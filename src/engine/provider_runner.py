"""ProviderRunner — 单个 provider 下的所有 target 执行器。

并发控制由 LLMGateway 统一管理（Semaphore + Rate Limiter），
本模块只负责调度，不再维护独立的 Semaphore。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from src.engine.target_runner import TargetRunner

logger = logging.getLogger(__name__)


class _Gateway(Protocol):
    """LLMGateway 协议类型"""

    async def call(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0,
    ): ...


class _Storage(Protocol):
    """Storage 协议类型"""

    async def save_run(
        self, model_dir: str, probe_type: str, run_id: str, data: dict
    ) -> None: ...


class ProviderRunner:
    def __init__(
        self,
        provider: str,
        gateway: _Gateway,
        storage: _Storage,
        statistical_samples: int = 20,
    ) -> None:
        self._provider = provider
        self._target_runner = TargetRunner(
            gateway, storage, statistical_samples
        )

    async def run(
        self,
        targets: list[tuple[str, list[str], dict[str, list]]],
        run_id: str,
    ) -> None:
        """顺序执行该 provider 下所有 target 的所有 probe_type。

        targets: [(model_dir, [probe_type, ...], {probe_type: [probe, ...]}, ...)]

        并发控制完全由 Gateway 层负责，这里顺序调度每个 target。
        如果需要 target 级并发，应调整 Gateway 的 Semaphore。
        """
        for model_dir, probe_types, probes_map in targets:
            for pt in probe_types:
                probes = probes_map.get(pt, [])
                if probes:
                    await self._target_runner.run(
                        model_dir, pt, probes, run_id
                    )
