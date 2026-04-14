"""Orchestrator + ProviderRunner 集成测试。

验证：
  - 统一 run_id 生成
  - 多 provider 并行执行
  - 首次运行自动设置 baseline
  - 后续运行不覆盖 baseline
  - 错误探针结果不影响整体流程
"""

from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import patch

from src.config.schema import (
    AppConfig,
    EvaluationConfig,
    ModelEntry,
    ProviderConfig,
    TargetEntry,
)
from src.engine.storage import Storage
from src.engine.orchestrator import Orchestrator


# ---- 探针 fixture 数据 ----

_INSTRUCTION_PROBES = [
    {"id": "inst_001", "type": "instruction", "language": "zh", "prompt": "hello"},
]

_CONSISTENCY_PROBES = [
    {
        "id": "cons_001",
        "type": "consistency",
        "language": "zh",
        "variants": [
            {"label": "v1", "prompt": "q1"},
            {"label": "v2", "prompt": "q2"},
        ],
    },
]


def _write_probes(probe_dir, probes: list[dict]) -> None:
    """写入探针 JSON 文件"""
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "probes.json").write_text(
        json.dumps(probes, ensure_ascii=False), encoding="utf-8"
    )


# ---- 工厂 ----

def _make_config(
    targets: list[TargetEntry] | None = None,
    probe_types: list[str] | None = None,
) -> AppConfig:
    return AppConfig(
        providers={
            "test": ProviderConfig(
                base_url="http://fake", api_key="k1", concurrency=2
            ),
            "other": ProviderConfig(
                base_url="http://fake2", api_key="k2", concurrency=1
            ),
        },
        models=[
            ModelEntry(name="model-a", provider="test"),
            ModelEntry(name="model-b", provider="other"),
        ],
        evaluation=EvaluationConfig(
            schedule=[0],
            probe_types=probe_types or ["instruction"],
            statistical_samples=2,
            targets=targets
            or [
                TargetEntry(model="test__model-a"),
                TargetEntry(model="other__model-b"),
            ],
        ),
    )


class _FakeGateway:
    """始终返回成功响应的 mock gateway"""

    def __init__(self):
        from src.engine.llm_gateway import RawResponse

        self._resp = RawResponse(
            text="ok", latency_ms=10, input_tokens=1, output_tokens=1,
            stop_reason="end_turn",
        )

    async def call(self, provider, model, messages, max_tokens=1024, temperature=0):
        return self._resp


class _FailGateway:
    """始终抛异常的 mock gateway"""

    async def call(self, provider, model, messages, max_tokens=1024, temperature=0):
        raise ConnectionError("refused")


def _make_orchestrator(tmp_path, gateway, probe_types=None, targets=None):
    """构建 orchestrator 并写入探针 fixture"""
    config = _make_config(probe_types=probe_types, targets=targets)
    storage = Storage(base_dir=tmp_path)
    probe_dir = tmp_path / "probes"

    # 根据 probe_types 写入对应探针
    pts = probe_types or ["instruction"]
    all_probes = []
    if "instruction" in pts:
        all_probes.extend(_INSTRUCTION_PROBES)
    if "consistency" in pts:
        all_probes.extend(_CONSISTENCY_PROBES)
    _write_probes(probe_dir, all_probes)

    orch = Orchestrator(config, gateway, storage, probe_dir=str(probe_dir))
    return orch, storage


# ---- 测试 ----

class TestFirstRunSetsBaseline:
    """首次运行自动将 run_id 设为 baseline"""

    @pytest.mark.asyncio
    async def test_auto_baseline(self, tmp_path):
        orch, storage = _make_orchestrator(tmp_path, _FakeGateway())

        run_id = await orch.run()
        assert len(run_id) == 14

        baseline = await storage.get_baseline("test__model-a")
        assert baseline == run_id

        baseline2 = await storage.get_baseline("other__model-b")
        assert baseline2 == run_id


class TestSecondRunDoesNotOverrideBaseline:
    """后续运行不覆盖已有 baseline"""

    @pytest.mark.asyncio
    async def test_baseline_unchanged(self, tmp_path):
        orch, storage = _make_orchestrator(tmp_path, _FakeGateway())

        with patch("src.engine.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414100001"
            first_id = await orch.run()
            assert first_id == "20260414100001"

        with patch("src.engine.orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414100002"
            second_id = await orch.run()
            assert second_id == "20260414100002"

        baseline = await storage.get_baseline("test__model-a")
        assert baseline == first_id
        assert baseline != second_id


class TestErrorResultsSkipped:
    """网关异常时探针结果记录 error，不中断整体流程"""

    @pytest.mark.asyncio
    async def test_error_recorded_but_run_completes(self, tmp_path):
        orch, storage = _make_orchestrator(tmp_path, _FailGateway())

        run_id = await orch.run()
        assert run_id is not None

        data = await storage.load_run("test__model-a", "instruction", run_id)
        assert data is not None
        for item in data["results"]:
            assert "error" in item


class TestModelFilter:
    """model_filter 只执行匹配的 target"""

    @pytest.mark.asyncio
    async def test_filter_single_model(self, tmp_path):
        orch, storage = _make_orchestrator(tmp_path, _FakeGateway())

        run_id = await orch.run(model_filter="test__model-a")

        data = await storage.load_run("other__model-b", "instruction", run_id)
        assert data is None

        data_a = await storage.load_run("test__model-a", "instruction", run_id)
        assert data_a is not None


class TestTypeFilter:
    """type_filter 只执行匹配的 probe_type"""

    @pytest.mark.asyncio
    async def test_filter_probe_type(self, tmp_path):
        orch, storage = _make_orchestrator(
            tmp_path, _FakeGateway(), probe_types=["instruction", "consistency"]
        )

        run_id = await orch.run(type_filter="instruction")

        data = await storage.load_run("test__model-a", "consistency", run_id)
        assert data is None

        data_i = await storage.load_run("test__model-a", "instruction", run_id)
        assert data_i is not None


class TestMultiProviderParallel:
    """多个 provider 应并行执行"""

    @pytest.mark.asyncio
    async def test_both_providers_execute(self, tmp_path):
        orch, storage = _make_orchestrator(tmp_path, _FakeGateway())

        run_id = await orch.run()

        data_a = await storage.load_run("test__model-a", "instruction", run_id)
        data_b = await storage.load_run("other__model-b", "instruction", run_id)
        assert data_a is not None
        assert data_b is not None
