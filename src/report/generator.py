"""报告生成器 -- 从分析结果生成自包含 HTML 报告

使用 Jinja2 模板 + Chart.js 生成可视化报告。
支持单模型报告和跨模型全局报告。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _BASE_DIR / "templates"


class ReportGenerator:
    def __init__(self, output_dir: Path | str | None = None) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        self._output_dir = Path(output_dir) if output_dir else None

    # ---- 单模型报告 ----

    def generate_model_report(self, model_dir: Path) -> str:
        """读取 model_dir/analysis/ 下所有 JSON，渲染单模型报告"""
        analyses = self._load_analyses(model_dir)
        if not analyses:
            return self._render("report.html", {
                "report_title": "单模型报告",
                "generated_at": self._now(),
                "analyses": None,
                "all_alerts": None,
                "chart_data": None,
            })

        chart_data = self._build_chart_data(analyses)
        all_alerts = self._collect_alerts(analyses)
        return self._render("report.html", {
            "report_title": f"模型报告: {analyses[-1]['model']}",
            "generated_at": self._now(),
            "analyses": analyses,
            "all_alerts": all_alerts,
            "chart_data": chart_data,
        })

    # ---- 全局报告 ----

    def generate_global_report(self, model_dirs: list[Path]) -> str:
        """跨模型对比报告，每个 model_dir 取最新一次分析结果"""
        entries = []
        for md in model_dirs:
            analyses = self._load_analyses(md)
            if analyses:
                entries.append(analyses[-1])

        if not entries:
            return self._render("report.html", {
                "report_title": "全局报告",
                "generated_at": self._now(),
                "analyses": None,
                "all_alerts": None,
                "chart_data": None,
            })

        chart_data = self._build_chart_data(entries)
        all_alerts = self._collect_alerts(entries)
        return self._render("report.html", {
            "report_title": "全局对比报告",
            "generated_at": self._now(),
            "analyses": entries,
            "all_alerts": all_alerts,
            "chart_data": chart_data,
        })

    # ---- 双写 ----

    def generate_and_save(self, model_dir: Path) -> None:
        """生成报告并写入 latest.html + 归档文件"""
        if not self._output_dir:
            raise ValueError("output_dir is required for generate_and_save")
        self._output_dir.mkdir(parents=True, exist_ok=True)

        analyses = self._load_analyses(model_dir)
        latest = analyses[-1] if analyses else {}
        run_id = latest.get("run_id", "unknown")
        html = self.generate_model_report(model_dir)

        # latest.html 覆盖写
        (self._output_dir / "latest.html").write_text(html, encoding="utf-8")
        # 归档文件
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        archive_name = f"report_{date_str}_{run_id}.html"
        (self._output_dir / archive_name).write_text(html, encoding="utf-8")

    # ---- 内部方法 ----

    def _load_analyses(self, model_dir: Path) -> list[dict]:
        """读取 model_dir/analysis/*.json，按 run_id 排序"""
        analysis_dir = model_dir / "analysis"
        if not analysis_dir.exists():
            return []
        files = sorted(analysis_dir.glob("*.json"))
        results = []
        for f in files:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        return results

    @staticmethod
    def _build_chart_data(analyses: list[dict]) -> dict:
        """构建 Chart.js 需要的 JSON 数据"""
        run_ids = [a["run_id"] for a in analyses]
        dimensions: dict[str, list[float]] = {}
        for a in analyses:
            for dim_name, dim_val in a.get("dimensions", {}).items():
                dimensions.setdefault(dim_name, []).append(
                    round(dim_val["score"] * 100, 2)
                )
        return {"run_ids": run_ids, "dimensions": dimensions}

    @staticmethod
    def _collect_alerts(analyses: list[dict]) -> list[dict]:
        """汇总所有分析结果中的告警，附加 run_id"""
        alerts = []
        for a in analyses:
            for alert in a.get("alerts", []):
                alerts.append({**alert, "run_id": a["run_id"]})
        return alerts

    def _render(self, template_name: str, data: dict) -> str:
        tmpl = self._env.get_template(template_name)
        return tmpl.render(**data)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
