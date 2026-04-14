"""综合分析器 -- 分发到各子模块、聚合评分、生成告警"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config.schema import EvaluationConfig


# ---- 数据结构 ----

@dataclass
class DimensionScore:
    """维度评分"""
    score: float
    detail: str
    alert_level: str = "normal"


@dataclass
class Alert:
    """告警"""
    dimension: str
    level: str  # warn | critical
    message: str


@dataclass
class AnalysisResult:
    """综合分析结果"""
    model: str
    run_id: str
    baseline_run_id: str | None
    overall_score: float
    alert_level: str  # normal | warn | critical
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)


# ---- 维度名常量 ----

_DIM_CAPABILITY = "capability"
_DIM_BEHAVIOR = "behavior"
_DIM_TEXT_SIM = "text_similarity"
_DIM_METADATA = "metadata"
_DIM_STATISTICAL = "statistical"

# probe_type -> 需要触发的维度列表
_PROBE_DIMENSIONS: dict[str, list[str]] = {
    "instruction": [_DIM_CAPABILITY],
    "coding_frontend": [_DIM_CAPABILITY],
    "coding_backend": [_DIM_CAPABILITY],
    "style_open": [_DIM_BEHAVIOR, _DIM_TEXT_SIM],
    "consistency": [_DIM_TEXT_SIM],
    "statistical": [_DIM_STATISTICAL],
}
# metadata 维度对所有 probe_type 都生效


def analyze(
    current_runs: dict[str, dict],
    baseline_runs: dict[str, dict] | None,
    config: EvaluationConfig,
) -> AnalysisResult:
    """综合分析入口"""
    # 从第一个 run 提取 meta
    first_run = next(iter(current_runs.values()), {})
    meta = first_run.get("meta", {})
    model = meta.get("model", "unknown")
    run_id = meta.get("run_id", "unknown")
    base_run_id = None
    if baseline_runs:
        first_base = next(iter(baseline_runs.values()), {})
        base_run_id = first_base.get("meta", {}).get("run_id")

    no_baseline = baseline_runs is None
    dims: dict[str, DimensionScore] = {}
    weights = config.weights

    for probe_type, run_data in current_runs.items():
        cur_results = run_data.get("results", [])
        base_results = []
        if baseline_runs and probe_type in baseline_runs:
            base_results = baseline_runs[probe_type].get("results", [])

        # 确定该 probe_type 触发的维度
        dim_names = list(_PROBE_DIMENSIONS.get(probe_type, []))
        # metadata 对所有 probe_type 生效
        dim_names.append(_DIM_METADATA)

        for dim in dim_names:
            if dim in dims:
                continue
            dims[dim] = _compute_dimension(
                dim, cur_results, base_results, no_baseline, config,
            )

    # 加权平均（仅计算实际存在的维度）
    overall = _weighted_average(dims, weights)

    # 生成告警
    alerts = _generate_alerts(dims)
    alert_level = _max_alert_level(dims)

    return AnalysisResult(
        model=model, run_id=run_id, baseline_run_id=base_run_id,
        overall_score=round(overall, 4), alert_level=alert_level,
        dimensions=dims, alerts=alerts,
    )


# ---- 内部函数 ----

def _valid_results(results: list[dict]) -> list[dict]:
    """过滤掉 error 条目"""
    return [r for r in results if "error" not in r and "response" in r]


def _extract_texts(results: list[dict]) -> list[str]:
    """从有效结果中提取文本列表"""
    return [r["response"].get("text", "") for r in _valid_results(results)]


_NO_BASELINE = DimensionScore(score=1.0, detail="no baseline", alert_level="normal")


def _compute_dimension(
    dim: str,
    cur_results: list[dict],
    base_results: list[dict],
    no_baseline: bool,
    config: EvaluationConfig,
) -> DimensionScore:
    """按维度名分发计算"""
    if no_baseline:
        return _NO_BASELINE

    if dim == _DIM_CAPABILITY:
        return _dim_capability(cur_results, base_results, config)
    if dim == _DIM_BEHAVIOR:
        return _dim_behavior(cur_results, base_results)
    if dim == _DIM_TEXT_SIM:
        return _dim_text_similarity(cur_results, base_results, config)
    if dim == _DIM_METADATA:
        return _dim_metadata(cur_results, base_results, config)
    if dim == _DIM_STATISTICAL:
        return _dim_statistical(cur_results, base_results)
    return _NO_BASELINE


def _dim_capability(
    cur_results: list[dict], base_results: list[dict], config: EvaluationConfig,
) -> DimensionScore:
    """capability 维度: 用 metadata 变化率近似（需要 probe_defs 才能精确计算）"""
    # 无 probe_defs 时，用 metadata 的变化率作为 capability 的代理指标
    th = config.thresholds
    thresholds = {"warn": th.capability_drop_warn, "critical": th.capability_drop_critical}
    return _dim_metadata(cur_results, base_results, config, thresholds)


def _dim_behavior(
    cur_results: list[dict], base_results: list[dict],
) -> DimensionScore:
    """behavior 维度: 提取特征并对比"""
    from src.analysis.behavior import extract_features, compare as behavior_compare

    cur_texts = _extract_texts(cur_results)
    base_texts = _extract_texts(base_results)
    if not cur_texts and not base_texts:
        return DimensionScore(score=1.0, detail="no data", alert_level="normal")

    cur_features = [extract_features(t) for t in cur_texts]
    base_features = [extract_features(t) for t in base_texts]
    return behavior_compare(cur_features, base_features)


def _dim_text_similarity(
    cur_results: list[dict], base_results: list[dict], config: EvaluationConfig,
) -> DimensionScore:
    """text_similarity 维度: 对比文本相似度"""
    from src.analysis.similarity import compare_texts

    cur_texts = _extract_texts(cur_results)
    base_texts = _extract_texts(base_results)
    if not cur_texts or not base_texts:
        return DimensionScore(score=1.0, detail="no data", alert_level="normal")

    # 取等长部分逐对比较，取平均
    pairs = min(len(cur_texts), len(base_texts))
    scores = [compare_texts(cur_texts[i], base_texts[i]) for i in range(pairs)]
    avg_score = sum(scores) / len(scores) if scores else 1.0

    th = config.thresholds
    if avg_score >= th.similarity_warn:
        level = "normal"
    elif avg_score >= th.similarity_critical:
        level = "warn"
    else:
        level = "critical"

    return DimensionScore(
        score=round(avg_score, 4),
        detail=f"avg_similarity={avg_score:.4f}, pairs={pairs}, level={level}",
        alert_level=level,
    )


def _dim_metadata(
    cur_results: list[dict], base_results: list[dict],
    config: EvaluationConfig, thresholds: dict | None = None,
) -> DimensionScore:
    """metadata 维度: 长度/延迟/token 变化率"""
    from src.analysis.metadata import compare as metadata_compare

    if thresholds is None:
        th = config.thresholds
        thresholds = {"warn": th.metadata_length_warn, "critical": th.metadata_length_critical}
    return metadata_compare(cur_results, base_results, thresholds)


def _dim_statistical(
    cur_results: list[dict], base_results: list[dict],
) -> DimensionScore:
    """statistical 维度: 分布对比"""
    from src.analysis.statistical import statistical_test

    cur_texts = _extract_texts(cur_results)
    base_texts = _extract_texts(base_results)
    return statistical_test(cur_texts, base_texts)


def _weighted_average(
    dims: dict[str, DimensionScore], weights,
) -> float:
    """对存在的维度做加权平均"""
    if not dims:
        return 1.0
    weight_map = {
        _DIM_CAPABILITY: weights.capability,
        _DIM_TEXT_SIM: weights.text_similarity,
        _DIM_BEHAVIOR: weights.behavior,
        _DIM_METADATA: weights.metadata,
        _DIM_STATISTICAL: weights.statistical,
    }
    total_w = 0.0
    total_score = 0.0
    for dim_name, dim_score in dims.items():
        w = weight_map.get(dim_name, 0.0)
        total_w += w
        total_score += dim_score.score * w
    return total_score / total_w if total_w > 0 else 1.0


def _generate_alerts(dims: dict[str, DimensionScore]) -> list[Alert]:
    """从维度评分中生成告警列表"""
    alerts = []
    for dim_name, dim_score in dims.items():
        if dim_score.alert_level == "warn":
            alerts.append(Alert(
                dimension=dim_name, level="warn",
                message=f"{dim_name} 指标偏离基线: {dim_score.detail}",
            ))
        elif dim_score.alert_level == "critical":
            alerts.append(Alert(
                dimension=dim_name, level="critical",
                message=f"{dim_name} 指标严重偏离基线: {dim_score.detail}",
            ))
    return alerts


def _max_alert_level(dims: dict[str, DimensionScore]) -> str:
    """取所有维度中最高告警级别"""
    levels = {d.alert_level for d in dims.values()}
    if "critical" in levels:
        return "critical"
    if "warn" in levels:
        return "warn"
    return "normal"
