"""Report Generator 单元测试 -- 覆盖 HTML 报告生成的关键内容"""

import json
from pathlib import Path

import pytest

from src.report.generator import ReportGenerator


# ---- 测试数据 ----

def _make_analysis(
    model: str = "test-model",
    run_id: str = "20260414100003",
    overall_score: float = 0.87,
    alert_level: str = "normal",
) -> dict:
    return {
        "model": model,
        "run_id": run_id,
        "baseline_run_id": "20260414000003",
        "overall_score": overall_score,
        "alert_level": alert_level,
        "dimensions": {
            "capability": {"score": 0.92, "detail": "cap ok", "alert_level": "normal"},
            "text_similarity": {"score": 0.78, "detail": "sim ok", "alert_level": "normal"},
            "behavior": {"score": 0.95, "detail": "beh ok", "alert_level": "normal"},
            "metadata": {"score": 0.80, "detail": "meta ok", "alert_level": "normal"},
            "statistical": {"score": 0.88, "detail": "stat ok", "alert_level": "normal"},
        },
        "alerts": [],
    }


def _make_analysis_with_alerts() -> dict:
    d = _make_analysis(alert_level="warn")
    d["alerts"] = [
        {"dimension": "text_similarity", "level": "warn",
         "message": "text_similarity 指标偏离基线"},
    ]
    d["dimensions"]["text_similarity"]["alert_level"] = "warn"
    d["dimensions"]["text_similarity"]["score"] = 0.55
    d["overall_score"] = 0.72
    return d


def _setup_model_dir(tmp_path: Path, analyses: list[dict]) -> Path:
    """在 tmp_path/data/{model}/analysis/ 下创建分析结果文件"""
    model_dir = tmp_path / "data" / analyses[0]["model"] / "analysis"
    model_dir.mkdir(parents=True)
    for a in analyses:
        (model_dir / f"{a['run_id']}.json").write_text(
            json.dumps(a, ensure_ascii=False), encoding="utf-8"
        )
    return tmp_path / "data" / analyses[0]["model"]


class TestSingleModelReport:
    """单模型报告生成"""

    def test_report_contains_chartjs(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        html = gen.generate_model_report(model_dir)
        assert "chart.js" in html

    def test_report_contains_overall_score(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        html = gen.generate_model_report(model_dir)
        assert "87.00" in html

    def test_report_contains_model_name(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        html = gen.generate_model_report(model_dir)
        assert "test-model" in html

    def test_report_contains_alert_level(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis_with_alerts()])
        html = gen.generate_model_report(model_dir)
        assert "warn" in html

    def test_report_contains_dimension_scores(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        html = gen.generate_model_report(model_dir)
        for dim in ["capability", "text_similarity", "behavior", "metadata", "statistical"]:
            assert dim in html

    def test_report_embedded_css(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        html = gen.generate_model_report(model_dir)
        assert "<style>" in html

    def test_report_contains_chart_data_script(self, tmp_path):
        gen = ReportGenerator()
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        html = gen.generate_model_report(model_dir)
        assert "chartData" in html
        assert "<script>" in html


class TestDualWrite:
    """双写逻辑: latest.html + 归档文件"""

    def test_latest_html_written(self, tmp_path):
        gen = ReportGenerator(output_dir=tmp_path)
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        gen.generate_and_save(model_dir)
        latest = tmp_path / "latest.html"
        assert latest.exists()

    def test_archive_html_written(self, tmp_path):
        gen = ReportGenerator(output_dir=tmp_path)
        model_dir = _setup_model_dir(tmp_path, [_make_analysis()])
        gen.generate_and_save(model_dir)
        archives = list(tmp_path.glob("report_*.html"))
        assert len(archives) == 1


class TestGlobalReport:
    """全局跨模型报告"""

    def test_global_report_contains_multiple_models(self, tmp_path):
        gen = ReportGenerator()
        a1 = _make_analysis(model="model-a", run_id="20260414100001")
        a2 = _make_analysis(model="model-b", run_id="20260414100002", overall_score=0.65)
        dir_a = _setup_model_dir(tmp_path, [a1])
        dir_b = _setup_model_dir(tmp_path, [a2])
        html = gen.generate_global_report([dir_a, dir_b])
        assert "model-a" in html
        assert "model-b" in html

    def test_global_report_contains_comparison_table(self, tmp_path):
        gen = ReportGenerator()
        a1 = _make_analysis(model="model-a")
        a2 = _make_analysis(model="model-b")
        dir_a = _setup_model_dir(tmp_path, [a1])
        dir_b = _setup_model_dir(tmp_path, [a2])
        html = gen.generate_global_report([dir_a, dir_b])
        assert "comparison" in html.lower() or "对比" in html


class TestEmptyInput:
    """边界情况: 空数据"""

    def test_empty_model_dir_returns_placeholder(self, tmp_path):
        gen = ReportGenerator()
        model_dir = tmp_path / "data" / "empty-model"
        model_dir.mkdir(parents=True)
        html = gen.generate_model_report(model_dir)
        assert "暂无数据" in html

    def test_empty_model_list_in_global(self):
        gen = ReportGenerator()
        html = gen.generate_global_report([])
        assert "暂无数据" in html
