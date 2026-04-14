"""capability 分析 -- 指令约束满足率 + 编码覆盖率 + 基线对比"""

from __future__ import annotations

from dataclasses import dataclass

from src.probe.schema import SimpleProbe, CodingProbe
from src.analysis._constraint import check as _check_constraint


@dataclass
class DimensionScore:
    score: float          # 0.0 ~ 1.0
    detail: str
    alert_level: str = "normal"  # normal | warn | critical


def check_instruction(
    probe_results: list[dict],
    probe_defs: list[SimpleProbe],
) -> float:
    """指令约束满足率，取所有探针的平均值"""
    if not probe_results:
        return 0.0

    lookup = {p.id: p for p in probe_defs}
    total_satisfied = 0
    total_constraints = 0

    for r in probe_results:
        if "error" in r or "response" not in r:
            continue
        probe = lookup.get(r["probe_id"])
        if not probe or not probe.constraints:
            continue
        text = r["response"].get("text", "")
        for c in probe.constraints:
            total_constraints += 1
            if _check_constraint(text, c):
                total_satisfied += 1

    if total_constraints == 0:
        return 0.0
    return total_satisfied / total_constraints


def check_coding(
    probe_results: list[dict],
    probe_defs: list[CodingProbe],
) -> float:
    """编码覆盖率，基于 must/should/forbidden/check_points 加权计算"""
    if not probe_results:
        return 0.0

    lookup = {p.id: p for p in probe_defs}
    total_score = 0.0
    total_max = 0

    for r in probe_results:
        if "error" in r or "response" not in r:
            continue
        probe = lookup.get(r["probe_id"])
        if not probe:
            continue
        text = r["response"].get("text", "")
        s = probe.scoring

        score = 0.0
        max_possible = 0

        for kw in s.must_contain:
            max_possible += 1
            if kw in text:
                score += 1
        for kw in s.should_contain:
            max_possible += 0.5
            if kw in text:
                score += 0.5
        for kw in s.forbidden_patterns:
            if kw in text:
                score -= 0.5
        for kw in s.check_points:
            max_possible += 1
            if kw in text:
                score += 1

        total_max += max_possible
        total_score += score

    if total_max == 0:
        return 0.0
    return max(0.0, min(1.0, total_score / total_max))


def compare(
    current_rate: float,
    baseline_rate: float,
    thresholds: dict,
) -> DimensionScore:
    """当前指标 vs 基线，返回评分与告警级别"""
    warn_t = thresholds.get("warn", 0.1)
    crit_t = thresholds.get("critical", 0.2)
    scaling = 5.0  # drop=0.2 -> score=0.0

    drop = baseline_rate - current_rate
    score = max(0.0, 1.0 - drop * scaling)

    if drop >= crit_t:
        level = "critical"
    elif drop >= warn_t:
        level = "warn"
    else:
        level = "normal"

    return DimensionScore(
        score=round(score, 4),
        detail=(
            f"current={current_rate:.4f}, baseline={baseline_rate:.4f}, "
            f"drop={drop:.4f}, level={level}"
        ),
        alert_level=level,
    )
