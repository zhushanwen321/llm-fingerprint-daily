"""statistical 分析 -- 基于多次采样的分布对比"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import ks_2samp


@dataclass
class DimensionScore:
    score: float
    detail: str
    alert_level: str = "normal"


# 用于从两个 Counter 合并 key 集合并对齐为概率分布
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+|[^\w\s]|[\u4e00-\u9fff]")
_JS_K = 3.0  # JS 散度惩罚系数
_KS_PENALTY = 0.15  # KS 检验显著时的额外惩罚
_TOP_K = 100  # 取频率最高的 token 数


def _tokenize(text: str) -> list[str]:
    """统一分词: 英文按空格/标点拆分，中文按单字符拆分"""
    return _TOKEN_PATTERN.findall(text)


def _counter_to_prob(counter: Counter, keys: list[str]) -> np.ndarray:
    """将 Counter 转为按 keys 对齐的概率向量"""
    total = sum(counter.values())
    if total == 0:
        return np.ones(len(keys)) / len(keys) if keys else np.array([])
    return np.array([counter.get(k, 0) / total for k in keys])


def _compute_js_divergence(freq1: Counter, freq2: Counter) -> float:
    """计算两个频率 Counter 之间的 JS 散度"""
    all_keys = list(set(freq1) | set(freq2))
    if not all_keys:
        return 0.0
    p = _counter_to_prob(freq1, all_keys)
    q = _counter_to_prob(freq2, all_keys)
    return float(jensenshannon(p, q, base=2))


def _compute_length_js(cur: list[str], base: list[str]) -> float:
    """基于 25-bin 直方图计算输出长度分布的 JS 散度"""
    cur_lens = np.array([len(s) for s in cur], dtype=float)
    base_lens = np.array([len(s) for s in base], dtype=float)
    all_vals = np.concatenate([cur_lens, base_lens])
    if all_vals.max() == all_vals.min():
        return 0.0
    bins = np.linspace(all_vals.min(), all_vals.max(), 26)
    p, _ = np.histogram(cur_lens, bins=bins)
    q, _ = np.histogram(base_lens, bins=bins)
    p = p.astype(float) / p.sum()
    q = q.astype(float) / q.sum()
    return float(jensenshannon(p, q, base=2))


def _token_freq_js(cur: list[str], base: list[str]) -> float:
    """计算两组样本 top-100 token 频率分布的 JS 散度"""
    cur_counter = Counter()
    base_counter = Counter()
    for s in cur:
        cur_counter.update(_tokenize(s))
    for s in base:
        base_counter.update(_tokenize(s))
    # 只取并集 top-K
    common = (cur_counter | base_counter).most_common(_TOP_K)
    top_keys = [k for k, _ in common]
    return _compute_js_divergence(
        Counter({k: cur_counter.get(k, 0) for k in top_keys}),
        Counter({k: base_counter.get(k, 0) for k in top_keys}),
    )


def statistical_test(current_samples: list[str], baseline_samples: list[str]) -> DimensionScore:
    """统计分布对比: 对比当前采样与基线采样的长度和 token 频率分布"""
    if not current_samples and not baseline_samples:
        return DimensionScore(score=1.0, detail="no data", alert_level="normal")
    if not current_samples or not baseline_samples:
        return DimensionScore(score=0.0, detail="missing samples", alert_level="critical")

    # 长度分布 JS 散度
    length_js = _compute_length_js(current_samples, baseline_samples)

    # KS 检验: 检查长度分布是否显著不同
    cur_lens = [len(s) for s in current_samples]
    base_lens = [len(s) for s in baseline_samples]
    _, ks_p = ks_2samp(cur_lens, base_lens)

    # Token 频率 JS 散度
    token_js = _token_freq_js(current_samples, baseline_samples)

    # 评分: 综合长度和 token 两个维度的 JS 散度
    avg_js = (length_js + token_js) / 2
    score = max(0.0, 1.0 - avg_js * _JS_K)

    # KS 检验显著 → 额外惩罚
    if ks_p < 0.05:
        score = max(0.0, score - _KS_PENALTY)

    # 告警级别
    if score >= 0.7:
        level = "normal"
    elif score >= 0.4:
        level = "warn"
    else:
        level = "critical"

    return DimensionScore(
        score=round(score, 4),
        detail=(
            f"length_js={length_js:.4f}, token_js={token_js:.4f}, "
            f"ks_p={ks_p:.4f}, level={level}"
        ),
        alert_level=level,
    )
