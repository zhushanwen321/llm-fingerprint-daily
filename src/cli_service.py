"""CLI 业务逻辑 -- 从 typer 命令中抽离的纯函数层。

职责：
  - 加载配置并创建组件
  - 调用 orchestrator / storage / report generator
  - 返回结构化结果供 CLI 层格式化输出
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config.loader import load_config
from src.engine.llm_gateway import LLMGateway
from src.engine.storage import Storage
from src.engine.orchestrator import Orchestrator


async def load_and_run(
    config_path: str,
    data_dir: str,
    probe_dir: str,
    model_filter: str | None = None,
    type_filter: str | None = None,
) -> dict:
    """加载配置、创建组件并执行一次评测"""
    config = load_config(config_path)
    gateway = LLMGateway(config)
    storage = Storage(base_dir=data_dir)
    orch = Orchestrator(config, gateway, storage, probe_dir=probe_dir)

    run_id = await orch.run(model_filter=model_filter, type_filter=type_filter)
    models = [t.model for t in config.evaluation.targets if t.enabled]
    return {"run_id": run_id, "models": models}


async def set_baseline(
    data_dir: str,
    model_dir: str,
    run_id: str,
) -> None:
    """手动设置指定模型的基线"""
    storage = Storage(base_dir=data_dir)
    await storage.set_baseline(model_dir, run_id, set_by="manual")


def list_history(data_dir: str, model_dir: str | None = None) -> list[dict]:
    """读取分析结果，返回按时间排序的历史记录列表"""
    base = Path(data_dir) / "data"

    if model_dir:
        dirs = [base / model_dir]
    elif base.exists():
        dirs = [d for d in base.iterdir() if d.is_dir()]
    else:
        return []

    results: list[dict] = []
    for d in dirs:
        analysis_dir = d / "analysis"
        if not analysis_dir.exists():
            continue
        for f in sorted(analysis_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "run_id": data.get("run_id", f.stem),
                "model": d.name,
                "overall_score": data.get("overall_score"),
            })
    return results


def generate_report(
    data_dir: str,
    output_dir: str,
    model_path: str | None = None,
    all_models: bool = False,
) -> str:
    """生成报告并返回输出路径"""
    from datetime import datetime, timezone

    from src.report.generator import ReportGenerator

    base = Path(data_dir) / "data"
    gen = ReportGenerator(output_dir=output_dir)

    # 发现所有模型目录
    model_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir()]
    ) if base.exists() else []

    if all_models:
        # 全局对比报告：保存 global_latest.html + 归档
        html = gen.generate_global_report(model_dirs)
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "global_latest.html").write_text(html, encoding="utf-8")
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        (out_path / f"global_{date_str}.html").write_text(html, encoding="utf-8")
    elif model_path and model_path != ".":
        # 指定模型目录
        gen.generate_and_save(Path(model_path))
    else:
        # 无指定路径或 path="."：为每个模型生成报告
        for md in model_dirs:
            gen.generate_and_save(md)

    return output_dir
