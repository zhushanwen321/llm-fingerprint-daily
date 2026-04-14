"""端到端集成测试 -- 验证 Config -> Probe -> Execution -> Analysis -> Report 完整流水线。

只 mock LLMGateway (LLM API 调用)，其余全部使用真实模块。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.analyzer import AnalysisResult, analyze
from src.config.schema import (
    AppConfig,
    EvaluationConfig,
    ProviderConfig,
    TargetEntry,
    ThresholdsConfig,
    WeightsConfig,
)
from src.engine.llm_gateway import RawResponse
from src.engine.orchestrator import Orchestrator
from src.engine.storage import Storage
from src.probe.loader import load_probes
from src.report.generator import ReportGenerator


# ---- Mock Gateway ----

class MockGateway:
    """返回确定性响应的 mock gateway，支持部分探针失败"""

    def __init__(
        self,
        text: str = "This is a deterministic mock response for testing.",
        latency_ms: float = 50.0,
        fail_probe_ids: set[str] | None = None,
    ):
        self._text = text
        self._latency_ms = latency_ms
        self._fail_ids = fail_probe_ids or set()
        self._call_count = 0

    async def call(
        self, provider, model, messages, max_tokens=1024, temperature=0
    ):
        self._call_count += 1
        # 通过 prompt 内容识别是否应该失败
        prompt_text = messages[0]["content"] if messages else ""
        for fid in self._fail_ids:
            if fid in prompt_text:
                raise ConnectionError(f"mock failure for probe {fid}")

        return RawResponse(
            text=self._text,
            latency_ms=self._latency_ms,
            input_tokens=10,
            output_tokens=8,
            stop_reason="end_turn",
        )


class PartialFailGateway(MockGateway):
    """部分探针失败: instruction 成功，其余类型失败"""

    def __init__(self):
        super().__init__()
        self._should_fail = False

    async def call(
        self, provider, model, messages, max_tokens=1024, temperature=0
    ):
        self._call_count += 1
        if self._should_fail:
            raise ConnectionError("mock partial failure")
        return RawResponse(
            text=self._text,
            latency_ms=self._latency_ms,
            input_tokens=10,
            output_tokens=8,
            stop_reason="end_turn",
        )


# ---- 配置工厂 ----

def _make_config(
    probe_types: list[str] | None = None,
    targets: list[TargetEntry] | None = None,
    statistical_samples: int = 3,
) -> AppConfig:
    return AppConfig(
        providers={
            "mock": ProviderConfig(
                base_url="http://mock",
                api_key="test-key",
                concurrency=2,
            ),
        },
        evaluation=EvaluationConfig(
            schedule=[0],
            probe_types=probe_types or ["instruction"],
            statistical_samples=statistical_samples,
            targets=targets or [TargetEntry(model="mock__test-model")],
            thresholds=ThresholdsConfig(),
            weights=WeightsConfig(),
        ),
    )


def _probe_dir() -> str:
    """返回项目根目录下的 probes/ 目录路径"""
    return str(Path(__file__).resolve().parent.parent / "probes")


# ---- 分析结果序列化辅助 ----

def _analysis_to_dict(result: AnalysisResult) -> dict:
    """将 AnalysisResult 转为可序列化的字典"""
    dims = {}
    for name, ds in result.dimensions.items():
        dims[name] = {"score": ds.score, "detail": ds.detail, "alert_level": ds.alert_level}
    return {
        "model": result.model,
        "run_id": result.run_id,
        "baseline_run_id": result.baseline_run_id,
        "overall_score": result.overall_score,
        "alert_level": result.alert_level,
        "dimensions": dims,
        "alerts": [{"dimension": a.dimension, "level": a.level, "message": a.message} for a in result.alerts],
    }


# ===========================================================================
# 测试 1: 完整流水线 -- 首次运行 baseline + 二次运行分析 + 生成报告
# ===========================================================================

class TestFullPipeline:
    """验证 Config -> Probe -> Execution -> Analysis -> Report 全链路"""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, tmp_path):
        # 1. 准备
        config = _make_config(probe_types=["instruction"])
        storage = Storage(base_dir=tmp_path)
        gateway = MockGateway()

        orch = Orchestrator(
            config, gateway, storage, probe_dir=_probe_dir(),
        )

        # 2. 第一次运行 -> 自动设置 baseline
        with patch("src.engine.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414080001"
            run_id_1 = await orch.run()

        assert run_id_1 == "20260414080001"

        # 验证 baseline 自动设置
        baseline_id = await storage.get_baseline("mock__test-model")
        assert baseline_id == run_id_1

        # 验证数据已存储
        data_1 = await storage.load_run("mock__test-model", "instruction", run_id_1)
        assert data_1 is not None
        assert "meta" in data_1
        assert "results" in data_1
        assert data_1["meta"]["probe_type"] == "instruction"
        assert len(data_1["results"]) > 0

        # 3. 第二次运行 -> 与 baseline 对比
        with patch("src.engine.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414080002"
            run_id_2 = await orch.run()

        assert run_id_2 == "20260414080002"

        # baseline 不应被覆盖
        baseline_id_2 = await storage.get_baseline("mock__test-model")
        assert baseline_id_2 == run_id_1

        data_2 = await storage.load_run("mock__test-model", "instruction", run_id_2)
        assert data_2 is not None

        # 4. 分析: 当前 vs baseline
        current_runs = {"instruction": data_2}
        baseline_runs = {"instruction": data_1}

        result = analyze(current_runs, baseline_runs, config.evaluation)
        assert isinstance(result, AnalysisResult)
        assert result.model == "test-model"
        assert result.run_id == run_id_2
        assert result.baseline_run_id == run_id_1
        # 同样的 mock 响应，相似度应该很高
        assert result.overall_score >= 0.5

        # 5. 保存分析结果
        result_dict = _analysis_to_dict(result)
        await storage.save_analysis("mock__test-model", run_id_2, result_dict)

        # 6. 生成报告
        model_dir = tmp_path / "data" / "mock__test-model"
        report_gen = ReportGenerator(output_dir=tmp_path / "reports")
        report_gen.generate_and_save(model_dir)

        # 验证 HTML 报告已生成
        latest_report = tmp_path / "reports" / "latest.html"
        assert latest_report.exists()

        html = latest_report.read_text(encoding="utf-8")
        # 验证报告包含关键数据
        assert "test-model" in html
        assert "维度详情" in html
        assert "metadata" in html


# ===========================================================================
# 测试 2: 错误处理 -- 部分 probe 失败，流程不中断
# ===========================================================================

class TestErrorHandling:
    """部分探针失败时，错误被记录，分析跳过，报告正常生成"""

    @pytest.mark.asyncio
    async def test_partial_failure(self, tmp_path):
        config = _make_config(probe_types=["instruction"])
        storage = Storage(base_dir=tmp_path)

        # 使用会失败的 gateway
        fail_gateway = PartialFailGateway()
        fail_gateway._should_fail = True

        orch = Orchestrator(
            config, fail_gateway, storage, probe_dir=_probe_dir(),
        )

        # 即使所有调用失败，run 也应完成
        run_id = await orch.run()
        assert run_id is not None

        data = await storage.load_run("mock__test-model", "instruction", run_id)
        assert data is not None

        # 所有结果应该是 error
        for item in data["results"]:
            assert "error" in item

        # 分析应该在无 baseline 情况下正常运行
        current_runs = {"instruction": data}
        result = analyze(current_runs, None, config.evaluation)
        assert isinstance(result, AnalysisResult)

        # 保存并生成报告
        result_dict = _analysis_to_dict(result)
        await storage.save_analysis("mock__test-model", run_id, result_dict)

        model_dir = tmp_path / "data" / "mock__test-model"
        report_gen = ReportGenerator(output_dir=tmp_path / "reports")
        report_gen.generate_and_save(model_dir)

        latest_report = tmp_path / "reports" / "latest.html"
        assert latest_report.exists()

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, tmp_path):
        """部分成功部分失败，分析仍可用"""
        config = _make_config(probe_types=["instruction"])
        storage = Storage(base_dir=tmp_path)
        gateway = MockGateway()

        orch = Orchestrator(
            config, gateway, storage, probe_dir=_probe_dir(),
        )

        # 第一次运行 (成功)
        with patch("src.engine.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414090001"
            run_id_1 = await orch.run()

        # 第二次运行: 构造部分失败的数据
        # 直接往 storage 写入包含 error 的数据
        data_1 = await storage.load_run("mock__test-model", "instruction", run_id_1)
        assert data_1 is not None

        # 手动构造包含部分 error 的第二次运行数据
        data_2 = {
            "meta": {
                "run_id": "20260414090002",
                "model": "test-model",
                "provider": "mock",
                "timestamp": "2026-04-14T09:00:02Z",
                "is_baseline": False,
                "baseline_run_id": None,
                "probe_type": "instruction",
            },
            "results": [
                # 一个成功
                data_1["results"][0] if data_1["results"] else {
                    "probe_id": "test",
                    "response": {"text": "ok", "latency_ms": 50, "input_tokens": 10, "output_tokens": 8, "stop_reason": "end_turn"},
                },
                # 一个失败
                {
                    "probe_id": "failed_probe",
                    "request": {"prompt": "test"},
                    "error": {"type": "ConnectionError", "message": "mock failure"},
                },
            ],
        }
        await storage.save_run("mock__test-model", "instruction", "20260414090002", data_2)

        # 分析
        current_runs = {"instruction": data_2}
        baseline_runs = {"instruction": data_1}
        result = analyze(current_runs, baseline_runs, config.evaluation)
        assert isinstance(result, AnalysisResult)
        # 分析不应因部分失败而崩溃
        assert result.overall_score >= 0.0


# ===========================================================================
# 测试 3: 探针加载集成 -- 从 probes/ 加载真实探针数据
# ===========================================================================

class TestProbeLoadingIntegration:
    """验证真实探针文件能被正确加载"""

    def test_load_all_probe_types(self):
        probes = load_probes(_probe_dir())
        # 至少应包含 instruction 类型
        assert len(probes) > 0
        # 检查所有预期类型都能加载
        expected_types = {"instruction", "statistical", "coding_frontend", "coding_backend", "style_open", "consistency"}
        loaded_types = set(probes.keys())
        assert loaded_types == expected_types

    def test_instruction_probes_valid(self):
        probes = load_probes(_probe_dir(), ["instruction"])
        assert "instruction" in probes
        assert len(probes["instruction"]) > 0
        for p in probes["instruction"]:
            assert p.id
            assert p.prompt
            assert p.type == "instruction"

    def test_statistical_probes_valid(self):
        probes = load_probes(_probe_dir(), ["statistical"])
        assert "statistical" in probes
        assert len(probes["statistical"]) > 0
        for p in probes["statistical"]:
            assert p.id
            assert p.prompt
            assert p.type == "statistical"

    def test_coding_frontend_probes_valid(self):
        probes = load_probes(_probe_dir(), ["coding_frontend"])
        assert "coding_frontend" in probes
        assert len(probes["coding_frontend"]) > 0
        for p in probes["coding_frontend"]:
            assert p.id
            assert p.prompt
            assert p.type == "coding_frontend"
            assert p.scoring is not None

    def test_coding_backend_probes_valid(self):
        probes = load_probes(_probe_dir(), ["coding_backend"])
        assert "coding_backend" in probes
        assert len(probes["coding_backend"]) > 0
        for p in probes["coding_backend"]:
            assert p.id
            assert p.prompt
            assert p.type == "coding_backend"

    def test_style_open_probes_valid(self):
        probes = load_probes(_probe_dir(), ["style_open"])
        assert "style_open" in probes
        assert len(probes["style_open"]) > 0
        for p in probes["style_open"]:
            assert p.id
            assert p.prompt
            assert p.type == "style_open"
            assert p.analysis is not None

    def test_consistency_probes_valid(self):
        probes = load_probes(_probe_dir(), ["consistency"])
        assert "consistency" in probes
        assert len(probes["consistency"]) > 0
        for p in probes["consistency"]:
            assert p.id
            assert p.type == "consistency"
            assert len(p.variants) >= 2

    def test_filter_by_type(self):
        probes = load_probes(_probe_dir(), ["instruction", "statistical"])
        assert set(probes.keys()) == {"instruction", "statistical"}
        # 不应包含其他类型
        assert "coding_frontend" not in probes


# ===========================================================================
# 测试 4: 多探针类型流水线
# ===========================================================================

class TestMultiProbeTypePipeline:
    """验证多种探针类型在同一流水线中正确执行"""

    @pytest.mark.asyncio
    async def test_instruction_and_statistical(self, tmp_path):
        config = _make_config(
            probe_types=["instruction", "statistical"],
            statistical_samples=2,
        )
        storage = Storage(base_dir=tmp_path)
        gateway = MockGateway()

        orch = Orchestrator(
            config, gateway, storage, probe_dir=_probe_dir(),
        )

        run_id = await orch.run()

        # 两种类型都应有数据
        inst_data = await storage.load_run("mock__test-model", "instruction", run_id)
        stat_data = await storage.load_run("mock__test-model", "statistical", run_id)

        assert inst_data is not None
        assert stat_data is not None
        assert inst_data["meta"]["probe_type"] == "instruction"
        assert stat_data["meta"]["probe_type"] == "statistical"

        # statistical 应有多个采样结果
        assert len(stat_data["results"]) > 0

        # 分析应覆盖多个维度
        current_runs = {"instruction": inst_data, "statistical": stat_data}
        result = analyze(current_runs, None, config.evaluation)
        # 无 baseline 时所有维度都是默认分
        assert "metadata" in result.dimensions
