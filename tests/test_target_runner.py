"""TargetRunner 单元测试 — 验证各 probe_type 的执行路径"""

from __future__ import annotations

import pytest

from src.engine.target_runner import TargetRunner
from src.engine.storage import Storage
from src.engine.llm_gateway import RawResponse
from src.probe.schema import (
    SimpleProbe,
    StatisticalProbe,
    ConsistencyProbe,
    Variant,
)


# ---- Mock Gateway ----

class MockGateway:
    """模拟 LLMGateway，记录调用历史"""

    def __init__(self):
        self.calls: list[dict] = []

    async def call(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0,
    ) -> RawResponse:
        self.calls.append({
            "provider": provider,
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return RawResponse(
            text="mock response",
            latency_ms=100.0,
            input_tokens=10,
            output_tokens=5,
            stop_reason="end_turn",
        )


# ---- 测试数据 ----

_PROBES = [
    SimpleProbe(
        id="instruction_001",
        type="instruction",
        language="zh",
        prompt="hello",
        max_tokens=500,
    ),
    SimpleProbe(
        id="instruction_002",
        type="instruction",
        language="zh",
        prompt="world",
        max_tokens=500,
    ),
]

_CONSISTENCY_PROBES = [
    ConsistencyProbe(
        id="consistency_001",
        type="consistency",
        language="zh",
        variants=[
            Variant(label="v1", prompt="question A"),
            Variant(label="v2", prompt="question B"),
            Variant(label="v3", prompt="question C"),
        ],
    ),
]

_STAT_PROBES = [
    StatisticalProbe(
        id="stat_001",
        type="statistical",
        language="zh",
        prompt="coin flip",
        max_tokens=300,
    ),
    StatisticalProbe(
        id="stat_002",
        type="statistical",
        language="zh",
        prompt="random number",
        max_tokens=300,
    ),
]


# ---- 测试类 ----

class TestInstructionProbes:
    """instruction 探针：每个 probe 一次调用"""

    @pytest.mark.asyncio
    async def test_run_instruction_probes(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage)
        result = await runner.run(
            "test__model-a", "instruction", _PROBES, run_id="20260414100003"
        )
        assert result["meta"]["probe_type"] == "instruction"
        assert len(result["results"]) == len(_PROBES)
        assert len(gateway.calls) == len(_PROBES)


class TestConsistencyProbes:
    """consistency 探针：每个 variant 一次调用"""

    @pytest.mark.asyncio
    async def test_run_consistency_calls_all_variants(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage)
        result = await runner.run(
            "test__model-a",
            "consistency",
            _CONSISTENCY_PROBES,
            run_id="20260414100003",
        )
        # 1 个 probe，3 个 variants → 3 次 API 调用
        assert len(result["results"]) == 3
        assert len(gateway.calls) == 3


class TestStatisticalProbes:
    """statistical 探针：每个 probe 调用 N 次，temperature > 0"""

    @pytest.mark.asyncio
    async def test_run_statistical_samples_n_times(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage, statistical_samples=5)
        result = await runner.run(
            "test__model-a",
            "statistical",
            _STAT_PROBES,
            run_id="20260414100003",
        )
        # 2 个 probe × 5 次采样 = 10 次调用
        assert len(result["results"]) == len(_STAT_PROBES) * 5
        assert len(gateway.calls) == len(_STAT_PROBES) * 5
        # 验证 temperature > 0
        for c in gateway.calls:
            assert c["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_default_statistical_samples(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage)
        result = await runner.run(
            "test__model-a",
            "statistical",
            [_STAT_PROBES[0]],
            run_id="20260414100003",
        )
        # 默认 20 次采样
        assert len(result["results"]) == 20


class TestResultStructure:
    """验证返回结构包含正确的 meta 和 results 字段"""

    @pytest.mark.asyncio
    async def test_meta_fields(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage)
        result = await runner.run(
            "test__model-a", "instruction", _PROBES, run_id="20260414100003"
        )
        meta = result["meta"]
        assert meta["run_id"] == "20260414100003"
        assert meta["model"] == "model-a"
        assert meta["provider"] == "test"
        assert meta["probe_type"] == "instruction"
        assert "timestamp" in meta

    @pytest.mark.asyncio
    async def test_result_item_structure(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage)
        result = await runner.run(
            "test__model-a", "instruction", _PROBES[:1], run_id="20260414100003"
        )
        item = result["results"][0]
        assert "probe_id" in item
        assert "request" in item
        assert "response" in item
        assert item["response"]["text"] == "mock response"
        assert item["response"]["latency_ms"] == 100.0

    @pytest.mark.asyncio
    async def test_saved_to_storage(self, tmp_path):
        gateway = MockGateway()
        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(gateway, storage)
        await runner.run(
            "test__model-a", "instruction", _PROBES, run_id="20260414100003"
        )
        loaded = await storage.load_run(
            "test__model-a", "instruction", "20260414100003"
        )
        assert loaded is not None
        assert len(loaded["results"]) == len(_PROBES)


class TestErrorHandling:
    """网关异常时记录 error 而非 response"""

    @pytest.mark.asyncio
    async def test_gateway_error_recorded(self, tmp_path):
        class FailGateway:
            async def call(self, provider, model, messages, max_tokens=1024, temperature=0):
                raise TimeoutError("connection timed out")

        storage = Storage(base_dir=tmp_path)
        runner = TargetRunner(FailGateway(), storage)
        result = await runner.run(
            "test__model-a", "instruction", _PROBES[:1], run_id="20260414100003"
        )
        assert len(result["results"]) == 1
        item = result["results"][0]
        assert "error" in item
        assert item["error"]["type"] == "TimeoutError"
        assert "response" not in item
