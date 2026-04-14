"""TargetRunner — 针对单个 target 的单个 probe_type 执行器。

职责:
  - 遍历 probes，按类型决定调用策略
  - 收集结果，保存到 Storage
  - 返回结构化结果 (meta + results)

调用策略:
  - instruction/coding/style: 每个 probe 一次调用
  - consistency: 每个 variant 一次调用
  - statistical: 每个 probe 采样 N 次，temperature > 0
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from src.engine.storage import Storage
from src.probe.schema import (
    ConsistencyProbe,
    Probe,
    StatisticalProbe,
)

logger = logging.getLogger(__name__)

# statistical 探针使用 temperature > 0 以获得多样性采样
_STAT_TEMPERATURE = 0.7


class _Gateway(Protocol):
    """LLMGateway 的协议类型，方便测试时注入 mock"""

    async def call(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0,
    ): ...


class TargetRunner:
    def __init__(
        self,
        gateway: _Gateway,
        storage: Storage,
        statistical_samples: int = 20,
    ) -> None:
        self._gateway = gateway
        self._storage = storage
        self._statistical_samples = statistical_samples

    async def run(
        self,
        model_dir: str,
        probe_type: str,
        probes: list[Probe],
        run_id: str,
    ) -> dict:
        """执行一批 probes，返回结构化结果并保存"""
        provider, model = model_dir.split("__", 1)
        meta = self._build_meta(run_id, provider, model, probe_type)
        results = []

        for probe in probes:
            probe_results = await self._execute_probe(
                provider, model, probe, probe_type
            )
            results.extend(probe_results)

        data = {"meta": meta, "results": results}
        await self._storage.save_run(model_dir, probe_type, run_id, data)
        return data

    def _build_meta(
        self, run_id: str, provider: str, model: str, probe_type: str
    ) -> dict:
        return {
            "run_id": run_id,
            "model": model,
            "provider": provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_baseline": False,
            "baseline_run_id": None,
            "probe_type": probe_type,
        }

    async def _execute_probe(
        self,
        provider: str,
        model: str,
        probe: Probe,
        probe_type: str,
    ) -> list[dict]:
        """按 probe 类型分发执行策略"""
        if probe_type == "consistency" and isinstance(probe, ConsistencyProbe):
            return await self._run_consistency(provider, model, probe)
        if probe_type == "statistical" and isinstance(probe, StatisticalProbe):
            return await self._run_statistical(provider, model, probe)
        return [await self._run_single(provider, model, probe.id, probe.prompt, probe.max_tokens)]

    async def _run_single(
        self, provider: str, model: str, probe_id: str, prompt: str, max_tokens: int
    ) -> dict:
        """单次调用：instruction/coding/style 探针"""
        messages = [{"role": "user", "content": prompt}]
        request = {
            "prompt": prompt,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        try:
            resp = await self._gateway.call(
                provider, model, messages, max_tokens
            )
            return self._build_result(probe_id, request, resp)
        except Exception as exc:
            return self._build_error(probe_id, request, exc)

    async def _run_consistency(
        self, provider: str, model: str, probe: ConsistencyProbe
    ) -> list[dict]:
        """consistency 探针：每个 variant 一次调用"""
        results = []
        for variant in probe.variants:
            messages = [{"role": "user", "content": variant.prompt}]
            request = {
                "prompt": variant.prompt,
                "variant_label": variant.label,
                "temperature": 0,
                "max_tokens": probe.max_tokens,
            }
            try:
                resp = await self._gateway.call(
                    provider, model, messages, probe.max_tokens
                )
                results.append(self._build_result(probe.id, request, resp))
            except Exception as exc:
                results.append(self._build_error(probe_id=probe.id, request=request, exc=exc))
        return results

    async def _run_statistical(
        self, provider: str, model: str, probe: StatisticalProbe
    ) -> list[dict]:
        """statistical 探针：同一 prompt 调用 N 次，temperature > 0"""
        messages = [{"role": "user", "content": probe.prompt}]
        request = {
            "prompt": probe.prompt,
            "temperature": _STAT_TEMPERATURE,
            "max_tokens": probe.max_tokens,
        }
        results = []
        for _ in range(self._statistical_samples):
            try:
                resp = await self._gateway.call(
                    provider, model, messages, probe.max_tokens,
                    temperature=_STAT_TEMPERATURE,
                )
                results.append(self._build_result(probe.id, request, resp))
            except Exception as exc:
                results.append(self._build_error(probe.id, request, exc))
        return results

    @staticmethod
    def _build_result(probe_id: str, request: dict, resp) -> dict:
        return {
            "probe_id": probe_id,
            "request": request,
            "response": {
                "text": resp.text,
                "latency_ms": resp.latency_ms,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "stop_reason": resp.stop_reason,
            },
        }

    @staticmethod
    def _build_error(probe_id: str, request: dict, exc: Exception) -> dict:
        return {
            "probe_id": probe_id,
            "request": request,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
