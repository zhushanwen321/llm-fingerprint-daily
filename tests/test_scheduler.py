"""调度器单元测试"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.config.schema import (
    AppConfig,
    EvaluationConfig,
    ProviderConfig,
)
from src.scheduler.core import FingerprintScheduler


def _make_config(schedule=None) -> AppConfig:
    """构造最小测试配置"""
    return AppConfig(
        providers={
            "test": ProviderConfig(
                base_url="https://api.test.com",
                api_key="key",
            )
        },
        evaluation=EvaluationConfig(
            schedule=schedule or [0, 6, 12, 18],
        ),
    )


class TestCronJobRegistration:
    """验证 cron job 注册逻辑"""

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_jobs_registered_for_each_hour(self, MockScheduler):
        """每个 schedule 小时应注册一个 cron job"""
        config = _make_config(schedule=[0, 4, 6, 10, 14, 18, 22])
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        mock_instance = MockScheduler.return_value
        assert mock_instance.add_job.call_count == 7

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_job_hour_and_minute(self, MockScheduler):
        """job 应在 HH:03 触发"""
        config = _make_config(schedule=[6, 18])
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        mock_instance = MockScheduler.return_value
        hours = {6, 18}
        for call in mock_instance.add_job.call_args_list:
            trigger = call.kwargs["trigger"]
            # APScheduler 3.x 字段索引: 5=hour, 6=minute
            assert trigger.fields[5].expressions[0].first in hours
            assert trigger.fields[6].expressions[0].first == 3

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_job_max_instances_and_coalesce(self, MockScheduler):
        """max_instances=1, coalesce=True"""
        config = _make_config(schedule=[0])
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        mock_instance = MockScheduler.return_value
        call_kwargs = mock_instance.add_job.call_args.kwargs
        assert call_kwargs["max_instances"] == 1
        assert call_kwargs["coalesce"] is True

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_job_misfire_grace_time(self, MockScheduler):
        """misfire_grace_time 应为 300 秒"""
        config = _make_config(schedule=[0])
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        mock_instance = MockScheduler.return_value
        call_kwargs = mock_instance.add_job.call_args.kwargs
        assert call_kwargs["misfire_grace_time"] == 300

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_job_calls_orchestrator_run(self, MockScheduler):
        """job 函数应调用 orchestrator.run"""
        config = _make_config(schedule=[0])
        orchestrator = AsyncMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        mock_instance = MockScheduler.return_value
        # APScheduler 3.x add_job 的 func 是第一个位置参数
        func = mock_instance.add_job.call_args.args[0]
        import asyncio
        asyncio.get_event_loop().run_until_complete(func())
        orchestrator.run.assert_awaited_once()

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_timezone_passed_to_trigger(self, MockScheduler):
        """timezone 应传递给 CronTrigger"""
        config = _make_config(schedule=[0])
        config.evaluation.timezone = "UTC"
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        mock_instance = MockScheduler.return_value
        call_kwargs = mock_instance.add_job.call_args.kwargs
        trigger = call_kwargs["trigger"]
        # APScheduler 3.x timezone 存储为 datetime.timezone 对象
        from datetime import timezone as dt_tz
        assert trigger.timezone == dt_tz.utc


class TestLifecycle:
    """启动和关闭生命周期"""

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_start_calls_scheduler_start(self, MockScheduler):
        config = _make_config(schedule=[0])
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()

        MockScheduler.return_value.start.assert_called_once()

    @patch("src.scheduler.core.AsyncIOScheduler")
    def test_shutdown_calls_scheduler_shutdown(self, MockScheduler):
        config = _make_config(schedule=[0])
        orchestrator = MagicMock()
        scheduler = FingerprintScheduler(config, orchestrator)
        scheduler.start()
        scheduler.shutdown()

        MockScheduler.return_value.shutdown.assert_called_once_with(wait=False)
