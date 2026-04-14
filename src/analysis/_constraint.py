"""instruction 约束检查器 -- 单个约束的判定逻辑"""

from __future__ import annotations

import json
import re

from src.probe.schema import Constraint


def check(text: str, constraint: Constraint) -> bool:
    """检查 text 是否满足单个约束"""
    t = constraint.type
    v = constraint.value

    if t == "language":
        return _check_language(text, str(v))
    if t == "max_words":
        return _check_max_words(text, int(v))
    if t == "format":
        return _check_format(text, str(v))
    if t == "no_markdown":
        return not bool(re.search(r"[*#`]", text))
    if t == "field_names":
        return _check_field_names(text, list(v))
    if t == "max_length":
        return len(text) <= int(v)
    if t == "no_punctuation":
        return not bool(re.search(r"[,.!?;:'\"]", text))
    if t == "conclusion_first":
        return _check_conclusion_first(text)
    return False


def _check_language(text: str, lang: str) -> bool:
    if lang == "en":
        return bool(re.search(r"[a-zA-Z]", text))
    if lang == "zh":
        return bool(re.search(r"[\u4e00-\u9fff]", text))
    return True


def _check_max_words(text: str, limit: int) -> bool:
    # 英文按空格分词，中文按字符计数，取较大值
    en_words = len(text.split())
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return max(en_words, zh_chars) <= limit


def _check_format(text: str, fmt: str) -> bool:
    text = text.strip()
    if fmt == "json":
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, ValueError):
            return False
    if fmt == "xml":
        return text.startswith("<") and text.endswith(">")
    return False


def _check_field_names(text: str, expected: list[str]) -> bool:
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return all(k in obj for k in expected)
    except (json.JSONDecodeError, ValueError):
        pass
    return False


_CONCLUSION_WORDS = re.compile(
    r"^(therefore|thus|hence|consequently|in conclusion|"
    r"as a result|clearly|obviously|indeed|the answer is)",
    re.IGNORECASE,
)


def _check_conclusion_first(text: str) -> bool:
    first_sentence = re.split(r"[.!?]", text, maxsplit=1)[0].strip()
    return bool(_CONCLUSION_WORDS.match(first_sentence))
