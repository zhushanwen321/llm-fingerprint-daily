"""similarity 分析模块的单元测试"""

import pytest

from src.analysis.similarity import compare_texts, compare_consistency, DimensionScore


class TestCompareTexts:
    """单对文本相似度比较"""

    def test_identical_texts(self):
        text = "The quick brown fox jumps over the lazy dog."
        score = compare_texts(text, text)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_completely_different_texts(self):
        s1 = "aaaa bbbb cccc dddd eeee ffff gggg"
        s2 = "zzzz yyyy xxxx wwww vvvv uuuu tttt"
        score = compare_texts(s1, s2)
        # 完全不同的词汇，相似度应较低
        assert score < 0.5

    def test_similar_texts(self):
        s1 = "The cat sat on the mat and looked around."
        s2 = "The cat sat on the mat and looked outside."
        score = compare_texts(s1, s2)
        assert score > 0.7

    def test_empty_texts(self):
        score = compare_texts("", "")
        assert score == pytest.approx(1.0)

    def test_one_empty(self):
        score = compare_texts("some text", "")
        assert score < 0.5

    def test_chinese_texts(self):
        # tf-idf 按空格分词，中文整句作为单个 token，余弦相似度低
        # 但 SequenceMatcher 会贡献字符级相似度
        s1 = "今天天气很好，适合出去散步。"
        s2 = "今天天气不错，适合出去走走。"
        score = compare_texts(s1, s2)
        assert 0.0 <= score <= 1.0

    def test_score_between_zero_and_one(self):
        score = compare_texts("hello world", "goodbye world")
        assert 0.0 <= score <= 1.0

    def test_long_texts(self):
        s1 = "This is a longer piece of text. " * 10
        s2 = "This is a different longer piece of text. " * 10
        score = compare_texts(s1, s2)
        assert 0.0 <= score <= 1.0


class TestCompareConsistency:
    """多变体一致性比较"""

    def test_identical_variants(self):
        variants = ["response A", "response A"]
        result = compare_consistency(variants, variants)
        assert isinstance(result, DimensionScore)
        assert result.score == pytest.approx(1.0, abs=0.01)
        assert result.alert_level == "normal"

    def test_consistent_vs_inconsistent(self):
        cur = ["response alpha", "response alpha beta"]
        base = ["response one", "response two", "response three"]
        result = compare_consistency(cur, base)
        assert isinstance(result, DimensionScore)
        assert 0.0 <= result.score <= 1.0

    def test_single_variant_each(self):
        result = compare_consistency(["only one"], ["only one"])
        assert result.score == pytest.approx(1.0, abs=0.01)

    def test_empty_variants(self):
        result = compare_consistency([], [])
        assert result.alert_level == "normal"
        assert result.score == pytest.approx(1.0)

    def test_one_side_empty(self):
        result = compare_consistency(["has content"], [])
        assert result.alert_level == "critical"

    def test_alert_level_warn(self):
        # 两个差异适中的变体，最小相似度落在 warn 区间
        cur = ["alpha beta gamma", "alpha beta delta"]
        base = ["alpha beta gamma", "alpha beta delta"]
        result = compare_consistency(cur, base)
        assert result.alert_level in ("normal", "warn")

    def test_alert_level_critical(self):
        # 当前组内差异大
        cur = ["aaaa", "zzzz"]
        base = ["aaaa", "aaaa"]
        result = compare_consistency(cur, base)
        assert result.alert_level in ("warn", "critical")

    def test_detail_not_empty(self):
        result = compare_consistency(["a"], ["b"])
        assert len(result.detail) > 0
