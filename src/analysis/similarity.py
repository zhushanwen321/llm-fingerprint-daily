"""similarity 分析 -- 文本相似度比较与一致性评估"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class DimensionScore:
    score: float
    detail: str
    alert_level: str = "normal"


def compare_texts(current: str, baseline: str) -> float:
    """混合相似度: 0.7 * tf-idf 余弦 + 0.3 * SequenceMatcher"""
    if not current.strip() and not baseline.strip():
        return 1.0
    if not current.strip() or not baseline.strip():
        return 0.0

    # tf-idf 余弦相似度
    try:
        vec = TfidfVectorizer()
        tfidf_matrix = vec.fit_transform([current, baseline])
        # 手动计算余弦相似度，避免稀疏矩阵除零
        v1 = tfidf_matrix[0].toarray().flatten()
        v2 = tfidf_matrix[1].toarray().flatten()
        dot = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            cosine = 0.0
        else:
            cosine = float(dot / (norm1 * norm2))
    except ValueError:
        cosine = 0.0

    # SequenceMatcher 字符级相似度
    seq_ratio = SequenceMatcher(None, current, baseline).ratio()

    return round(0.7 * cosine + 0.3 * seq_ratio, 4)


def _min_pairwise_similarity(variants: list[str]) -> float:
    """计算变体列表中的最小成对相似度"""
    if len(variants) <= 1:
        return 1.0
    min_sim = 1.0
    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            sim = compare_texts(variants[i], variants[j])
            min_sim = min(min_sim, sim)
    return min_sim


def compare_consistency(
    current_variants: list[str],
    baseline_variants: list[str],
    warn_threshold: float = 0.7,
    critical_threshold: float = 0.5,
) -> DimensionScore:
    """对比两组变体的一致性: 比较各自最小成对相似度"""
    if not current_variants and not baseline_variants:
        return DimensionScore(score=1.0, detail="no data", alert_level="normal")
    if not current_variants or not baseline_variants:
        return DimensionScore(score=0.0, detail="missing variants", alert_level="critical")

    cur_min = _min_pairwise_similarity(current_variants)
    base_min = _min_pairwise_similarity(baseline_variants)

    # 评分: 当前最小相似度作为主指标
    score = cur_min

    if score >= warn_threshold:
        level = "normal"
    elif score >= critical_threshold:
        level = "warn"
    else:
        level = "critical"

    return DimensionScore(
        score=round(score, 4),
        detail=(
            f"cur_min={cur_min:.4f}, base_min={base_min:.4f}, level={level}"
        ),
        alert_level=level,
    )
