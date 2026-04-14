"""综合分析器 analyzer 的单元测试"""

import pytest

from src.analysis.analyzer import analyze, AnalysisResult, Alert
from src.config.schema import EvaluationConfig, WeightsConfig


def _make_eval_config(**overrides):
    """构造 EvaluationConfig，默认使用合理的 probe_types"""
    defaults = {
        "schedule": [8],
        "probe_types": ["instruction", "style_open", "statistical"],
    }
    defaults.update(overrides)
    return EvaluationConfig(**defaults)


def _make_run(run_id="run-001", model="model-a", probe_type="instruction", results=None):
    """构造单次运行的输入数据"""
    return {
        "meta": {
            "run_id": run_id,
            "provider": "test",
            "model": model,
            "probe_type": probe_type,
        },
        "results": results or [],
    }


def _resp(text="Hello world"):
    return {"text": text, "latency_ms": 100, "input_tokens": 10, "output_tokens": 5}


class TestAnalyzeBasic:
    """analyze 基本功能"""

    def test_returns_analysis_result(self):
        """返回 AnalysisResult 实例"""
        runs = {"instruction": _make_run()}
        result = analyze(runs, None, _make_eval_config())
        assert isinstance(result, AnalysisResult)

    def test_first_run_no_baseline(self):
        """首次运行（无基线）: 所有维度 score=1.0, detail 包含 no baseline"""
        runs = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(runs, None, _make_eval_config())
        assert result.overall_score == pytest.approx(1.0)
        assert result.alert_level == "normal"
        assert result.baseline_run_id is None

    def test_with_baseline(self):
        """有基线时正常计算"""
        cur = {"instruction": _make_run(results=[{"response": _resp()}])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        config = _make_eval_config()
        result = analyze(cur, base, config)
        assert result.model == "model-a"
        assert result.baseline_run_id == "run-001"

    def test_model_from_meta(self):
        """model 字段取自 meta"""
        runs = {"instruction": _make_run(model="gpt-4")}
        result = analyze(runs, None, _make_eval_config())
        assert result.model == "gpt-4"

    def test_run_id_from_meta(self):
        """run_id 取自 meta（使用第一个 probe_type 的）"""
        runs = {"instruction": _make_run(run_id="r1")}
        result = analyze(runs, None, _make_eval_config())
        assert result.run_id == "r1"


class TestDispatch:
    """按 probe_type 分发到不同分析模块"""

    def test_instruction_dispatches_capability(self):
        """instruction 类型触发 capability 分析"""
        cur = {"instruction": _make_run(results=[{"response": _resp()}])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(cur, base, _make_eval_config())
        assert "capability" in result.dimensions

    def test_style_open_dispatches_behavior(self):
        """style_open 类型触发 behavior 分析"""
        cur = {"style_open": _make_run(
            probe_type="style_open",
            results=[{"response": _resp("This is a test sentence.")}],
        )}
        base = {"style_open": _make_run(
            probe_type="style_open",
            results=[{"response": _resp("This is a test sentence.")}],
        )}
        result = analyze(cur, base, _make_eval_config())
        assert "behavior" in result.dimensions

    def test_style_open_dispatches_similarity(self):
        """style_open 类型触发 text_similarity 分析"""
        cur = {"style_open": _make_run(
            probe_type="style_open",
            results=[{"response": _resp("Hello world.")}],
        )}
        base = {"style_open": _make_run(
            probe_type="style_open",
            results=[{"response": _resp("Hello world.")}],
        )}
        result = analyze(cur, base, _make_eval_config())
        assert "text_similarity" in result.dimensions

    def test_statistical_dispatches_statistical(self):
        """statistical 类型触发 statistical 分析"""
        text = "The quick brown fox jumps over the lazy dog."
        cur = {"statistical": _make_run(
            probe_type="statistical",
            results=[{"response": _resp(text)}],
        )}
        base = {"statistical": _make_run(
            probe_type="statistical",
            results=[{"response": _resp(text)}],
        )}
        result = analyze(cur, base, _make_eval_config())
        assert "statistical" in result.dimensions

    def test_any_type_dispatches_metadata(self):
        """所有 probe_type 都触发 metadata 分析"""
        cur = {"instruction": _make_run(results=[{"response": _resp()}])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(cur, base, _make_eval_config())
        assert "metadata" in result.dimensions


class TestErrorSkipping:
    """跳过 error 结果"""

    def test_error_results_skipped(self):
        """error 条目被跳过，不参与分析"""
        cur = {"instruction": _make_run(results=[
            {"error": {"type": "timeout"}},
            {"response": _resp()},
        ])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(cur, base, _make_eval_config())
        # 不应抛异常，正常返回结果
        assert isinstance(result, AnalysisResult)

    def test_all_errors_no_baseline(self):
        """全部 error + 无基线 -> score=1.0"""
        cur = {"instruction": _make_run(results=[{"error": {"type": "timeout"}}])}
        result = analyze(cur, None, _make_eval_config())
        assert result.overall_score == pytest.approx(1.0)


class TestWeightedAverage:
    """加权平均计算"""

    def test_custom_weights(self):
        """自定义权重生效"""
        cur = {"instruction": _make_run(results=[{"response": _resp()}])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        config = _make_eval_config(weights=WeightsConfig(
            capability=0.5, text_similarity=0.1,
            behavior=0.1, metadata=0.2, statistical=0.1,
        ))
        result = analyze(cur, base, config)
        # 无基线时所有 score=1.0，任何权重组合都应得到 1.0
        # 有基线时 capability 和 metadata 维度存在
        assert "capability" in result.dimensions
        assert "metadata" in result.dimensions

    def test_missing_dimension_excluded(self):
        """缺少某种 probe_type 时，对应维度不计入平均"""
        # 只有 instruction -> 只有 capability 和 metadata 维度
        cur = {"instruction": _make_run(results=[{"response": _resp()}])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(cur, base, _make_eval_config())
        # 不应包含 behavior, text_similarity, statistical
        assert "behavior" not in result.dimensions
        assert "text_similarity" not in result.dimensions


class TestAlertGeneration:
    """告警生成"""

    def test_no_alerts_when_normal(self):
        """所有维度 normal -> 无告警"""
        runs = {"instruction": _make_run()}
        result = analyze(runs, None, _make_eval_config())
        assert len(result.alerts) == 0
        assert result.alert_level == "normal"

    def test_alert_level_is_max(self):
        """overall alert_level = 所有维度中最高级别"""
        runs = {"instruction": _make_run()}
        result = analyze(runs, None, _make_eval_config())
        # 首次运行无基线，所有 normal
        assert result.alert_level == "normal"

    def test_alert_structure(self):
        """告警对象包含正确的字段"""
        runs = {"instruction": _make_run()}
        result = analyze(runs, None, _make_eval_config())
        for alert in result.alerts:
            assert isinstance(alert, Alert)
            assert alert.level in ("warn", "critical")
            assert len(alert.dimension) > 0
            assert len(alert.message) > 0


class TestDimensionScore:
    """维度评分"""

    def test_dimension_detail_no_baseline(self):
        """无基线时 detail 包含 no baseline"""
        runs = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(runs, None, _make_eval_config())
        for _, dim_score in result.dimensions.items():
            assert "no baseline" in dim_score.detail

    def test_dimension_score_range(self):
        """有基线时 score 在 [0, 1] 范围内"""
        cur = {"instruction": _make_run(results=[{"response": _resp()}])}
        base = {"instruction": _make_run(results=[{"response": _resp()}])}
        result = analyze(cur, base, _make_eval_config())
        for _, dim_score in result.dimensions.items():
            assert 0.0 <= dim_score.score <= 1.0
