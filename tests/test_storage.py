"""Storage 层单元测试 — 覆盖所有公开方法的正常路径和边界情况"""

import json
import pytest

from src.engine.storage import Storage

_SAMPLE_DATA = {"response": "hello", "tokens": 42, "latency_ms": 120}


class TestSaveRun:
    """save_run / load_run / list_runs 三件套"""

    @pytest.mark.asyncio
    async def test_save_and_load_run(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        await storage.save_run(
            "provider__model", "instruction", "20260414100003", _SAMPLE_DATA
        )
        result = await storage.load_run(
            "provider__model", "instruction", "20260414100003"
        )
        assert result == _SAMPLE_DATA

    @pytest.mark.asyncio
    async def test_save_creates_correct_path(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        await storage.save_run(
            "openai__gpt-4o", "style_open", "20260414100003", _SAMPLE_DATA
        )
        expected = (
            tmp_path / "data" / "openai__gpt-4o"
            / "style_open" / "20260414100003.json"
        )
        assert expected.exists()
        assert json.loads(expected.read_text()) == _SAMPLE_DATA

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        result = await storage.load_run(
            "provider__model", "instruction", "nonexistent"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_runs_sorted(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        run_ids = ["20260414100003", "20260414100001", "20260414100002"]
        for rid in run_ids:
            await storage.save_run(
                "provider__model", "instruction", rid, _SAMPLE_DATA
            )
        result = await storage.list_runs("provider__model", "instruction")
        assert result == ["20260414100001", "20260414100002", "20260414100003"]

    @pytest.mark.asyncio
    async def test_list_runs_empty_dir(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        result = await storage.list_runs("provider__model", "instruction")
        assert result == []


class TestBaselineManagement:
    """baseline 的设置与读取"""

    @pytest.mark.asyncio
    async def test_set_and_get_baseline(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        await storage.set_baseline(
            "provider__model", "20260414100003", set_by="auto"
        )
        baseline = await storage.get_baseline("provider__model")
        assert baseline == "20260414100003"

    @pytest.mark.asyncio
    async def test_baseline_history(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        await storage.set_baseline(
            "provider__model", "20260414000001", set_by="manual"
        )
        await storage.set_baseline(
            "provider__model", "20260414000002", set_by="auto"
        )
        bl_path = tmp_path / "data" / "provider__model" / "baseline.json"
        bl_data = json.loads(bl_path.read_text())
        assert len(bl_data["history"]) == 2
        assert bl_data["history"][0]["run_id"] == "20260414000001"
        assert bl_data["history"][1]["run_id"] == "20260414000002"

    @pytest.mark.asyncio
    async def test_get_baseline_when_none(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        baseline = await storage.get_baseline("provider__model")
        assert baseline is None


class TestSaveAnalysis:
    """save_analysis 的写入和读取"""

    @pytest.mark.asyncio
    async def test_save_analysis(self, tmp_path):
        storage = Storage(base_dir=tmp_path)
        analysis_data = {"score": 0.85, "details": {"drift": 0.12}}
        await storage.save_analysis(
            "provider__model", "20260414100003", analysis_data
        )
        expected = (
            tmp_path / "data" / "provider__model"
            / "analysis" / "20260414100003.json"
        )
        assert expected.exists()
        assert json.loads(expected.read_text()) == analysis_data
