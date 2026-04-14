"""CLI 入口 -- typer 应用，定义子命令和参数。

子命令：
  run       执行一次评测
  report    生成 HTML 报告
  history   查看历史评分
  serve     启动定时调度
  baseline  手动设置基线
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import typer

from src.cli_service import (
    generate_report,
    list_history,
    load_and_run,
    set_baseline,
)

app = typer.Typer(help="LLM 指纹追踪工具")

# 默认路径
_DEFAULT_CONFIG = "config.yaml"
_DEFAULT_DATA = "."
_DEFAULT_PROBES = "probes"


@app.command(help="执行一次评测运行")
def run(
    model: str | None = typer.Option(None, "--model", help="过滤指定模型"),
    type: str | None = typer.Option(None, "--type", help="过滤探针类型"),
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", help="配置文件路径"),
    data_dir: Path = typer.Option(_DEFAULT_DATA, "--data-dir", help="数据目录"),
    probe_dir: Path = typer.Option(_DEFAULT_PROBES, "--probe-dir", help="探针目录"),
):
    result = asyncio.run(
        load_and_run(
            config_path=str(config),
            data_dir=str(data_dir),
            probe_dir=str(probe_dir),
            model_filter=model,
            type_filter=type,
        )
    )
    typer.echo(f"运行完成: run_id={result['run_id']}")
    typer.echo(f"评测模型: {', '.join(result['models'])}")


@app.command(help="生成 HTML 报告")
def report(
    path: Path = typer.Argument(".", help="模型目录路径"),
    all_models: bool = typer.Option(False, "--all", help="生成全局对比报告"),
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", help="配置文件路径"),
    data_dir: Path = typer.Option(_DEFAULT_DATA, "--data-dir", help="数据目录"),
):
    from src.config.loader import load_config

    cfg = load_config(str(config))
    output_dir = cfg.report.output_dir

    out = generate_report(
        data_dir=str(data_dir),
        output_dir=output_dir,
        model_path=str(path) if not all_models else None,
        all_models=all_models,
    )
    typer.echo(f"报告已生成: {out}")


@app.command(help="查看历史评分记录")
def history(
    path: Path = typer.Argument(".", help="数据目录或模型目录"),
):
    records = list_history(str(path))
    if not records:
        typer.echo("暂无历史记录")
        return

    typer.echo(f"{'run_id':<18} {'model':<20} {'score':>8}")
    typer.echo("-" * 48)
    for r in records:
        score = r["overall_score"]
        score_str = f"{score:.2%}" if score is not None else "N/A"
        typer.echo(f"{r['run_id']:<18} {r['model']:<20} {score_str:>8}")


@app.command(help="启动定时调度服务")
def serve(
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", help="配置文件路径"),
    data_dir: Path = typer.Option(_DEFAULT_DATA, "--data-dir", help="数据目录"),
    probe_dir: Path = typer.Option(_DEFAULT_PROBES, "--probe-dir", help="探针目录"),
):
    from src.config.loader import load_config
    from src.engine.llm_gateway import LLMGateway
    from src.engine.storage import Storage
    from src.engine.orchestrator import Orchestrator
    from src.scheduler.core import FingerprintScheduler

    cfg = load_config(str(config))
    gateway = LLMGateway(cfg)
    storage = Storage(base_dir=data_dir)
    orch = Orchestrator(cfg, gateway, storage, probe_dir=str(probe_dir))
    scheduler = FingerprintScheduler(cfg, orch)

    loop = asyncio.new_event_loop()

    def _shutdown(_sig):
        scheduler.shutdown()
        loop.call_later(0.5, loop.stop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    typer.echo("调度服务已启动，按 Ctrl+C 停止")
    scheduler.start()
    loop.run_forever()
    typer.echo("调度服务已停止")


@app.command(help="手动设置模型基线")
def baseline(
    run_id: str = typer.Option(..., "--run-id", help="目标 run_id"),
    model: str = typer.Option(..., "--model", help="目标模型标识"),
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", help="配置文件路径"),
    data_dir: Path = typer.Option(_DEFAULT_DATA, "--data-dir", help="数据目录"),
):
    asyncio.run(set_baseline(
        data_dir=str(data_dir),
        model=model,
        run_id=run_id,
    ))
    typer.echo(f"已设置 {model} 的基线为 {run_id}")
