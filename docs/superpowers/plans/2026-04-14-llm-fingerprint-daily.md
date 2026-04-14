# LLM Fingerprint Daily 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个定时黑盒 LLM 指纹探测系统，通过多维度探针检测 API 背后模型是否被替换或能力波动。

**Architecture:** 分层模块化：配置层 → 探针管理层 → 执行引擎（四层收口）→ 分析引擎 → 报告层。调度器使用 APScheduler AsyncIOScheduler，CLI 使用 typer。

**Tech Stack:** Python 3.12+, pydantic, httpx (async), APScheduler, typer, Jinja2, scikit-learn (tf-idf), scipy (KS test), numpy

**Spec:** `docs/superpowers/specs/2026-04-14-llm-fingerprint-daily-design.md`

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pyproject.toml` | 项目配置 + 依赖 |
| `config.yaml` | 示例配置文件 |
| `probes/*.json` | 各类型探针数据 |
| `src/config/schema.py` | 配置数据模型 (pydantic) |
| `src/config/loader.py` | 配置加载 + 环境变量解析 |
| `src/probe/schema.py` | 探针数据模型 |
| `src/probe/loader.py` | 探针文件加载 |
| `src/engine/storage.py` | 唯一文件写入出口 |
| `src/engine/llm_gateway.py` | 唯一 LLM API 调用出口 |
| `src/engine/target_runner.py` | 单 target 执行 |
| `src/engine/provider_runner.py` | 单 provider 执行 |
| `src/engine/orchestrator.py` | 唯一 run 调度入口 |
| `src/analysis/capability.py` | 能力评分 |
| `src/analysis/behavior.py` | 行为特征提取 |
| `src/analysis/similarity.py` | 文本相似度 |
| `src/analysis/metadata.py` | 元数据分析 |
| `src/analysis/statistical.py` | 统计检验 |
| `src/analysis/analyzer.py` | 综合分析器（汇总各模块） |
| `src/scheduler/core.py` | APScheduler 封装 |
| `src/report/generator.py` | HTML 报告生成 |
| `templates/report.html` | Jinja2 报告模板 |
| `src/main.py` | CLI 入口 |
| `tests/` | 测试目录 |

---

## Phase 1: 基础设施

### Task 1: 项目骨架

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `.gitignore`
- Create: `config.example.yaml`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "llm-fingerprint-daily"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "httpx>=0.27",
    "apscheduler>=3.10",
    "typer>=0.12",
    "jinja2>=3.1",
    "scikit-learn>=1.4",
    "scipy>=1.12",
    "numpy>=1.26",
    "pyyaml>=6.0",
]

[project.scripts]
fingerprint = "src.main:app"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov"]
```

- [ ] **Step 2: 创建目录结构和空 __init__.py**

```bash
mkdir -p src/config src/probe src/engine src/analysis src/scheduler src/report tests probes templates data
touch src/__init__.py src/config/__init__.py src/probe/__init__.py src/engine/__init__.py src/analysis/__init__.py src/scheduler/__init__.py src/report/__init__.py
touch tests/__init__.py
```

- [ ] **Step 3: 创建 .gitignore**

```
__pycache__/
*.pyc
.env
data/
.venv/
*.egg-info/
```

- [ ] **Step 4: 创建 config.example.yaml**（从 spec 第 3 节的完整配置）

- [ ] **Step 5: 安装依赖并提交**

```bash
pip install -e ".[dev]"
git add -A && git commit -m "chore: init project skeleton with pyproject.toml"
```

---

### Task 2: 配置数据模型

**Files:**
- Create: `src/config/schema.py`
- Test: `tests/test_config_schema.py`

- [ ] **Step 1: 写测试 — 配置模型能正确解析完整配置**

```python
# tests/test_config_schema.py
import pytest
from src.config.schema import AppConfig, ProviderConfig, EvaluationConfig

def test_parse_minimal_config():
    config = AppConfig(
        providers={"test": ProviderConfig(
            base_url="https://api.test.com", api_key="key123", concurrency=2
        )},
        models=[{"name": "model-a", "provider": "test", "display_name": "Model A"}],
        evaluation=EvaluationConfig(
            schedule=[0, 12],
            probe_types=["instruction"],
            max_llm_concurrent=3,
            targets=[{"model": "model-a", "enabled": True}],
        ),
    )
    assert config.providers["test"].concurrency == 2
    assert config.evaluation.schedule == [0, 12]
    assert len(config.evaluation.targets) == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_config_schema.py -v
```

- [ ] **Step 3: 实现 schema.py**

用 pydantic BaseModel 定义：`ProviderConfig`, `ModelEntry`, `TargetEntry`, `ThresholdsConfig`, `WeightsConfig`, `EvaluationConfig`, `ReportConfig`, `AppConfig`。关键字段：
- `api_key` 支持 `${ENV_VAR}` 格式（在 loader 中解析，schema 中为 str）
- `retry_intervals: list[float]`
- `concurrency: int` 在 ProviderConfig 中
- `max_llm_concurrent: int` 在 EvaluationConfig 中

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: 补充边界测试 — retry_intervals 超出取最后一个值、权重之和为 1.0 的校验**

- [ ] **Step 6: 提交**

---

### Task 3: 配置加载

**Files:**
- Create: `src/config/loader.py`
- Test: `tests/test_config_loader.py`

- [ ] **Step 1: 写测试 — 加载 YAML 并解析环境变量**

```python
def test_load_config_resolves_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_API_KEY", "sk-123")
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text('''
providers:
  test:
    base_url: "https://api.test.com"
    api_key: "${TEST_API_KEY}"
    concurrency: 2
models: []
evaluation:
  schedule: [0]
  probe_types: []
  max_llm_concurrent: 2
  targets: []
report:
  output_dir: "./reports"
''')
    config = load_config(str(config_yaml))
    assert config.providers["test"].api_key == "sk-123"
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 loader.py** — `load_config(path) -> AppConfig`：读 YAML → 解析 `${ENV}` → pydantic 校验

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: 提交**

---

### Task 4: 探针数据模型 + 加载

**Files:**
- Create: `src/probe/schema.py`
- Create: `src/probe/loader.py`
- Test: `tests/test_probe_loader.py`

- [ ] **Step 1: 写测试 — 加载各类型探针 JSON**

测试覆盖 4 种探针模型：简单探针（instruction/statistical）、coding 探针（含 scoring）、style 探针（含 analysis）、consistency 探针（含 variants）。

- [ ] **Step 2: 实现探针 schema** — 用 tagged union 或 probe_type 字段区分不同探针类型的 pydantic 模型

- [ ] **Step 3: 实现 loader.py** — `load_probes(probe_dir, probe_types: list[str]) -> dict[str, list[Probe]]`：按 probe_types 过滤加载

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: 提交**

---

## Phase 2: 执行引擎

### Task 5: 存储层

**Files:**
- Create: `src/engine/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 写测试 — 保存探测结果 JSON + 基线管理**

```python
async def test_save_run_result(tmp_path):
    storage = Storage(base_dir=tmp_path)
    await storage.save_run("provider__model", "instruction", "20260414100003", data)
    path = tmp_path / "provider__model" / "instruction" / "20260414100003.json"
    assert path.exists()

async def test_baseline_management(tmp_path):
    storage = Storage(base_dir=tmp_path)
    await storage.set_baseline("provider__model", "20260414100003", set_by="auto")
    baseline = await storage.get_baseline("provider__model")
    assert baseline == "20260414100003"
```

- [ ] **Step 2: 实现 storage.py** — 核心方法：
  - `save_run(model_dir, probe_type, run_id, data)` — 写入 JSON
  - `load_run(model_dir, probe_type, run_id)` — 读取 JSON
  - `list_runs(model_dir, probe_type)` — 按时间排序列出所有 run_id
  - `set_baseline / get_baseline` — 操作 baseline.json
  - `save_analysis(model_dir, run_id, data)` — 写入 analysis/

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 6: LLM Gateway

**Files:**
- Create: `src/engine/llm_gateway.py`
- Test: `tests/test_llm_gateway.py`

- [ ] **Step 1: 写测试 — 用 httpx mock 测试两层 Semaphore + 重试逻辑**

```python
async def test_retry_on_timeout():
    call_count = 0
    async def mock_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("timeout")
        return MockResponse(text="ok", status_code=200)

    gateway = LLMGateway(config)
    result = await gateway.call("test", "model-a", messages)
    assert call_count == 3
    assert result.text == "ok"
```

- [ ] **Step 2: 实现 llm_gateway.py** — 核心逻辑：
  - 两层 Semaphore（全局 + provider）
  - Anthropic Messages API 请求构造（`/v1/messages`）
  - retry_intervals 递增重试
  - 超时控制
  - 返回 `RawResponse` 数据类（text, latency_ms, input_tokens, output_tokens, stop_reason）

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 补充测试 — 并发控制验证（全局 Semaphore 限流）**

- [ ] **Step 5: 提交**

---

### Task 7: Target Runner

**Files:**
- Create: `src/engine/target_runner.py`
- Test: `tests/test_target_runner.py`

- [ ] **Step 1: 写测试 — mock LLMGateway，验证对每种 probe_type 的调用和结果存储**

```python
async def test_run_instruction_probes(tmp_path):
    gateway = MockGateway()
    storage = Storage(base_dir=tmp_path)
    runner = TargetRunner(gateway, storage)
    result = await runner.run("test__model-a", "instruction", probes, run_id="20260414100003")
    assert result.meta.probe_type == "instruction"
    assert len(result.results) == len(probes)
```

- [ ] **Step 2: 实现 target_runner.py** — 对单个 target 的单个 probe_type 执行：
  - 加载探针
  - 对每个探针调用 LLMGateway.call()
  - consistency 探针：对每个 variant 分别调用
  - statistical 探针：对同一 prompt 调用 N 次
  - 收集结果 → 通过 Storage 保存

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 8: Provider Runner + Orchestrator

**Files:**
- Create: `src/engine/provider_runner.py`
- Create: `src/engine/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: 写测试 — 验证 run_id 统一生成 + 多 provider 并行**

- [ ] **Step 2: 实现 provider_runner.py** — 对单个 provider 下的所有 target 执行，用 provider 级 Semaphore 控制并发

- [ ] **Step 3: 实现 orchestrator.py** — 唯一 run 入口：
  - `async run(config, model_filter=None, type_filter=None) -> str` 返回 run_id
  - 生成 run_id
  - 按 provider 分组 targets
  - `asyncio.gather(*[provider_runner.run() for each provider])`
  - 首次 run 自动设置基线

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: 提交**

---

## Phase 3: 分析层

### Task 9: Capability 分析

**Files:**
- Create: `src/analysis/capability.py`
- Test: `tests/test_capability.py`

- [ ] **Step 1: 写测试 — instruction 约束满足率 + coding 覆盖率**

- [ ] **Step 2: 实现 capability.py**
  - `check_instruction(probe_results, probe_defs) -> float` — 检查约束满足率
  - `check_coding(probe_results, probe_defs) -> float` — 检查 must_contain/should_contain/forbidden/check_points
  - `compare(current_rate, baseline_rate, thresholds) -> DimensionScore`

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 10: Behavior 分析

**Files:**
- Create: `src/analysis/behavior.py`
- Test: `tests/test_behavior.py`

- [ ] **Step 1: 写测试 — 词频 JS 散度 + 句长 KS 检验**

- [ ] **Step 2: 实现 behavior.py**
  - `extract_features(text) -> BehaviorFeatures` — 词频/句长/标点/列表/段落数/类比/犹豫词
  - `compare(current_features, baseline_features) -> DimensionScore`
  - JS 散度用 scipy.spatial.distance.jensenshannon
  - KS 检验用 scipy.stats.ks_2samp

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 11: Similarity 分析

**Files:**
- Create: `src/analysis/similarity.py`
- Test: `tests/test_similarity.py`

- [ ] **Step 1: 写测试 — tf-idf 相似度 + SequenceMatcher 混合评分**

- [ ] **Step 2: 实现 similarity.py**
  - `compare_texts(current, baseline) -> float` — 0.7 * tf-idf cosine + 0.3 * SequenceMatcher
  - `compare_consistency(variant_results, baseline_variant_results) -> DimensionScore`
  - 用 sklearn TfidfVectorizer 做向量化

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 12: Metadata 分析

**Files:**
- Create: `src/analysis/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: 写测试 — 输出长度/延迟变化率取中位数**

- [ ] **Step 2: 实现 metadata.py**
  - `compare(current_results, baseline_results) -> DimensionScore`
  - 提取 output_length, latency_ms, input_tokens, output_tokens
  - 变化率取中位数
  - 按阈值映射分数

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 13: Statistical 分析

**Files:**
- Create: `src/analysis/statistical.py`
- Test: `tests/test_statistical.py`

- [ ] **Step 1: 写测试 — KS 检验 + JS 散度**

- [ ] **Step 2: 实现 statistical.py**
  - `test(current_samples, baseline_samples) -> DimensionScore`
  - 输出长度分布：KS 检验 + 25 桶直方图 JS 散度
  - token 频率分布：top-100 token 频率 JS 散度

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 14: 综合分析器

**Files:**
- Create: `src/analysis/analyzer.py`
- Test: `tests/test_analyzer.py`

- [ ] **Step 1: 写测试 — 各维度汇总 + 告警生成 + overall_score 加权平均**

```python
def test_overall_score_is_weighted_average():
    dimensions = {
        "capability": DimensionScore(score=0.9),
        "text_similarity": DimensionScore(score=0.8),
        "behavior": DimensionScore(score=0.95),
        "metadata": DimensionScore(score=1.0),
        "statistical": DimensionScore(score=0.85),
    }
    result = compute_overall(dimensions, weights)
    assert abs(result.overall_score - expected) < 0.01

def test_alert_generation():
    # capability 下降超过 warn 阈值 → 生成 WARN alert
    pass
```

- [ ] **Step 2: 实现 analyzer.py**
  - `analyze(current_run, baseline_run, config) -> AnalysisResult`
  - 按 probe_type 分发到对应分析模块
  - 加权汇总 overall_score
  - 按阈值生成 alerts

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

## Phase 4: 上层

### Task 15: 调度器

**Files:**
- Create: `src/scheduler/core.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 写测试 — 验证 cron 任务注册 + max_instances**

- [ ] **Step 2: 实现 core.py**
  - `FingerprintScheduler` 封装 AsyncIOScheduler
  - 按 schedule 配置注册 cron 任务（避开整点，+3 分钟）
  - max_instances=1, coalesce=True, misfire_grace_time=300
  - `start()` / `shutdown()` 方法

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 16: 报告层

**Files:**
- Create: `templates/report.html`
- Create: `src/report/generator.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: 写测试 — 验证 HTML 输出包含关键内容**

```python
def test_single_model_report_contains_charts(tmp_path):
    generator = ReportGenerator()
    html = generator.generate_model_report(model_dir, analysis_results)
    assert "Chart.js" in html
    assert "overall_score" in html
```

- [ ] **Step 2: 实现 report.html Jinja2 模板** — 内嵌 CSS + Chart.js，包含：
  - 概览区（overall_score + alert_level）
  - 各维度趋势折线图（Chart.js line chart）
  - 告警时间线
  - probe_type 详细历史表格

- [ ] **Step 3: 实现 generator.py**
  - `generate_model_report(model_dir, all_analysis) -> str` — 单模型报告
  - `generate_global_report(model_dirs) -> str` — 全局报告
  - 读取 model_dir 下所有 analysis/*.json 组织数据

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: 提交**

---

### Task 17: CLI 入口

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写测试 — CLI 子命令注册验证**

- [ ] **Step 2: 实现 main.py** — typer app：
  - `fingerprint run [--model] [--type]` — 调用 Orchestrator
  - `fingerprint report [path] [--all]` — 调用 ReportGenerator
  - `fingerprint history [path]` — 读取分析历史并打印摘要
  - `fingerprint serve` — 启动 Scheduler
  - `fingerprint baseline --run-id --model` — 更新基线

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: 提交**

---

### Task 18: 探针数据文件

**Files:**
- Create: `probes/instruction.json`
- Create: `probes/style_open.json`
- Create: `probes/coding_frontend.json`
- Create: `probes/coding_backend.json`
- Create: `probes/consistency.json`
- Create: `probes/statistical.json`

- [ ] **Step 1: 编写 instruction.json** — 8-10 条多约束指令遵循探针，difficulty hard 为主

- [ ] **Step 2: 编写 style_open.json** — 中英各 5 条开放性问题（如"解释量子计算"/"Explain why the sky is blue"），含 analysis 定义

- [ ] **Step 3: 编写 coding_frontend.json + coding_backend.json** — 各 5-8 条代码题，含 scoring 定义（must_contain/check_points 等）

- [ ] **Step 4: 编写 consistency.json** — 5 组同义变体（自然语言/代码描述/数学表达），expected_consistency: "same_answer"

- [ ] **Step 5: 编写 statistical.json** — 3-5 条通用 prompt，用于多次采样分布对比

- [ ] **Step 6: 验证所有 JSON 可被 probe loader 正确加载**

- [ ] **Step 7: 提交**

---

### Task 19: 端到端集成测试

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: 写测试 — mock API，完整 run → analyze → report 流程**

```python
async def test_full_pipeline(tmp_path):
    # 用 mock gateway 模拟 API 响应
    # 1. 首次 run → 自动设置基线
    # 2. 第二次 run → 与基线对比分析
    # 3. 生成报告 → 验证 HTML 输出
    pass
```

- [ ] **Step 2: 运行测试确认通过**

- [ ] **Step 3: 修复发现的问题**

- [ ] **Step 4: 提交**
