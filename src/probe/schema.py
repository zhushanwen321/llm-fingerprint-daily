"""探针数据模型 -- 定义各类型探针的 JSON 结构"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


# ---- 公共子模型 ----

class Constraint(BaseModel):
    """instruction 探针的约束条件，value 类型随 type 变化"""
    type: Literal[
        "language", "max_words", "format", "no_markdown",
        "field_names", "max_length", "no_punctuation", "conclusion_first",
    ]
    value: bool | int | str | list[str]
    description: str = ""


class Scoring(BaseModel):
    """coding 探针的评分规则"""
    must_contain: list[str] = Field(default_factory=list)
    should_contain: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    check_points: list[str] = Field(default_factory=list)


class Analysis(BaseModel):
    """style 探针的分析配置"""
    extract: list[str] = Field(default_factory=list)
    baseline_compare: str = "full_text"


class Variant(BaseModel):
    """consistency 探针的变体"""
    label: str
    prompt: str


# ---- 探针模型 ----

class SimpleProbe(BaseModel):
    """instruction 类型探针"""
    id: str
    type: Literal["instruction"] = "instruction"
    language: str
    prompt: str
    max_tokens: int = 500
    difficulty: str = "medium"
    constraints: list[Constraint] = Field(default_factory=list)


class StatisticalProbe(BaseModel):
    """statistical 类型探针 -- 最简形式，无约束"""
    id: str
    type: Literal["statistical"] = "statistical"
    language: str
    prompt: str
    max_tokens: int = 300
    difficulty: str = "easy"


class CodingProbe(BaseModel):
    """coding 类型探针 -- 带评分规则"""
    id: str
    type: Literal["coding_frontend", "coding_backend"] = "coding_frontend"
    language: str
    prompt: str
    max_tokens: int = 2048
    scoring: Scoring


class StyleProbe(BaseModel):
    """style 类型探针 -- 带分析配置"""
    id: str
    type: Literal["style_open"] = "style_open"
    language: str
    prompt: str
    max_tokens: int = 500
    analysis: Analysis


class ConsistencyProbe(BaseModel):
    """consistency 类型探针 -- 多变体"""
    id: str
    type: Literal["consistency"] = "consistency"
    language: str
    variants: list[Variant]
    expected_consistency: str = "same_answer"
    max_tokens: int = 500


# 联合类型，用于 loader 按分发
Probe = Annotated[
    Union[SimpleProbe, StatisticalProbe, CodingProbe, StyleProbe, ConsistencyProbe],
    Field(discriminator="type"),
]
