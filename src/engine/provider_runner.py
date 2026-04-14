"""ProviderRunner — 单个 provider 下的所有 target 执行器。

使用 provider 级别的 Semaphore 限制并发 target 数量，
对每个 target 调用 TargetRunner 完成探针执行。
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
        concurrency: int,
        gateway: _Gateway,
        storage: _Storage,
        statistical_samples: int = 20,
    ) -> None:
        self._provider = provider
        self._sem = asyncio.Semaphore(concurrency)
        self._target_runner = TargetRunner(
            gateway, storage, statistical_samples
        )

    async def run(
        self,
        targets: list[tuple[str, list[str], dict[str, list]]],
        run_id: str,
    ) -> None:
        """执行该 provider 下所有 target 的所有 probe_type。

        targets: [(model_dir, [probe_type, ...], {probe_type: [probe, ...]}, ...)]
        """
        async def _run_one(target: tuple):
            model_dir, probe_types, probes_map = target
            async with self._sem:
                for pt in probe_types:
                    probes = probes_map.get(pt, [])
                    if probes:
                        await self._target_runner.run(
                            model_dir, pt, probes, run_id
                        )

        await asyncio.gather(*[_run_one(t) for t in targets])
