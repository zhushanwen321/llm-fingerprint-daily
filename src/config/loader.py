"""配置加载器 — 读取 YAML 并解析环境变量引用"""

from __future__ import annotations

import os
import re

import yaml

from src.config.schema import AppConfig

# 匹配 ${ENV_VAR} 格式的环境变量引用
_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_vars(value: str) -> str:
    """将字符串中的 ${ENV_VAR} 替换为实际环境变量值"""
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            raise ValueError(f"环境变量 {var_name} 未设置")
        return os.environ[var_name]

    return _ENV_PATTERN.sub(_replace, value)


def _resolve_dict(data: object) -> object:
    """递归遍历字典/列表，解析所有字符串中的环境变量引用"""
    if isinstance(data, dict):
        return {k: _resolve_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_dict(item) for item in data]
    if isinstance(data, str):
        return _resolve_env_vars(data)
    return data


def load_config(path: str) -> AppConfig:
    """加载 YAML 配置文件，解析环境变量后返回 AppConfig 实例"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    resolved = _resolve_dict(raw)
    return AppConfig.model_validate(resolved)
