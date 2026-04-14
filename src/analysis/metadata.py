"""metadata 分析 -- 输出长度/延迟/token 变化率对比"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass
class DimensionScore:
    score: float
    detail: str
    alert_level: str = "normal"


# 默认阈值
_DEFAULT_THRESHOLDS = {"warn": 0.10, "critical": 0.30}

# 评分衰减因子: 变化率 1.0 -> score=0.0
_SCALING_FACTOR = 1.0


def compare(
    current_results: list[dict],
    baseline_results: list[dict],
    thresholds: dict | None = None,
) -> DimensionScore:
    """对比当前与基线的元数据指标，返回评分"""
    th = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}

    cur_valid = _extract_metadata(current_results)
    base_valid = _extract_metadata(baseline_results)

    # 双方都无有效数据
    if not cur_valid and not base_valid:
        return DimensionScore(score=1.0, detail="no data", alert_level="normal")
    # 单侧缺失
    if not cur_valid or not base_valid:
        return DimensionScore(score=0.0, detail="missing data", alert_level="critical")

    # 计算各指标中位数变化率
    metrics = ["output_length", "latency_ms", "input_tokens", "output_tokens"]
    change_rates = []
    details = []

    for m in metrics:
        cur_vals = [r[m] for r in cur_valid]
        base_vals = [r[m] for r in base_valid]
        cur_med = median(cur_vals)
        base_med = median(base_vals)
        if base_med == 0:
            continue
        rate = (cur_med - base_med) / base_med
        change_rates.append(abs(rate))
        details.append(f"{m}={rate:+.4f}")

    if not change_rates:
        return DimensionScore(score=1.0, detail="no valid metrics", alert_level="normal")

    # 各指标变化率取均值用于评分，取最大值用于告警
    avg_change = sum(change_rates) / len(change_rates)
    max_change = max(change_rates)
    score = max(0.0, 1.0 - avg_change * _SCALING_FACTOR)

    # 告警级别基于最大变化率，任一指标超标即告警
    if max_change >= th["critical"]:
        level = "critical"
    elif max_change >= th["warn"]:
        level = "warn"
    else:
        level = "normal"

    return DimensionScore(
        score=round(score, 4),
        detail=f"max_change={max_change:.4f}, avg_change={avg_change:.4f}, [{', '.join(details)}], level={level}",
        alert_level=level,
    )


def _extract_metadata(results: list[dict]) -> list[dict]:
    """从探针结果中提取元数据，跳过 error 条目"""
    extracted = []
    for r in results:
        if "error" in r or "response" not in r:
            continue
        resp = r["response"]
        extracted.append({
            "output_length": len(resp.get("text", "")),
            "latency_ms": resp.get("latency_ms", 0),
            "input_tokens": resp.get("input_tokens", 0),
            "output_tokens": resp.get("output_tokens", 0),
        })
    return extracted
