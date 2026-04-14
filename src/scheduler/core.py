"""调度器 -- 基于 APScheduler 的 cron 定时探针执行"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.schema import AppConfig

logger = logging.getLogger(__name__)


class FingerprintScheduler:
    """封装 APScheduler，按配置的 schedule 小时注册 cron job"""

    def __init__(self, config: AppConfig, orchestrator) -> None:
        self._config = config
        self._orchestrator = orchestrator
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """注册 cron job 并启动调度器"""
        eval_cfg = self._config.evaluation
        tz = eval_cfg.timezone

        for hour in eval_cfg.schedule:
            self._scheduler.add_job(
                self._run,
                trigger=CronTrigger(hour=hour, minute=3, timezone=tz),
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
            logger.info("registered cron job at %02d:03 (%s)", hour, tz)

        self._scheduler.start()
        logger.info(
            "scheduler started, %d jobs registered",
            len(eval_cfg.schedule),
        )

    def shutdown(self) -> None:
        """优雅关闭，不等待正在执行的任务"""
        self._scheduler.shutdown(wait=False)
        logger.info("scheduler shutdown")

    async def _run(self) -> None:
        """cron job 的实际执行入口"""
        await self._orchestrator.run()
