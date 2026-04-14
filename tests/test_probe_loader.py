"""探针数据模型与加载器的单元测试"""

import json
import pytest
from pathlib import Path

from src.probe.schema import (
    SimpleProbe,
    StatisticalProbe,
    CodingProbe,
    StyleProbe,
    ConsistencyProbe,
)
from src.probe.loader import load_probes


# ---- 固定的测试 JSON 数据 ----

_INSTRUCTION_PROBE = {
    "id": "instruction_001",
    "type": "instruction",
    "language": "en",
    "prompt": "Explain quantum computing in one sentence.",
    "max_tokens": 500,
    "difficulty": "hard",
    "constraints": [
        {"type": "language", "value": "en", "description": "Must be in English"},
        {"type": "max_words", "value": 50, "description": "Max 50 words"},
    ],
}

_STAT_PROBE = {
    "id": "stat_001",
    "type": "statistical",
    "language": "en",
    "prompt": "What is 2+2?",
    "max_tokens": 300,
    "difficulty": "easy",
}

_CODING_PROBE = {
    "id": "coding_fe_001",
    "type": "coding_frontend",
    "language": "en",
    "prompt": "Write a debounce function.",
    "max_tokens": 2048,
    "scoring": {
        "must_contain": ["setTimeout", "clearTimeout"],
        "should_contain": ["TypeScript generic"],
        "forbidden_patterns": ["any", "// TODO"],
        "check_points": ["handles rapid calls", "preserves this context"],
    },
}

_STYLE_PROBE = {
    "id": "style_en_001",
    "type": "style_open",
    "language": "en",
    "prompt": "Describe a sunset.",
    "max_tokens": 500,
    "analysis": {
        "extract": ["sentence_count", "avg_word_length", "punctuation_ratio"],
        "baseline_compare": "full_text",
    },
}

_CONSISTENCY_PROBE = {
    "id": "consistency_001",
    "type": "consistency",
    "language": "mixed",
    "variants": [
        {"label": "natural_language", "prompt": "Solve: 3x+7=22"},
        {"label": "code_description", "prompt": "Given x such that 3*x+7==22, find x"},
        {"label": "mathematical", "prompt": "Find x: 3x + 7 = 22"},
    ],
    "expected_consistency": "same_answer",
    "max_tokens": 500,
}


class TestSimpleProbe:
    """instruction 类型探针"""

    def test_parse_instruction_probe(self):
        p = SimpleProbe.model_validate(_INSTRUCTION_PROBE)
        assert p.id == "instruction_001"
        assert p.difficulty == "hard"
        assert len(p.constraints) == 2
        assert p.constraints[0].type == "language"
        assert p.constraints[0].value == "en"

    def test_constraint_types(self):
        """验证各种约束类型都能正确解析"""
        probe_data = {
            **_INSTRUCTION_PROBE,
            "constraints": [
                {"type": "language", "value": "zh"},
                {"type": "max_words", "value": 100},
                {"type": "format", "value": "json"},
                {"type": "no_markdown", "value": True},
                {"type": "field_names", "value": ["name", "age"]},
                {"type": "max_length", "value": 200},
                {"type": "no_punctuation", "value": True},
                {"type": "conclusion_first", "value": True},
            ],
        }
        p = SimpleProbe.model_validate(probe_data)
        assert len(p.constraints) == 8
        assert p.constraints[4].value == ["name", "age"]

    def test_instruction_without_constraints(self):
        """constraints 可选"""
        data = {**_INSTRUCTION_PROBE, "constraints": []}
        p = SimpleProbe.model_validate(data)
        assert p.constraints == []


class TestStatisticalProbe:
    """statistical 类型探针"""

    def test_parse_statistical_probe(self):
        p = StatisticalProbe.model_validate(_STAT_PROBE)
        assert p.difficulty == "easy"
        assert p.max_tokens == 300


class TestCodingProbe:
    """coding 类型探针"""

    def test_parse_coding_probe(self):
        p = CodingProbe.model_validate(_CODING_PROBE)
        assert p.scoring.must_contain == ["setTimeout", "clearTimeout"]
        assert p.scoring.forbidden_patterns == ["any", "// TODO"]


class TestStyleProbe:
    """style 类型探针"""

    def test_parse_style_probe(self):
        p = StyleProbe.model_validate(_STYLE_PROBE)
        assert p.analysis.baseline_compare == "full_text"
        assert "sentence_count" in p.analysis.extract


class TestConsistencyProbe:
    """consistency 类型探针"""

    def test_parse_consistency_probe(self):
        p = ConsistencyProbe.model_validate(_CONSISTENCY_PROBE)
        assert p.language == "mixed"
        assert len(p.variants) == 3
        assert p.expected_consistency == "same_answer"


class TestConstraintValidation:
    """约束值类型验证"""

    def test_invalid_constraint_type(self):
        """未知的约束类型应报错"""
        data = {
            **_INSTRUCTION_PROBE,
            "constraints": [
                {"type": "unknown_type", "value": "x"},
            ],
        }
        with pytest.raises(Exception):
            SimpleProbe.model_validate(data)


class TestLoader:
    """加载器集成测试"""

    def _write_probes(self, tmp_path: Path, probes: list[dict]) -> Path:
        probe_file = tmp_path / "test_probes.json"
        probe_file.write_text(json.dumps(probes), encoding="utf-8")
        return tmp_path

    def test_load_all_probes(self, tmp_path):
        """加载目录下所有探针"""
        self._write_probes(
            tmp_path,
            [_INSTRUCTION_PROBE, _STAT_PROBE, _CODING_PROBE],
        )
        result = load_probes(str(tmp_path))
        assert "instruction" in result
        assert "statistical" in result
        assert "coding_frontend" in result
        assert len(result["instruction"]) == 1
        assert len(result["statistical"]) == 1

    def test_load_filtered_by_type(self, tmp_path):
        """按类型过滤加载"""
        self._write_probes(
            tmp_path,
            [_INSTRUCTION_PROBE, _STAT_PROBE, _CODING_PROBE],
        )
        result = load_probes(str(tmp_path), probe_types=["instruction"])
        assert len(result) == 1
        assert "instruction" in result

    def test_load_empty_dir(self, tmp_path):
        """空目录返回空 dict"""
        result = load_probes(str(tmp_path))
        assert result == {}

    def test_skip_invalid_files(self, tmp_path):
        """跳过无法解析的 JSON 文件，不抛异常"""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")
        good_file = tmp_path / "good.json"
        good_file.write_text(json.dumps([_STAT_PROBE]), encoding="utf-8")
        result = load_probes(str(tmp_path))
        assert "statistical" in result

    def test_skip_invalid_probes_in_file(self, tmp_path):
        """文件中部分无效探针应跳过，有效部分正常加载"""
        mixed = [
            _STAT_PROBE,
            {"id": "bad", "type": "unknown_type"},  # 无效
            _STAT_PROBE,  # id 重复但类型有效
        ]
        probe_file = tmp_path / "mixed.json"
        probe_file.write_text(json.dumps(mixed), encoding="utf-8")
        result = load_probes(str(tmp_path))
        # 至少应加载有效的 statistical 探针
        assert "statistical" in result
        assert len(result["statistical"]) >= 1
