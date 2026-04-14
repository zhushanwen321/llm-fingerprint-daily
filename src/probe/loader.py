"""探针加载器 -- 从目录读取 JSON 探针文件"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from src.probe.schema import (
    SimpleProbe,
    StatisticalProbe,
    CodingProbe,
    StyleProbe,
    ConsistencyProbe,
)

logger = logging.getLogger(__name__)

# type literal -> model 的映射，用于按 type 字段分发
_TYPE_MAP: dict[str, type] = {
    "instruction": SimpleProbe,
    "statistical": StatisticalProbe,
    "coding_frontend": CodingProbe,
    "style_open": StyleProbe,
    "consistency": ConsistencyProbe,
}


def load_probes(
    probe_dir: str,
    probe_types: list[str] | None = None,
) -> dict[str, list]:
    """
    加载目录下所有探针 JSON 文件。

    每个 JSON 文件是一个探针对象数组。
    返回按 probe_type 分组的字典。
    """
    result: dict[str, list] = {}
    dir_path = Path(probe_dir)
    if not dir_path.is_dir():
        return result

    allowed = set(probe_types) if probe_types else None

    for json_file in sorted(dir_path.glob("*.json")):
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("跳过无法解析的文件: %s", json_file)
            continue

        if not isinstance(raw, list):
            logger.warning("跳过非数组文件: %s", json_file)
            continue

        for item in raw:
            probe_type = item.get("type") if isinstance(item, dict) else None
            if probe_type is None:
                continue
            if allowed is not None and probe_type not in allowed:
                continue

            model_cls = _TYPE_MAP.get(probe_type)
            if model_cls is None:
                logger.warning("未知探针类型 %s，跳过", probe_type)
                continue

            try:
                probe = model_cls.model_validate(item)
                result.setdefault(probe_type, []).append(probe)
            except ValidationError:
                logger.warning("探针 %s 验证失败，跳过", item.get("id", "?"))

    return result
