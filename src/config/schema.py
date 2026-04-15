"""配置数据模型 — 基于 pydantic BaseModel 定义 config.yaml 的结构"""

from __future__ import annotations

from pydantic import BaseModel, model_validator


class ProviderConfig(BaseModel):
    """LLM 服务提供者配置"""

    base_url: str
    api_key: str  # 支持 ${ENV_VAR} 格式，由 loader 负责解析
    default_headers: dict[str, str] = {}
    concurrency: int = 1
    rpm: int = 0  # 每分钟最大请求数，0 表示不限制
    request_interval: float = 0  # 两次请求间的最小间隔秒数，在 semaphore 内等待


class ModelEntry(BaseModel):
    """模型条目"""

    name: str
    provider: str
    display_name: str = ""


class TargetEntry(BaseModel):
    """评测目标"""

    provider: str = ""  # 可在 AppConfig validator 中从 models 列表自动推断
    model: str
    enabled: bool = True
    baseline_run_id: str | None = None


class ThresholdsConfig(BaseModel):
    """告警/告警阈值"""

    capability_drop_warn: float = 0.05
    capability_drop_critical: float = 0.15
    similarity_warn: float = 0.7
    similarity_critical: float = 0.5
    behavior_js_warn: float = 0.1
    behavior_js_critical: float = 0.3
    metadata_length_warn: float = 0.1
    metadata_length_critical: float = 0.3


class WeightsConfig(BaseModel):
    """各分析维度权重，总和必须为 1.0"""

    capability: float = 0.30
    text_similarity: float = 0.25
    behavior: float = 0.20
    metadata: float = 0.10
    statistical: float = 0.15

    @model_validator(mode="after")
    def _check_sum(self) -> WeightsConfig:
        total = (
            self.capability
            + self.text_similarity
            + self.behavior
            + self.metadata
            + self.statistical
        )
        # 允许浮点误差
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"权重总和必须为 1.0，当前为 {total}")
        return self


class EvaluationConfig(BaseModel):
    """评测调度与参数"""

    schedule: list[int]
    timezone: str = "Asia/Shanghai"
    probe_types: list[str] = []
    max_llm_concurrent: int = 5
    max_retries: int = 5
    retry_intervals: list[float] = [5, 10, 30, 60]
    timeout: int = 60
    statistical_samples: int = 20
    targets: list[TargetEntry] = []
    thresholds: ThresholdsConfig = ThresholdsConfig()
    weights: WeightsConfig = WeightsConfig()


class ReportConfig(BaseModel):
    """报告输出配置"""

    output_dir: str = "./reports"
    auto_open: bool = False


class AppConfig(BaseModel):
    """应用顶层配置"""

    providers: dict[str, ProviderConfig]
    models: list[ModelEntry] = []
    evaluation: EvaluationConfig
    report: ReportConfig = ReportConfig()

    @model_validator(mode="after")
    def _fill_target_providers(self) -> AppConfig:
        """从 models 列表自动推断 targets 中缺失的 provider"""
        model_provider_map = {m.name: m.provider for m in self.models}
        for t in self.evaluation.targets:
            if not t.provider:
                if t.model in model_provider_map:
                    t.provider = model_provider_map[t.model]
                else:
                    raise ValueError(
                        f"target '{t.model}' 缺少 provider 且 models 列表中未定义"
                    )
        return self

    @staticmethod
    def get_retry_interval(intervals: list[float], attempt: int) -> float:
        """获取重试间隔，超出数组长度时取最后一个值"""
        if not intervals:
            return 5.0
        idx = min(attempt - 1, len(intervals) - 1)
        return intervals[idx]

    def validate_concurrency(self, raise_on_error: bool = False) -> bool:
        """校验所有 provider 并发数总和不超过 max_llm_concurrent"""
        total = sum(p.concurrency for p in self.providers.values())
        ok = total <= self.evaluation.max_llm_concurrent
        if not ok and raise_on_error:
            raise ValueError(
                f"provider 并发数总和 {total} 超过 max_llm_concurrent {self.evaluation.max_llm_concurrent}"
            )
        return ok
