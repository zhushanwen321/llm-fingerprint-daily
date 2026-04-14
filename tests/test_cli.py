"""CLI 子命令注册与基本功能测试。

验证：
  - 所有子命令已注册
  - run 命令能正确调用 orchestrator
  - baseline 命令调用 storage.set_baseline
  - history 命令能解析并展示分析数据
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from src.main import app

runner = CliRunner()


class TestSubcommandsRegistered:
    """所有子命令应能被识别"""

    def test_run_registered(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output

    def test_report_registered(self):
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output

    def test_history_registered(self):
        result = runner.invoke(app, ["history", "--help"])
        assert result.exit_code == 0

    def test_serve_registered(self):
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0

    def test_baseline_registered(self):
        result = runner.invoke(app, ["baseline", "--help"])
        assert result.exit_code == 0
        assert "--run-id" in result.output
        assert "--model" in result.output


class TestRunCommand:
    """run 子命令应加载配置并执行 orchestrator"""

    def test_run_with_mock(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "providers:\n"
            "  p1:\n"
            "    base_url: http://fake\n"
            "    api_key: k\n"
            "evaluation:\n"
            "  schedule: [0]\n"
            "  targets: [{model: p1__m1}]\n",
            encoding="utf-8",
        )

        with patch("src.main.load_and_run") as mock_svc:
            mock_svc.return_value = {
                "run_id": "20260414120000",
                "models": ["p1__m1"],
            }
            result = runner.invoke(
                app, ["run", "--config", str(config_path)]
            )
            assert result.exit_code == 0
            assert "20260414120000" in result.output


class TestBaselineCommand:
    """baseline 子命令应调用 storage.set_baseline"""

    def test_baseline_missing_args(self):
        result = runner.invoke(app, ["baseline"])
        assert result.exit_code != 0

    def test_baseline_with_mock(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "providers:\n  p1:\n    base_url: http://fake\n    api_key: k\n"
            "evaluation:\n  schedule: [0]\n  targets: [{model: p1__m1}]\n",
            encoding="utf-8",
        )
        with patch("src.main.set_baseline") as _mock_svc:
            result = runner.invoke(
                app, [
                    "baseline",
                    "--run-id", "R001",
                    "--model", "p1__m1",
                    "--config", str(config_path),
                ],
            )
            assert result.exit_code == 0
            assert "R001" in result.output


class TestHistoryCommand:
    """history 子命令应读取分析文件并展示"""

    def test_history_with_sample_data(self, tmp_path):
        with patch("src.main.list_history") as mock_hist:
            mock_hist.return_value = [
                {"run_id": "20260414100000", "model": "p1__m1",
                 "overall_score": 0.85}
            ]
            result = runner.invoke(app, ["history", str(tmp_path)])
            assert result.exit_code == 0
            assert "20260414100000" in result.output
            assert "85.00%" in result.output

    def test_history_empty(self, tmp_path):
        with patch("src.main.list_history") as mock_hist:
            mock_hist.return_value = []
            result = runner.invoke(app, ["history", str(tmp_path)])
            assert result.exit_code == 0
            assert "暂无历史记录" in result.output
