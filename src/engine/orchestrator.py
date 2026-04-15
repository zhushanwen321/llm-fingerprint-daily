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

from src.analysis.analyzer import analyze
from src.config.schema import AppConfig, EvaluationConfig
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

        # 按 provider 分组，构造内部 model_dir = "provider__model"
        grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for t in targets:
            model_dir = f"{t.provider}__{t.model}"
            grouped[t.provider].append((model_dir, t.model))

        # 为每个 provider 构建 ProviderRunner 并并行执行
        tasks = []
        for provider, model_entries in grouped.items():
            runner = ProviderRunner(
                provider, self._gateway, self._storage,
                eval_cfg.statistical_samples,
            )
            runner_targets = []
            for model_dir, _model in model_entries:
                pt_list = [pt for pt in probe_types if pt in all_probes]
                probes_map = {pt: all_probes.get(pt, []) for pt in pt_list}
                runner_targets.append((model_dir, pt_list, probes_map))
            tasks.append(runner.run(runner_targets, run_id))

        await asyncio.gather(*tasks)

        # 首次运行自动设置 baseline
        for t in targets:
            model_dir = f"{t.provider}__{t.model}"
            current = await self._storage.get_baseline(model_dir)
            if current is None:
                await self._storage.set_baseline(model_dir, run_id, set_by="auto")

        # 对每个模型执行分析并保存结果
        for t in targets:
            model_dir = f"{t.provider}__{t.model}"
            await self._analyze_model(model_dir, run_id, eval_cfg)

        logger.info("run %s completed, %d targets executed", run_id, len(targets))
        return run_id

    async def _analyze_model(
        self,
        model_dir: str,
        run_id: str,
        eval_cfg: EvaluationConfig,
    ) -> None:
        """加载当前 run 和 baseline 数据，执行分析并保存"""
        import json
        from dataclasses import asdict

        # 加载当前 run 的所有 probe_type 数据
        current_runs: dict[str, dict] = {}
        model_path = self._storage._model_path(model_dir)
        if model_path.exists():
            for pt_dir in model_path.iterdir():
                if not pt_dir.is_dir() or pt_dir.name == "analysis":
                    continue
                run_file = pt_dir / f"{run_id}.json"
                if run_file.exists():
                    current_runs[pt_dir.name] = json.loads(
                        run_file.read_text(encoding="utf-8")
                    )

        if not current_runs:
            return

        # 加载 baseline 数据
        baseline_runs: dict[str, dict] | None = None
        baseline_run_id = await self._storage.get_baseline(model_dir)
        if baseline_run_id and baseline_run_id != run_id:
            baseline_runs = {}
            for pt_dir in model_path.iterdir():
                if not pt_dir.is_dir() or pt_dir.name == "analysis":
                    continue
                run_file = pt_dir / f"{baseline_run_id}.json"
                if run_file.exists():
                    baseline_runs[pt_dir.name] = json.loads(
                        run_file.read_text(encoding="utf-8")
                    )

        result = analyze(current_runs, baseline_runs, eval_cfg)
        analysis_dict = asdict(result)
        await self._storage.save_analysis(model_dir, run_id, analysis_dict)
        logger.info(
            "analysis saved: %s run=%s score=%.4f alert=%s",
            model_dir, run_id, result.overall_score, result.alert_level,
        )
