"""Orchestrator — 系统唯一的运行入口。

职责:
  - 生成 run_id
  - 按 provider 分组 target
  - 并行调度 ProviderRunner
  - 首次运行自动设置 baseline
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from src.config.schema import AppConfig
from src.engine.provider_runner import ProviderRunner
from src.engine.storage import Storage
from src.probe.loader import load_probes

logger = logging.getLogger(__name__)


class _Gateway:
    """LLMGateway 协议类型"""

    async def call(
        self,
        _provider: str,
        _model: str,
        _messages: list[dict],
        _max_tokens: int = 1024,
        _temperature: float = 0,
    ): ...


class Orchestrator:
    def __init__(
        self,
        config: AppConfig,
        gateway: _Gateway,
        storage: Storage,
        probe_dir: str,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._storage = storage
        self._probe_dir = probe_dir

    async def run(
        self,
        model_filter: str | None = None,
        type_filter: str | None = None,
    ) -> str:
        """执行一次完整的评测运行，返回 run_id"""
        run_id = datetime.now().strftime("%Y%m%d%H%M%S")
        eval_cfg = self._config.evaluation

        # 确定要执行的 probe_types
        probe_types = [type_filter] if type_filter else eval_cfg.probe_types

        # 加载探针
        all_probes = load_probes(self._probe_dir, probe_types)

        # 收集并过滤 enabled targets
        targets = [
            t for t in eval_cfg.targets
            if t.enabled and (model_filter is None or t.model == model_filter)
        ]

        # 按 provider 分组
        grouped: dict[str, list[str]] = defaultdict(list)
        for t in targets:
            provider = t.model.split("__", 1)[0]
            grouped[provider].append(t.model)

        # 为每个 provider 构建 ProviderRunner 并并行执行
        tasks = []
        for provider, model_dirs in grouped.items():
            concurrency = self._config.providers[provider].concurrency
            runner = ProviderRunner(
                provider, concurrency, self._gateway, self._storage,
                eval_cfg.statistical_samples,
            )
            # 将 model_dirs 转换为 ProviderRunner.run 所需的格式
            runner_targets = []
            for md in model_dirs:
                pt_list = [pt for pt in probe_types if pt in all_probes]
                probes_map = {pt: all_probes.get(pt, []) for pt in pt_list}
                runner_targets.append((md, pt_list, probes_map))
            tasks.append(runner.run(runner_targets, run_id))

        await asyncio.gather(*tasks)

        # 首次运行自动设置 baseline
        for t in targets:
            current = await self._storage.get_baseline(t.model)
            if current is None:
                await self._storage.set_baseline(t.model, run_id, set_by="auto")

        logger.info("run %s completed, %d targets executed", run_id, len(targets))
        return run_id
