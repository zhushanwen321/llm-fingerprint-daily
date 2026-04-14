"""存储层 — 系统唯一的文件写入出口。

所有 JSON 文件的读写都经过此类，使用 asyncio.to_thread 避免阻塞事件循环。
目录结构:
  data/{model_dir}/{probe_type}/{run_id}.json  — 探针结果
  data/{model_dir}/baseline.json               — 基线指针
  data/{model_dir}/analysis/{run_id}.json       — 分析结果
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


class Storage:
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    # ---- 路径工具 ----

    def _model_path(self, model_dir: str) -> Path:
        return self._base / "data" / model_dir

    # ---- 探针结果读写 ----

    async def save_run(
        self, model_dir: str, probe_type: str, run_id: str, data: dict
    ) -> None:
        """将探针结果写入 JSON 文件"""
        path = self._model_path(model_dir) / probe_type / f"{run_id}.json"
        await asyncio.to_thread(self._write_json, path, data)

    async def load_run(
        self, model_dir: str, probe_type: str, run_id: str
    ) -> dict | None:
        """读取单次探针结果，不存在则返回 None"""
        path = self._model_path(model_dir) / probe_type / f"{run_id}.json"
        if not path.exists():
            return None
        return await asyncio.to_thread(self._read_json, path)

    async def list_runs(self, model_dir: str, probe_type: str) -> list[str]:
        """列出指定模型+探针类型下的所有 run_id，按时间排序"""
        dir_path = self._model_path(model_dir) / probe_type
        if not dir_path.exists():
            return []
        return sorted(
            p.stem
            for p in dir_path.glob("*.json")
            if p.is_file()
        )

    # ---- 基线管理 ----

    async def set_baseline(
        self, model_dir: str, run_id: str, set_by: str = "auto"
    ) -> None:
        """更新基线指针，保留历史记录"""
        bl_path = self._model_path(model_dir) / "baseline.json"
        now = datetime.now(timezone.utc).isoformat()

        if bl_path.exists():
            bl_data = await asyncio.to_thread(self._read_json, bl_path)
        else:
            bl_data = {"current_baseline_run_id": None, "history": []}

        bl_data["history"].append(
            {"run_id": run_id, "set_at": now, "set_by": set_by}
        )
        bl_data["current_baseline_run_id"] = run_id
        await asyncio.to_thread(self._write_json, bl_path, bl_data)

    async def get_baseline(self, model_dir: str) -> str | None:
        """读取当前基线 run_id"""
        bl_path = self._model_path(model_dir) / "baseline.json"
        if not bl_path.exists():
            return None
        bl_data = await asyncio.to_thread(self._read_json, bl_path)
        return bl_data.get("current_baseline_run_id")

    # ---- 分析结果 ----

    async def save_analysis(
        self, model_dir: str, run_id: str, data: dict
    ) -> None:
        """保存分析结果"""
        path = self._model_path(model_dir) / "analysis" / f"{run_id}.json"
        await asyncio.to_thread(self._write_json, path, data)

    # ---- 同步底层（供 to_thread 调用）----

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))
