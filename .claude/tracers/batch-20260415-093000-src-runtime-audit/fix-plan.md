# 代码修复计划

## 概述
- 批次：batch-20260415-093000-src-runtime-audit
- 严重问题数：3
- 一般问题数：3
- 轻微问题数：2

## 核心设计决策

**P0-1/2/3 的根因是同一个**：`TargetEntry` 只有 `model` 字段，没有 `provider` 字段。代码用 `model.split("__", 1)[0]` 猜测 provider，但配置中 model 值不含 `__`。

**修复方案**：在 `TargetEntry` 中添加 `provider` 字段，让 target 明确声明自己属于哪个 provider。这比强制 model 名包含 `__` 更清晰，也与 `ModelEntry` 已有的 `provider` 字段保持一致。

## 优先修复（P0 — 必定崩溃）

| 优先级 | 问题 | 文件 | 行号 | 修复方案 |
|--------|------|------|------|----------|
| P0 | target.model 格式与 providers 键不匹配 | orchestrator.py | 75,81 | 从 TargetEntry.provider 获取 provider，不再 split model |
| P0 | model_dir 不含 `__` 时解包失败 | target_runner.py | 65 | model_dir 改为纯 model 名，provider 由参数传入 |
| P0 | provider 不存在时 KeyError | llm_gateway.py | 69,70 | 上游修复后此问题自动消除 |

## 计划修复（P1 — 特定条件崩溃）

| 优先级 | 问题 | 文件 | 行号 | 修复方案 |
|--------|------|------|------|----------|
| P1 | data 目录不存在时崩溃 | cli_service.py | 55,85,91 | iterdir 前检查目录是否存在，不存在返回空列表 |
| P1 | max_retries=0 时 raise None | llm_gateway.py | 105 | 在 raise 前检查 last_exc 是否为 None，为 None 则抛出明确异常 |

## 可选优化（P2）

| 问题 | 文件 | 建议 |
|------|------|------|
| 默认 config.yaml 不存在 | main.py | 启动时若文件不存在给出友好提示 |
| API 响应格式异常 | llm_gateway.py | 用 .get() 安全访问 content |

## 详细修复步骤

### 步骤 1：schema.py — TargetEntry 添加 provider 字段

```python
class TargetEntry(BaseModel):
    provider: str          # 新增
    model: str
    enabled: bool = True
    baseline_run_id: str | None = None
```

### 步骤 2：orchestrator.py — 使用 TargetEntry.provider

- 第 75 行：改为 `provider = t.provider`
- 第 88-91 行：model_dirs 列表存储 `(provider, model)` 元组

### 步骤 3：target_runner.py — provider 由参数传入

- `run()` 方法签名添加 `provider` 参数
- 移除 `model_dir.split("__", 1)` 解包逻辑

### 步骤 4：provider_runner.py — 传递 provider

- 适配 orchestrator 传来的新数据格式

### 步骤 5：cli_service.py — 目录存在性检查

- `list_history` 和 `generate_report` 中 iterdir 前加 `base.exists()` 检查

### 步骤 6：llm_gateway.py — max_retries=0 保护

- 在 `raise last_exc` 前加 None 检查

### 步骤 7：config.example.yaml — targets 添加 provider 字段

```yaml
targets:
  - provider: anthropic
    model: "claude-sonnet-4-20250514"
    enabled: true
  - provider: openrouter
    model: "gpt-4o"
    enabled: true
```
