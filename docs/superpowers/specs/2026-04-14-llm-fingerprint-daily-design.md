# LLM Fingerprint Daily - 设计文档

> 日期：2026-04-14
> 状态：已确认

## 1. 项目概述

定时（0/4/6/10/14/18/22 点）对配置的 LLM API 进行黑盒指纹探测，判断模型是否被替换、能力是否波动。

核心约束：
- 个人项目，低成本
- 黑盒探针（仅 API 输入输出）
- Anthropic Messages API 格式
- 中英混合探针

## 2. 项目结构

```
llm-fingerprint-daily/
├── config.yaml                # 全局配置入口
├── probes/                    # 探针定义（JSON）
│   ├── instruction.json       # 指令遵循探针
│   ├── style_open.json        # 开放性风格探针
│   ├── coding_frontend.json   # 前端代码探针
│   ├── coding_backend.json    # 后端代码探针
│   ├── consistency.json       # 语义一致性探针
│   ├── statistical.json       # 统计分布探针
│   └── logprobs.json          # 灰盒 logprobs 探针
├── data/
│   └── {provider}__{model}/   # 每个模型一个根目录
│       ├── instruction/
│       │   └── {run_id}.json
│       ├── style_open/
│       ├── coding_frontend/
│       ├── coding_backend/
│       ├── consistency/
│       ├── statistical/
│       ├── logprobs/
│       ├── analysis/
│       │   └── {run_id}.json
│       └── report/
│           ├── {date}.html
│           └── latest.html
├── reports/                   # 全局汇总报告
│   └── report_{date}.html
├── src/
│   ├── __init__.py
│   ├── main.py                # CLI 入口（typer）
│   ├── config/                # 配置层
│   │   ├── __init__.py
│   │   ├── loader.py          # 配置加载与校验
│   │   └── schema.py          # 配置数据模型（pydantic）
│   ├── scheduler/             # 调度层
│   │   ├── __init__.py
│   │   └── core.py            # APScheduler 封装
│   ├── probe/                 # 探针管理层
│   │   ├── __init__.py
│   │   ├── loader.py          # 探针加载
│   │   └── schema.py          # 探针数据模型
│   ├── engine/                # 执行引擎
│   │   ├── __init__.py
│   │   ├── orchestrator.py    # RunOrchestrator（唯一调度入口）
│   │   ├── provider_runner.py # ProviderRunner
│   │   ├── target_runner.py   # TargetRunner
│   │   ├── llm_gateway.py     # LLMGateway（唯一 API 调用出口）
│   │   └── storage.py         # Storage（唯一文件写入出口）
│   ├── analysis/              # 分析层
│   │   ├── __init__.py
│   │   ├── similarity.py      # 文本相似度
│   │   ├── capability.py      # 能力评分
│   │   ├── behavior.py        # 行为模式分析
│   │   ├── metadata.py        # 元数据分析
│   │   ├── statistical.py     # 统计检验（KS/KL）
│   │   ├── logprobs.py        # logprobs 对比
│   │   └── probespec.py       # ProbeSpec 行为谱（第二阶段）
│   └── report/                # 报告层
│       ├── __init__.py
│       └── generator.py       # HTML 报告生成
├── templates/
│   └── report.html            # Jinja2 报告模板
├── pyproject.toml
└── README.md
```

## 3. 配置模型

```yaml
# Provider 配置
providers:
  anthropic:
    base_url: "https://api.anthropic.com"
    api_key: "${ANTHROPIC_API_KEY}"
    default_headers: {}

  openrouter:
    base_url: "https://openrouter.ai/api"
    api_key: "${OPENROUTER_API_KEY}"

# 模型列表
models:
  - name: "claude-sonnet-4-20250514"
    provider: anthropic
    display_name: "Claude Sonnet 4"
  - name: "gpt-4o"
    provider: openrouter
    display_name: "GPT-4o"

# 评测配置
evaluation:
  schedule: [0, 4, 6, 10, 14, 18, 22]
  timezone: "Asia/Shanghai"
  probe_types:
    - instruction
    - style_open
    - coding_frontend
    - coding_backend
    - consistency
    - statistical
    - logprobs
  concurrency: 2                 # 每 provider 最大并发
  max_llm_concurrent: 5          # 全局 LLM API 最大并发
  max_retries: 5                 # 单次请求最大重试次数
  retry_intervals: [5, 10, 30, 60]  # 递增重试间隔，超出取最后一个值
  timeout: 60                    # 单次请求超时（秒）
  targets:
    - model: "claude-sonnet-4-20250514"
      enabled: true
    - model: "gpt-4o"
      enabled: true

# 报告配置
report:
  output_dir: "./reports"
  auto_open: false
```

设计要点：
- providers 和 models 分离，一个 provider 可复用 base_url/api_key
- evaluation.targets 和 models 解耦，可注册多模型但只评测部分
- api_key 支持 `${ENV_VAR}` 环境变量引用
- retry_intervals[i] 为第 i 次重试的等待秒数，超出数组长度取最后一个值

## 4. 探针设计

### 探针 vs Benchmark

探针追求"模型间差异性"，用少量 prompt（3-50 条）让不同模型产生显著不同的响应。Benchmark 追求"任务有效性"，用大量题目评估能力水平。两者目标不同。

### 探针类型与优先级

**第一阶段（核心）：**

| 类型 | 文件 | 探测目标 | 区分度来源 |
|------|------|----------|-----------|
| instruction | instruction.json | 多约束指令遵循精确度 | 约束满足率变化 |
| style_open | style_open.json | 开放性问题风格特征 | 词频/句长/标点/结构漂移 |
| coding_frontend | coding_frontend.json | 前端代码质量 | 代码风格/边界处理差异 |
| coding_backend | coding_backend.json | 后端代码质量 | 代码风格/边界处理差异 |
| consistency | consistency.json | 同义变体语义一致性 | 跨模态变体的一致性 |
| statistical | statistical.json | 输出分布特征 | KS 检验/KL 散度 |
| logprobs | logprobs.json | token 概率分布 | 概率分布漂移 |

**第二阶段（设计纳入，实现延后）：**

| 类型 | 探测目标 | 区分度来源 |
|------|----------|-----------|
| probespec | 动态行为谱 | DCT 提取行为谱指纹 |

### 探针数据模型（分层定义）

**简单探针（instruction / statistical / logprobs）：**

```json
[{
  "id": "instruction_001",
  "type": "instruction",
  "language": "en",
  "prompt": "...",
  "max_tokens": 500,
  "difficulty": "hard"
}]
```

**复杂探针（coding）：**

```json
[{
  "id": "coding_fe_001",
  "type": "coding_frontend",
  "language": "en",
  "prompt": "...",
  "max_tokens": 2048,
  "scoring": {
    "must_contain": ["setTimeout", "clearTimeout"],
    "should_contain": ["TypeScript generic"],
    "forbidden_patterns": ["any", "// TODO"],
    "check_points": ["handles rapid calls", "preserves this context"]
  }
}]
```

**风格探针（style_open）：**

```json
[{
  "id": "style_en_001",
  "type": "style_open",
  "language": "en",
  "prompt": "Explain why the sky is blue to a curious 8-year-old.",
  "max_tokens": 500,
  "analysis": {
    "extract": ["sentence_count", "avg_word_length", "punctuation_ratio",
                 "list_usage", "analogy_usage", "hedge_words"],
    "baseline_compare": "full_text"
  }
}]
```

**一致性探针（consistency）：**

```json
[{
  "id": "consistency_001",
  "type": "consistency",
  "language": "mixed",
  "variants": [
    {"label": "natural_language", "prompt": "..."},
    {"label": "code_description", "prompt": "..."},
    {"label": "mathematical", "prompt": "..."}
  ],
  "expected_consistency": "same_answer",
  "max_tokens": 500
}]
```

### 探针设计方法论

探针区分度的核心来源：

1. **多步推理链**：5-10 步连续推理，中间任何一步出错都导致最终错误
2. **多约束叠加**：同时施加 4-5 个约束，检查满足率
3. **代码质量微观特征**：边界处理、错误处理、命名风格
4. **已知陷阱题**：不同模型/版本的犯错模式不同
5. **统计分布**：不需要精心设计 prompt，靠多次采样的分布漂移检测
6. **灰盒 logprobs**：token 概率分布的变化比文本变化更敏感

## 5. 执行引擎

### 四层收口架构

```
RunOrchestrator          唯一调度入口：编排完整 run
  └→ ProviderRunner      per-provider：分组 + provider 级并发
       └→ TargetRunner   per-target：probe_type 顺序执行
            └→ LLMGateway 唯一 API 出口：两层 Semaphore + 重试
```

**收口原则：**
- LLMGateway 是所有 LLM API 调用的唯一出口，禁止绕过
- Storage 是所有文件写入的唯一出口
- RunOrchestrator 是所有 run 的唯一调度入口

### LLMGateway 两层 Semaphore

```python
class LLMGateway:
    def __init__(self, config):
        self._global_sem = asyncio.Semaphore(config.max_llm_concurrent)
        self._provider_sems = {
            name: asyncio.Semaphore(p.concurrency)
            for name, p in config.providers.items()
        }

    async def call(self, provider, model, messages, **kwargs):
        async with self._global_sem:           # 全局上限
            async with self._provider_sems[provider]:  # provider 上限
                return await self._do_request(...)
```

### run_id 设计

run_id 在探测启动时统一生成（`%Y%m%d%H%M%S`），贯穿本次 run 的所有文件：
- `data/{provider}__{model}/instruction/{run_id}.json`
- `data/{provider}__{model}/style_open/{run_id}.json`
- `data/{provider}__{model}/analysis/{run_id}.json`

### 单次探测结果 JSON 结构

```json
{
  "meta": {
    "run_id": "20260414100003",
    "model": "claude-sonnet-4-20250514",
    "provider": "anthropic",
    "timestamp": "2026-04-14T10:00:03+08:00",
    "is_baseline": false,
    "baseline_run_id": "20260414000003",
    "probe_type": "instruction"
  },
  "results": [
    {
      "probe_id": "instruction_001",
      "request": {
        "prompt": "...",
        "temperature": 0,
        "max_tokens": 500
      },
      "response": {
        "text": "...",
        "logprobs": [],
        "latency_ms": 1234,
        "input_tokens": 45,
        "output_tokens": 89,
        "stop_reason": "end_turn"
      }
    }
  ]
}
```

## 6. 分析引擎

### 分析模块与探针类型对应

| 模块 | 负责的探针类型 | 输出 |
|------|---------------|------|
| capability.py | instruction, coding | 约束满足率、代码覆盖率 |
| behavior.py | style_open | 词频/句长/标点/结构特征 |
| similarity.py | style_open, consistency | 文本相似度分数 |
| metadata.py | 所有类型 | 长度/延迟/token 用量变化率 |
| statistical.py | statistical | KS 检验 p-value、JS 散度 |
| logprobs.py | logprobs | token 概率 KL 散度 |
| probespec.py | probespec（第二阶段） | DCT 行为谱指纹 |

### 分析流程

输入：当前 run JSON + 基线 baseline JSON

对每个探针结果：
1. capability.check() — 检查约束满足率 / 代码覆盖率 / 答案正确率
2. behavior.extract() — 提取词频分布、句长分布、标点模式、结构特征
3. similarity.compare() — 与基线文本计算余弦相似度
4. metadata.compare() — 输出长度/响应延迟/token 用量变化率
5. statistical.test() — KS 检验 + JS 散度（仅 statistical 类型）
6. logprobs.compare() — token 概率分布 KL 散度（仅 logprobs 类型）

### 综合评分与告警

每个模型每次探测产出分析 JSON：

```json
{
  "model": "claude-sonnet-4-20250514",
  "run_id": "20260414100003",
  "baseline_run_id": "20260414000003",
  "overall_score": 0.87,
  "alert_level": "normal",
  "dimensions": {
    "capability": {"score": 0.92, "detail": "..."},
    "text_similarity": {"score": 0.78, "detail": "..."},
    "behavior": {"score": 0.91, "detail": "..."},
    "metadata": {"score": 0.95, "detail": "..."},
    "statistical": {"score": 0.84, "detail": "..."}
  },
  "alerts": []
}
```

**告警阈值（可配置）：**

| 维度 | 正常 | 警告 (WARN) | 严重 (CRITICAL) |
|------|------|------------|----------------|
| capability 约束满足率 | 下降 < 5pp | 下降 5-15pp | 下降 > 15pp |
| text_similarity | > 0.7 | 0.5-0.7 | < 0.5 |
| behavior JS 散度 | < 0.1 | 0.1-0.3 | > 0.3 |
| metadata 长度变化 | < 10% | 10-30% | > 30% |

## 7. 调度器

### 技术选型

APScheduler BackgroundScheduler，进程内运行。

### 并发控制（三层）

| 层级 | 控制方式 | 作用 |
|------|----------|------|
| Run 级 | APScheduler max_instances=1, coalesce=True | 同一时刻最多一个 run |
| Provider 级 | asyncio.Semaphore(concurrency) | 每 provider 并发上限 |
| LLM 调用级 | LLMGateway 两层 Semaphore | 全局 + provider 双重控制 |

### CLI 命令

```bash
# 执行一轮完整探测
fingerprint run

# 只探测特定模型
fingerprint run --model claude-sonnet-4-20250514

# 只运行特定探测类型
fingerprint run --type instruction,style_open

# 为特定模型生成报告
fingerprint report data/anthropic__claude-sonnet-4-20250514/

# 生成全局汇总报告
fingerprint report --all

# 查看某个模型的历史趋势
fingerprint history data/anthropic__claude-sonnet-4-20250514/

# 启动内置调度器
fingerprint serve

# 设置基线
fingerprint baseline --run-id 20260414000003 --model claude-sonnet-4-20250514
```

### 异常处理

- 探测失败：记录日志，不影响下一轮
- 进程中断：misfire_grace_time=300，5 分钟内恢复则补执行
- 轮次重叠：max_instances=1 跳过

## 8. 报告层

### 技术选型

- 模板引擎：Jinja2
- 图表：Chart.js 内嵌（~200KB）
- 样式：内嵌 CSS
- 产出：单文件自包含 HTML

### 报告类型

**单模型报告**（`data/{provider}__{model}/report/{date}.html`）：
- 概览：评分、探测轮次、时间跨度
- 各维度评分趋势折线图（Chart.js）
- 告警时间线
- 各 probe_type 详细历史表格

**全局汇总报告**（`reports/report_{date}.html`）：
- 所有模型评分对比矩阵
- 同一 run_id 下各模型横向对比
- 全局告警汇总

## 9. 数据目录结构

```
data/
└── {provider}__{model}/
    ├── instruction/
    │   └── {run_id}.json
    ├── style_open/
    │   └── {run_id}.json
    ├── coding_frontend/
    │   └── {run_id}.json
    ├── coding_backend/
    │   └── {run_id}.json
    ├── consistency/
    │   └── {run_id}.json
    ├── statistical/
    │   └── {run_id}.json
    ├── logprobs/
    │   └── {run_id}.json
    ├── analysis/
    │   └── {run_id}.json
    └── report/
        ├── {date}.html
        └── latest.html
```

设计原则：
- 按探测类型建子目录，分析时直接读整个目录获取时间序列
- 同一 run_id 贯穿所有文件，可跨目录关联
- analysis 和 report 在模型根目录下，支持 `fingerprint report .` 就地生成
