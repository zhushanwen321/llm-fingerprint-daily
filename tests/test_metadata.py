"""metadata 分析模块的单元测试"""

import pytest

from src.analysis.metadata import compare


def _resp(text="Hello world", latency=1000, in_tok=50, out_tok=100):
    """构造 response 字段"""
    return {
        "text": text,
        "latency_ms": latency,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


class TestCompareBasic:
    """compare 基本功能"""

    def test_identical_results_normal(self):
        """完全相同的 current/baseline -> score=1.0, normal"""
        cur = [{"response": _resp()}]
        base = [{"response": _resp()}]
        result = compare(cur, base, {})
        assert result.score == pytest.approx(1.0)
        assert result.alert_level == "normal"

    def test_empty_inputs(self):
        """空列表 -> score=1.0, 无数据"""
        result = compare([], [], {})
        assert result.score == pytest.approx(1.0)
        assert result.alert_level == "normal"

    def test_one_side_empty(self):
        """只有一侧有数据 -> critical"""
        cur = [{"response": _resp()}]
        result = compare(cur, [], {})
        assert result.alert_level == "critical"
        assert result.score == pytest.approx(0.0)


class TestErrorSkipping:
    """跳过 error 结果"""

    def test_error_in_current_skipped(self):
        """current 中的 error 条目被跳过"""
        cur = [{"error": {"message": "timeout"}}, {"response": _resp()}]
        base = [{"response": _resp()}]
        result = compare(cur, base, {})
        # 一条有效配对，应该正常
        assert result.alert_level == "normal"

    def test_error_in_baseline_skipped(self):
        """baseline 中的 error 条目被跳过"""
        cur = [{"response": _resp()}]
        base = [{"error": {"message": "fail"}}, {"response": _resp()}]
        result = compare(cur, base, {})
        assert result.alert_level == "normal"

    def test_all_errors(self):
        """所有条目都是 error -> 无数据"""
        cur = [{"error": {"message": "fail"}}]
        base = [{"error": {"message": "fail"}}]
        result = compare(cur, base, {})
        assert result.score == pytest.approx(1.0)
        assert result.alert_level == "normal"


class TestMetrics:
    """各指标的变化检测"""

    def test_output_length_change_warn(self):
        """输出长度变化 15% -> warn"""
        cur = [{"response": _resp(text="A" * 115)}]
        base = [{"response": _resp(text="A" * 100)}]
        result = compare(cur, base, {"warn": 0.10, "critical": 0.30})
        assert result.alert_level == "warn"

    def test_output_length_change_critical(self):
        """输出长度变化 40% -> critical"""
        cur = [{"response": _resp(text="A" * 140)}]
        base = [{"response": _resp(text="A" * 100)}]
        result = compare(cur, base, {"warn": 0.10, "critical": 0.30})
        assert result.alert_level == "critical"

    def test_latency_change(self):
        """延迟大幅增加 -> score 下降"""
        cur = [{"response": _resp(latency=2000)}]
        base = [{"response": _resp(latency=1000)}]
        result = compare(cur, base, {"warn": 0.10, "critical": 0.30})
        assert result.score < 1.0

    def test_token_change(self):
        """output_tokens 增加 50% -> score 下降"""
        cur = [{"response": _resp(out_tok=150)}]
        base = [{"response": _resp(out_tok=100)}]
        result = compare(cur, base, {"warn": 0.10, "critical": 0.30})
        assert result.score < 1.0


class TestMedian:
    """使用中位数而非均值"""

    def test_median_robustness(self):
        """中位数不受极端值影响：一个异常值不应主导结果"""
        cur = [
            {"response": _resp(text="A" * 100)},
            {"response": _resp(text="A" * 100)},
            {"response": _resp(text="A" * 200)},  # 极端值
        ]
        base = [
            {"response": _resp(text="A" * 100)},
            {"response": _resp(text="A" * 100)},
            {"response": _resp(text="A" * 100)},
        ]
        result = compare(cur, base, {"warn": 0.10, "critical": 0.30})
        # 中位数变化率 = 0%，应为 normal
        assert result.alert_level == "normal"


class TestScoring:
    """评分逻辑"""

    def test_score_clamped_to_zero(self):
        """score 不会低于 0"""
        cur = [{"response": _resp(text="A" * 5000)}]
        base = [{"response": _resp(text="A" * 100)}]
        result = compare(cur, base, {})
        assert result.score >= 0.0

    def test_detail_contains_info(self):
        """detail 包含有用的诊断信息"""
        cur = [{"response": _resp(text="A" * 120)}]
        base = [{"response": _resp(text="A" * 100)}]
        result = compare(cur, base, {})
        assert len(result.detail) > 0


class TestThresholds:
    """自定义阈值"""

    def test_custom_thresholds(self):
        """自定义阈值生效"""
        cur = [{"response": _resp(text="A" * 104)}]
        base = [{"response": _resp(text="A" * 100)}]
        # 严格阈值: 2% warn, 5% critical; 4% 变化应触发 warn
        result = compare(cur, base, {"warn": 0.02, "critical": 0.05})
        assert result.alert_level == "warn"

    def test_default_thresholds(self):
        """不传阈值时使用默认值"""
        cur = [{"response": _resp(text="A" * 105)}]
        base = [{"response": _resp(text="A" * 100)}]
        result = compare(cur, base, {})
        # 默认阈值下 5% 变化应该是 normal
        assert result.alert_level == "normal"
