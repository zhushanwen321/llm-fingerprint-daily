"""配置数据模型的单元测试"""

import pytest
from pydantic import ValidationError

from src.config.schema import (
    AppConfig,
    EvaluationConfig,
    ModelEntry,
    ProviderConfig,
    ReportConfig,
    TargetEntry,
    ThresholdsConfig,
    WeightsConfig,
)


def _make_minimal_config(**overrides) -> AppConfig:
    """构造最小可用配置，支持覆盖字段"""
    defaults = {
        "providers": {
            "test": ProviderConfig(
                base_url="https://api.test.com",
                api_key="key123",
                concurrency=2,
            )
        },
        "models": [
            ModelEntry(
                name="model-a",
                provider="test",
                display_name="Model A",
            )
        ],
        "evaluation": EvaluationConfig(
            schedule=[0, 12],
            probe_types=["instruction"],
            max_llm_concurrent=3,
            targets=[TargetEntry(model="model-a", enabled=True)],
        ),
        "report": ReportConfig(),
    }
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestMinimalConfig:
    """最小配置解析"""

    def test_parse_minimal_config(self):
        config = _make_minimal_config()
        assert config.providers["test"].concurrency == 2
        assert config.evaluation.schedule == [0, 12]
        assert len(config.evaluation.targets) == 1

    def test_defaults(self):
        config = _make_minimal_config()
        assert config.evaluation.timezone == "Asia/Shanghai"
        assert config.evaluation.statistical_samples == 20
        assert config.evaluation.timeout == 60
        assert config.evaluation.max_retries == 5
        assert config.evaluation.retry_intervals == [5, 10, 30, 60]


class TestEdgeCases:
    """边界条件测试"""

    def test_retry_intervals_beyond_array(self):
        """超出重试次数时取最后一个间隔值"""
        intervals = [5, 10]
        # 取第3次重试间隔(索引2)，应返回最后一个值
        result = AppConfig.get_retry_interval(intervals, 3)
        assert result == 10

    def test_retry_intervals_within_array(self):
        result = AppConfig.get_retry_interval([5, 10, 30], 1)
        assert result == 5

    def test_weights_sum_validation_pass(self):
        """权重总和为1.0时通过验证"""
        weights = WeightsConfig(
            capability=0.30,
            text_similarity=0.25,
            behavior=0.20,
            metadata=0.10,
            statistical=0.15,
        )
        assert abs(weights.capability + weights.text_similarity +
                   weights.behavior + weights.metadata + weights.statistical - 1.0) < 1e-9

    def test_weights_sum_validation_fail(self):
        """权重总和不等于1.0时应报错"""
        with pytest.raises(ValidationError):
            WeightsConfig(
                capability=0.50,
                text_similarity=0.40,
                behavior=0.0,
                metadata=0.0,
                statistical=0.0,
            )

    def test_concurrency_constraint_pass(self):
        """provider 并发数总和不超过 max_llm_concurrent"""
        config = _make_minimal_config()
        # test provider concurrency=2, max_llm_concurrent=3
        assert config.validate_concurrency() is True

    def test_concurrency_constraint_fail(self):
        """并发数超限应报错"""
        config = _make_minimal_config()
        config.evaluation.max_llm_concurrent = 1
        with pytest.raises(ValueError):
            config.validate_concurrency(raise_on_error=True)

    def test_api_key_env_format(self):
        """api_key 支持 ${ENV_VAR} 格式"""
        p = ProviderConfig(
            base_url="https://api.test.com",
            api_key="${MY_API_KEY}",
            concurrency=1,
        )
        assert p.api_key == "${MY_API_KEY}"

    def test_model_entry_fields(self):
        m = ModelEntry(name="m1", provider="p1", display_name="M1")
        assert m.name == "m1"
        assert m.provider == "p1"

    def test_target_entry_with_baseline(self):
        t = TargetEntry(model="m1", enabled=True, baseline_run_id="run-001")
        assert t.baseline_run_id == "run-001"

    def test_target_entry_without_baseline(self):
        t = TargetEntry(model="m1", enabled=True)
        assert t.baseline_run_id is None

    def test_thresholds_defaults(self):
        th = ThresholdsConfig()
        assert th.capability_drop_warn == 0.05
        assert th.capability_drop_critical == 0.15
