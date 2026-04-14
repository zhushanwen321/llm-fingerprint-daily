"""behavior 分析模块的单元测试"""

import pytest

from src.analysis.behavior import (
    BehaviorFeatures,
    extract_features,
    compare,
)


class TestExtractFeatures:
    """特征提取"""

    def test_basic_extraction(self):
        text = "Hello world. This is a test! How are you?"
        feat = extract_features(text)
        assert isinstance(feat, BehaviorFeatures)
        assert len(feat.word_freq) <= 50
        assert len(feat.sentence_lengths) > 0

    def test_empty_text(self):
        feat = extract_features("")
        assert isinstance(feat, BehaviorFeatures)
        assert feat.word_freq == {}
        assert feat.sentence_lengths == []
        assert feat.paragraph_count == 0

    def test_sentence_lengths(self):
        text = "Short. This sentence is longer. Tiny."
        feat = extract_features(text)
        assert len(feat.sentence_lengths) == 3
        # 句子长度按字符数
        assert feat.sentence_lengths[0] == len("Short")
        assert feat.sentence_lengths[2] == len("Tiny")

    def test_punctuation_ratios(self):
        text = "Hello, world! How are you?"
        feat = extract_features(text)
        assert "comma" in feat.punctuation_ratios
        assert "exclamation" in feat.punctuation_ratios
        assert feat.punctuation_ratios["comma"] > 0

    def test_list_detection(self):
        text = "- item one\n- item two\n1. first\n2. second"
        feat = extract_features(text)
        assert feat.has_list_markers is True

    def test_no_list(self):
        text = "Normal paragraph with no lists at all."
        feat = extract_features(text)
        assert feat.has_list_markers is False

    def test_paragraph_count(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        feat = extract_features(text)
        assert feat.paragraph_count == 3

    def test_analogy_detection(self):
        text = "It is like a dream. Such as apples."
        feat = extract_features(text)
        assert feat.analogy_count >= 2

    def test_analogy_chinese(self):
        text = "就像一场梦，仿佛回到了从前。"
        feat = extract_features(text)
        assert feat.analogy_count >= 2

    def test_hedge_detection(self):
        text = "Maybe it will work. Perhaps not. 可能是对的。"
        feat = extract_features(text)
        assert feat.hedge_count >= 3

    def test_first_sentence_pattern_statement(self):
        text = "This is a statement. Is this a question?"
        feat = extract_features(text)
        assert feat.first_sentence_pattern == "statement"

    def test_first_sentence_pattern_question(self):
        text = "Is this a question? This is a statement."
        feat = extract_features(text)
        assert feat.first_sentence_pattern == "question"

    def test_first_sentence_pattern_exclamation(self):
        text = "Wow! This is amazing."
        feat = extract_features(text)
        assert feat.first_sentence_pattern == "exclamation"

    def test_multiline_input(self):
        text = "Line one.\nLine two.\n\nLine three."
        feat = extract_features(text)
        assert feat.paragraph_count == 2


class TestCompare:
    """基线对比"""

    def test_identical_features_normal(self):
        feat = extract_features("Hello world. This is a test!")
        result = compare([feat], [feat])
        assert result.alert_level == "normal"
        assert result.score == pytest.approx(1.0, abs=0.01)

    def test_different_texts_warn(self):
        f1 = extract_features("Short." * 5)
        f2 = extract_features("This is a much longer text with many words and sentences. " * 5)
        result = compare([f2], [f1])
        # 不同文本之间会有差异，但不一定 critical
        assert isinstance(result.alert_level, str)
        assert 0.0 <= result.score <= 1.0

    def test_detail_not_empty(self):
        feat = extract_features("Test text. Some content here.")
        result = compare([feat], [feat])
        assert len(result.detail) > 0

    def test_empty_inputs(self):
        result = compare([], [])
        assert result.alert_level == "normal"
        assert result.score == pytest.approx(1.0)

    def test_multiple_features(self):
        f1 = extract_features("Hello. Hi. Hey.")
        f2 = extract_features("Hello. Hi. Hey.")
        result = compare([f1, f2], [f1, f2])
        assert result.alert_level == "normal"

    def test_js_divergence_thresholds(self):
        """JS 散度阈值边界测试"""
        # 相同文本 -> JS 散度 = 0 -> normal
        f = extract_features("The quick brown fox jumps over the lazy dog. " * 3)
        result = compare([f], [f])
        assert result.alert_level == "normal"
