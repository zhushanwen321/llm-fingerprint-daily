"""capability 分析模块的单元测试"""

import pytest

from src.probe.schema import SimpleProbe, CodingProbe, Constraint, Scoring
from src.analysis.capability import (
    check_instruction,
    check_coding,
    compare,
    DimensionScore,
)


# ---- 测试用探针 ----

def _make_instruction_probe(constraints: list[dict]) -> SimpleProbe:
    return SimpleProbe.model_validate({
        "id": "instr_001",
        "type": "instruction",
        "language": "en",
        "prompt": "Say hello",
        "max_tokens": 100,
        "constraints": constraints,
    })


def _make_coding_probe(
    must: list[str] | None = None,
    should: list[str] | None = None,
    forbidden: list[str] | None = None,
    checkpoints: list[str] | None = None,
) -> CodingProbe:
    return CodingProbe.model_validate({
        "id": "code_001",
        "type": "coding_frontend",
        "language": "en",
        "prompt": "Write code",
        "max_tokens": 500,
        "scoring": {
            "must_contain": must or [],
            "should_contain": should or [],
            "forbidden_patterns": forbidden or [],
            "check_points": checkpoints or [],
        },
    })


# ---- check_instruction 测试 ----

class TestCheckInstruction:
    """指令约束满足率"""

    def test_all_constraints_satisfied(self):
        probe = _make_instruction_probe([
            {"type": "language", "value": "en"},
            {"type": "max_words", "value": 50},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "Hello world"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_language_constraint_zh(self):
        probe = _make_instruction_probe([
            {"type": "language", "value": "zh"},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "你好世界"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_language_constraint_fail(self):
        probe = _make_instruction_probe([
            {"type": "language", "value": "zh"},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "Hello world"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_max_words_exceeded(self):
        probe = _make_instruction_probe([
            {"type": "max_words", "value": 3},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "one two three four five"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_format_json_valid(self):
        probe = _make_instruction_probe([
            {"type": "format", "value": "json"},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": '{"key": "value"}'}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_format_json_invalid(self):
        probe = _make_instruction_probe([
            {"type": "format", "value": "json"},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "not json"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_no_markdown_pass(self):
        probe = _make_instruction_probe([
            {"type": "no_markdown", "value": True},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "Plain text only"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_no_markdown_fail(self):
        probe = _make_instruction_probe([
            {"type": "no_markdown", "value": True},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "**bold** text"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_field_names_match(self):
        probe = _make_instruction_probe([
            {"type": "field_names", "value": ["name", "age"]},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": '{"name": "Tom", "age": 25}'}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_max_length_pass(self):
        probe = _make_instruction_probe([
            {"type": "max_length", "value": 10},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "short"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_max_length_fail(self):
        probe = _make_instruction_probe([
            {"type": "max_length", "value": 5},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "this is too long"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_no_punctuation_pass(self):
        probe = _make_instruction_probe([
            {"type": "no_punctuation", "value": True},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "hello world"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_no_punctuation_fail(self):
        probe = _make_instruction_probe([
            {"type": "no_punctuation", "value": True},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "hello, world!"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_conclusion_first_pass(self):
        probe = _make_instruction_probe([
            {"type": "conclusion_first", "value": True},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "Therefore, X is true."}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_conclusion_first_fail(self):
        probe = _make_instruction_probe([
            {"type": "conclusion_first", "value": True},
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "Let me think about it."}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_partial_constraints(self):
        """4 个约束中满足 2 个 -> 0.5"""
        probe = _make_instruction_probe([
            {"type": "language", "value": "en"},
            {"type": "max_words", "value": 3},  # fail: 超过3词
            {"type": "no_markdown", "value": True},  # pass
            {"type": "format", "value": "json"},  # fail: 非 json
        ])
        results = [{"probe_id": "instr_001", "response": {"text": "one two three four"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.5)

    def test_empty_results(self):
        probe = _make_instruction_probe([{"type": "language", "value": "en"}])
        rate = check_instruction([], [probe])
        assert rate == pytest.approx(0.0)

    def test_error_response_skipped(self):
        """error 响应不计入"""
        probe = _make_instruction_probe([{"type": "language", "value": "en"}])
        results = [{"probe_id": "instr_001", "error": {"message": "timeout"}}]
        rate = check_instruction(results, [probe])
        assert rate == pytest.approx(0.0)


# ---- check_coding 测试 ----

class TestCheckCoding:
    """编码覆盖率"""

    def test_full_score(self):
        probe = _make_coding_probe(
            must=["setTimeout", "clearTimeout"],
            should=["TypeScript"],
            forbidden=[],
            checkpoints=["debounce"],
        )
        text = "function debounce() { setTimeout(fn, 100); clearTimeout(id); } // TypeScript"
        results = [{"probe_id": "code_001", "response": {"text": text}}]
        rate = check_coding(results, [probe])
        assert rate == pytest.approx(1.0)

    def test_must_contain_missing(self):
        probe = _make_coding_probe(
            must=["setTimeout", "clearTimeout"],
        )
        results = [{"probe_id": "code_001", "response": {"text": "function foo() {}"}}]
        rate = check_coding(results, [probe])
        assert rate < 1.0

    def test_should_contain_partial(self):
        probe = _make_coding_probe(
            must=[],
            should=["TypeScript", "generic"],
        )
        results = [{"probe_id": "code_001", "response": {"text": "use TypeScript"}}]
        rate = check_coding(results, [probe])
        assert 0 < rate < 1.0

    def test_forbidden_penalty(self):
        probe = _make_coding_probe(
            must=["setTimeout"],
            forbidden=["any"],
        )
        text = "setTimeout(fn); const x: any = 1;"
        results = [{"probe_id": "code_001", "response": {"text": text}}]
        rate = check_coding(results, [probe])
        assert rate < 1.0

    def test_clamped_to_zero(self):
        probe = _make_coding_probe(
            must=["setTimeout"],
            forbidden=["any"],
        )
        text = "const x: any = 1;"
        results = [{"probe_id": "code_001", "response": {"text": text}}]
        rate = check_coding(results, [probe])
        assert rate == pytest.approx(0.0)

    def test_empty_results(self):
        probe = _make_coding_probe(must=["setTimeout"])
        rate = check_coding([], [probe])
        assert rate == pytest.approx(0.0)


# ---- compare 测试 ----

class TestCompare:
    """基线对比评分"""

    def test_no_drop_normal(self):
        score = compare(0.9, 0.9, {"warn": 0.1, "critical": 0.2})
        assert score.alert_level == "normal"
        assert score.score == pytest.approx(1.0)

    def test_small_drop_normal(self):
        score = compare(0.85, 0.9, {"warn": 0.1, "critical": 0.2})
        assert score.alert_level == "normal"

    def test_warn_drop(self):
        score = compare(0.75, 0.9, {"warn": 0.1, "critical": 0.2})
        assert score.alert_level == "warn"

    def test_critical_drop(self):
        score = compare(0.6, 0.9, {"warn": 0.1, "critical": 0.2})
        assert score.alert_level == "critical"

    def test_score_never_negative(self):
        score = compare(0.0, 1.0, {"warn": 0.1, "critical": 0.2})
        assert score.score >= 0.0

    def test_detail_contains_rates(self):
        score = compare(0.8, 0.9, {"warn": 0.1, "critical": 0.2})
        assert "0.8" in score.detail or "80" in score.detail
