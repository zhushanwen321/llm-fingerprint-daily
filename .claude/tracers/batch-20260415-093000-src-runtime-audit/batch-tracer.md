# 批量代码分析汇总报告

## 概述
- 批次名称：20260415-093000-src-runtime-audit
- 分析时间：2026-04-15
- 分析目录：src/
- 扫描文件数：26
- 过滤文件数：6（__init__.py 空文件）
- 分析文件数：20
- 成功完成：20
- 失败：0

## 文件清单

| 文件 | 扫描结果 | 状态 |
|-----|---------|------|
| src/main.py | 有问题（详见下文） | 完成 |
| src/cli_service.py | 有问题 | 完成 |
| src/config/schema.py | 无问题 | 完成 |
| src/config/loader.py | 无问题 | 完成 |
| src/engine/orchestrator.py | 严重问题 | 完成 |
| src/engine/llm_gateway.py | 有问题 | 完成 |
| src/engine/storage.py | 无问题 | 完成 |
| src/engine/provider_runner.py | 无问题 | 完成 |
| src/engine/target_runner.py | 严重问题 | 完成 |
| src/analysis/analyzer.py | 无问题 | 完成 |
| src/analysis/_constraint.py | 无问题 | 完成 |
| src/analysis/behavior.py | 无问题 | 完成 |
| src/analysis/capability.py | 无问题 | 完成 |
| src/analysis/metadata.py | 无问题 | 完成 |
| src/analysis/similarity.py | 无问题 | 完成 |
| src/analysis/statistical.py | 无问题 | 完成 |
| src/probe/schema.py | 无问题 | 完成 |
| src/probe/loader.py | 无问题 | 完成 |
| src/report/generator.py | 无问题 | 完成 |
| src/scheduler/core.py | 已修复 | 完成 |

## 问题汇总

### 严重问题（必定崩溃）

#### P0-1: orchestrator.py:75 — target.model 格式与 providers 键不匹配

**根因**：`TargetEntry.model` 值为纯模型名（如 `claude-sonnet-4-20250514`），但代码假设格式为 `provider__model`。

```python
# orchestrator.py:75
provider = t.model.split("__", 1)[0]  # 得到 "claude-sonnet-4-20250514"
# orchestrator.py:81
concurrency = self._config.providers[provider].concurrency  # KeyError!
```

配置中 providers 的键是 `anthropic`、`openrouter`，但 split 后得到的是整个模型名，查找时必然 KeyError。

**影响**：每次执行 `run` 或 `serve` 命令必定崩溃。

#### P0-2: target_runner.py:65 — model_dir 不含 `__` 时解包失败

```python
provider, model = model_dir.split("__", 1)  # ValueError!
```

即使 P0-1 修复后，model_dir 仍然不含 `__`，此处会抛出 `ValueError: not enough values to unpack`。

#### P0-3: llm_gateway.py:69,70 — provider 不存在时 KeyError

`self._config.providers[provider]` 和 `self._provider_sems[provider]` 用下标访问，无 `.get()` 保护。由 P0-1 引起的错误 provider 名会在此处再次 KeyError。

### 一般问题（特定条件下崩溃）

#### P1-1: cli_service.py:55 — list_history data 目录不存在时崩溃

`base.iterdir()` 在 `./data` 不存在时抛出 `FileNotFoundError`。首次运行或数据目录被清理后执行 `history` 命令必定崩溃。

#### P1-2: cli_service.py:85,91 — generate_report data 目录不存在时崩溃

同 P1-1，`generate_report` 中 `base.iterdir()` 在目录不存在时崩溃。

#### P1-3: llm_gateway.py:88,105 — max_retries=0 时 raise None

如果用户配置 `max_retries: 0`，`range(1, 1)` 为空，`last_exc` 保持 None，`raise last_exc` 抛出 TypeError。

### 轻微问题

#### P2-1: main.py:29 — 默认 config.yaml 不存在

项目只有 `config.example.yaml`，新用户首次运行所有命令都会因配置文件缺失报错。

#### P2-2: llm_gateway.py:136 — API 非标准响应格式时 KeyError/IndexError

`data["content"][0]["text"]` 假设响应格式固定。若 API 返回异常格式（如 content 为空），会抛出未捕获异常。已被上层 `except Exception` 兜住，不会整体崩溃，但错误信息不明确。

## 审查质量评估

- analysis 层（7个文件）：边界条件处理完善，除零、空值、异常捕获均已覆盖
- probe 层：YAML 文件与 schema 完全匹配，无问题
- report 层：Jinja2 模板变量传递正确
