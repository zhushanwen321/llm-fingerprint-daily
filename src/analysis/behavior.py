"""behavior 分析 -- 文本行为特征提取与基线对比"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import ks_2samp


@dataclass
class BehaviorFeatures:
    """单条文本的行为特征"""
    word_freq: dict[str, float] = field(default_factory=dict)
    sentence_lengths: list[int] = field(default_factory=list)
    punctuation_ratios: dict[str, float] = field(default_factory=dict)
    has_list_markers: bool = False
    paragraph_count: int = 0
    analogy_count: int = 0
    hedge_count: int = 0
    first_sentence_pattern: str = "statement"


@dataclass
class DimensionScore:
    score: float
    detail: str
    alert_level: str = "normal"


# ---- 关键词集合 ----

_ANALOGY_KEYWORDS = re.compile(
    r"\blike\b|\bsuch as\b|就像|仿佛|好比|犹如", re.IGNORECASE,
)
_HEDGE_KEYWORDS = re.compile(
    r"\bmaybe\b|\bperhaps\b|\bpossibly\b|可能|或许|也许|大概", re.IGNORECASE,
)
_LIST_PATTERN = re.compile(r"^\s*[-*]\s|^\s*\d+\.\s", re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"[.?!。？！]+")
_PUNCT_TYPES: dict[str, re.Pattern] = {
    "comma": re.compile(r"[,\uff0c]"),
    "period": re.compile(r"[.。\u3002]"),
    "exclamation": re.compile(r"[!\uff01]"),
    "question": re.compile(r"[?\uff1f]"),
    "colon": re.compile(r"[:\uff1a]"),
    "semicolon": re.compile(r"[;\uff1b]"),
}


def extract_features(text: str) -> BehaviorFeatures:
    """从文本中提取行为特征"""
    if not text.strip():
        return BehaviorFeatures()

    return BehaviorFeatures(
        word_freq=_word_freq(text),
        sentence_lengths=_sentence_lengths(text),
        punctuation_ratios=_punctuation_ratios(text),
        has_list_markers=bool(_LIST_PATTERN.search(text)),
        paragraph_count=_paragraph_count(text),
        analogy_count=len(_ANALOGY_KEYWORDS.findall(text)),
        hedge_count=len(_HEDGE_KEYWORDS.findall(text)),
        first_sentence_pattern=_first_sentence_pattern(text),
    )


def compare(
    current: list[BehaviorFeatures],
    baseline: list[BehaviorFeatures],
) -> DimensionScore:
    """对比当前与基线的行为特征，返回评分"""
    if not current and not baseline:
        return DimensionScore(score=1.0, detail="no data", alert_level="normal")
    if not current or not baseline:
        return DimensionScore(score=0.0, detail="missing data", alert_level="critical")

    # 合并各特征列表
    cur_words = _merge_word_freqs(current)
    base_words = _merge_word_freqs(baseline)
    cur_sents = _merge_sentence_lengths(current)
    base_sents = _merge_sentence_lengths(baseline)
    cur_punct = _avg_punctuation(current)
    base_punct = _avg_punctuation(baseline)

    # JS 散度 -- 主要判别器
    js_score = _calc_js(cur_words, base_words)

    # KS 检验 -- 句子长度分布
    ks_score = _calc_ks(cur_sents, base_sents)

    # 标点欧氏距离
    punct_score = _calc_punct_euclidean(cur_punct, base_punct)

    # 其他特征绝对差异
    analogy_diff = abs(_avg(current, "analogy_count") - _avg(baseline, "analogy_count"))
    hedge_diff = abs(_avg(current, "hedge_count") - _avg(baseline, "hedge_count"))
    para_diff = abs(_avg(current, "paragraph_count") - _avg(baseline, "paragraph_count"))

    # 归一化其他差异到 0~1（限制上限为 1.0）
    other_score = max(0.0, 1.0 - (analogy_diff + hedge_diff + para_diff) * 0.1)

    # 加权平均：JS 和 KS 权重更高
    overall = (
        0.35 * js_score
        + 0.25 * ks_score
        + 0.15 * punct_score
        + 0.15 * other_score
        + 0.10 * 1.0  # list / pattern 的简单匹配
    )

    # 告警级别基于 JS 散度
    # js_score 是相似度 (1 - divergence)，阈值按 divergence: <0.1, 0.1-0.3, >0.3
    js_div = 1 - js_score
    if js_div < 0.1:
        level = "normal"
    elif js_div < 0.3:
        level = "warn"
    else:
        level = "critical"

    return DimensionScore(
        score=round(overall, 4),
        detail=(
            f"js={1 - js_score:.4f}, ks_p={_ks_pvalue(cur_sents, base_sents):.4f}, "
            f"punct_dist={1 - punct_score:.4f}, level={level}"
        ),
        alert_level=level,
    )


# ---- 内部函数 ----

def _word_freq(text: str, top_n: int = 50) -> dict[str, float]:
    words = text.lower().split()
    total = len(words)
    if total == 0:
        return {}
    counts = Counter(words)
    return {w: c / total for w, c in counts.most_common(top_n)}


def _sentence_lengths(text: str) -> list[int]:
    parts = _SENTENCE_SPLIT.split(text)
    return [len(p.strip()) for p in parts if p.strip()]


def _punctuation_ratios(text: str) -> dict[str, float]:
    total = len(text)
    if total == 0:
        return {}
    return {
        name: len(pat.findall(text)) / total
        for name, pat in _PUNCT_TYPES.items()
    }


def _paragraph_count(text: str) -> int:
    paras = text.split("\n\n")
    return len([p for p in paras if p.strip()])


def _first_sentence_pattern(text: str) -> str:
    # 找到第一个分隔符来确定首句类型
    m = _SENTENCE_SPLIT.search(text.strip())
    if not m:
        return "statement"
    delim = m.group()
    if "?" in delim or "？" in delim:
        return "question"
    if "!" in delim or "！" in delim:
        return "exclamation"
    return "statement"


def _merge_word_freqs(features_list: list[BehaviorFeatures]) -> dict[str, float]:
    merged: Counter = Counter()
    for f in features_list:
        merged.update({k: v for k, v in f.word_freq.items()})
    total = sum(merged.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in merged.items()}


def _merge_sentence_lengths(features_list: list[BehaviorFeatures]) -> list[int]:
    result: list[int] = []
    for f in features_list:
        result.extend(f.sentence_lengths)
    return result


def _avg_punctuation(features_list: list[BehaviorFeatures]) -> dict[str, float]:
    keys = list(_PUNCT_TYPES.keys())
    if not features_list:
        return {k: 0.0 for k in keys}
    merged = {k: 0.0 for k in keys}
    for f in features_list:
        for k in keys:
            merged[k] += f.punctuation_ratios.get(k, 0.0)
    n = len(features_list)
    return {k: v / n for k, v in merged.items()}


def _avg(features_list: list[BehaviorFeatures], attr: str) -> float:
    if not features_list:
        return 0.0
    return sum(getattr(f, attr) for f in features_list) / len(features_list)


def _calc_js(cur: dict, base: dict) -> float:
    """计算 JS 散度，返回相似度 (1 - divergence)"""
    all_keys = sorted(set(cur.keys()) | set(base.keys()))
    if not all_keys:
        return 1.0
    p = np.array([cur.get(k, 0.0) for k in all_keys], dtype=float)
    q = np.array([base.get(k, 0.0) for k in all_keys], dtype=float)
    p_sum, q_sum = p.sum(), q.sum()
    if p_sum == 0 or q_sum == 0:
        return 1.0
    p /= p_sum
    q /= q_sum
    div = jensenshannon(p, q, base=2)
    if np.isnan(div):
        return 1.0
    # 阈值: <0.1 normal, 0.1-0.3 warn, >0.3 critical
    # 转换为相似度: 1 - div，clamp 到 [0, 1]
    return max(0.0, min(1.0, 1.0 - div))


def _calc_ks(cur: list[int], base: list[int]) -> float:
    """KS 检验，返回相似度"""
    if len(cur) < 2 or len(base) < 2:
        return 1.0
    _, pvalue = ks_2samp(cur, base)
    return float(pvalue)  # p 值越大，分布越相似


def _ks_pvalue(cur: list[int], base: list[int]) -> float:
    if len(cur) < 2 or len(base) < 2:
        return 1.0
    _, pvalue = ks_2samp(cur, base)
    return float(pvalue)


def _calc_punct_euclidean(cur: dict, base: dict) -> float:
    """标点比例的欧氏距离，返回相似度"""
    keys = sorted(set(cur.keys()) | set(base.keys()))
    if not keys:
        return 1.0
    sq = sum((cur.get(k, 0.0) - base.get(k, 0.0)) ** 2 for k in keys)
    dist = sq ** 0.5
    # 归一化: 距离上限约 1.0，转换为相似度
    return max(0.0, 1.0 - dist)
