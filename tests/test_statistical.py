"""statistical 分析模块的单元测试"""

import re
from collections import Counter

import numpy as np
import pytest

from src.analysis.statistical import DimensionScore, statistical_test


class TestTokenize:
    """分词函数测试"""

    def test_english_whitespace(self):
        from src.analysis.statistical import _tokenize
        result = _tokenize("hello world foo")
        assert "hello" in result
        assert "world" in result

    def test_chinese_characters(self):
        from src.analysis.statistical import _tokenize
        result = _tokenize("你好世界")
        assert "你" in result
        assert "好" in result

    def test_mixed(self):
        from src.analysis.statistical import _tokenize
        result = _tokenize("hello你好world世界")
        assert "hello" in result
        assert "你" in result


class TestComputeJSDivergence:
    """JS 散度计算测试"""

    def test_identical_distributions(self):
        from src.analysis.statistical import _compute_js_divergence
        freq1 = Counter({"a": 10, "b": 5, "c": 3})
        freq2 = Counter({"a": 10, "b": 5, "c": 3})
        js = _compute_js_divergence(freq1, freq2)
        assert js == pytest.approx(0.0, abs=0.01)

    def test_completely_different(self):
        from src.analysis.statistical import _compute_js_divergence
        freq1 = Counter({"a": 100, "b": 0, "c": 0})
        freq2 = Counter({"a": 0, "b": 100, "c": 0})
        js = _compute_js_divergence(freq1, freq2)
        assert js > 0.0

    def test_empty_counters(self):
        from src.analysis.statistical import _compute_js_divergence
        js = _compute_js_divergence(Counter(), Counter())
        assert js == 0.0


class TestComputeLengthJS:
    """输出长度分布 JS 散度测试"""

    def test_same_lengths(self):
        from src.analysis.statistical import _compute_length_js
        samples = ["abc", "def", "ghi"]
        js = _compute_length_js(samples, samples)
        assert js == pytest.approx(0.0, abs=0.01)


class TestStatisticalTest:
    """主测试函数"""

    def _gen_samples(self, rng, base_len, n=20, variance=50):
        """生成带随机长度波动的样本"""
        return [
            "word " * (base_len + rng.integers(-variance, variance + 1))
            for _ in range(n)
        ]

    def test_identical_distributions(self):
        """相同分布应得高分"""
        rng = np.random.default_rng(42)
        samples = self._gen_samples(rng, 50)
        result = statistical_test(samples, samples)
        assert isinstance(result, DimensionScore)
        assert result.score > 0.8
        assert result.alert_level == "normal"

    def test_different_distributions(self):
        """差异显著的分布应得低分"""
        rng = np.random.default_rng(42)
        cur = self._gen_samples(rng, 20, variance=5)
        base = self._gen_samples(rng, 200, variance=10)
        result = statistical_test(cur, base)
        assert isinstance(result, DimensionScore)
        assert result.score < 0.8
        assert result.alert_level in ("warn", "critical")

    def test_empty_inputs(self):
        """空输入应返回无数据"""
        result = statistical_test([], [])
        assert result.alert_level == "normal"
        assert result.score == pytest.approx(1.0)

    def test_one_side_empty(self):
        result = statistical_test(["hello"], [])
        assert result.alert_level == "critical"

    def test_score_in_range(self):
        rng = np.random.default_rng(123)
        cur = self._gen_samples(rng, 50)
        base = self._gen_samples(rng, 60)
        result = statistical_test(cur, base)
        assert 0.0 <= result.score <= 1.0

    def test_detail_not_empty(self):
        rng = np.random.default_rng(42)
        samples = self._gen_samples(rng, 50)
        result = statistical_test(samples, samples)
        assert len(result.detail) > 0

    def test_chinese_samples(self):
        """中文样本应正常工作"""
        cur = ["这是一段中文文本"] * 10 + ["这是另一段"] * 10
        base = ["这是一段中文文本"] * 10 + ["这是另一段"] * 10
        result = statistical_test(cur, base)
        assert result.score > 0.8
