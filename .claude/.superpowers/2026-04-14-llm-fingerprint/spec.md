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
├── data/
│   └── {provider}__{model}/   # 每个模型一个根目录
│       ├── instruction/
│       │   └── {run_id}.json
│       ├── style_open/
│       ├── coding_frontend/
│       ├── coding_backend/
│       ├── consistency/
│       ├── statistical/
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
    concurrency: 2                 # 该 provider 最大并发请求数

  openrouter:
    base_url: "https://openrouter.ai/api"
    api_key: "${OPENROUTER_API_KEY}"
    concurrency: 2

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
  max_llm_concurrent: 5          # 全局 LLM API 最大并发（约束: sum(provider.concurrency) <= 此值）
  max_retries: 5                 # 单次请求最大重试次数
  retry_intervals: [5, 10, 30, 60]  # 递增重试间隔，超出取最后一个值
  timeout: 60                    # 单次请求超时（秒）
  statistical_samples: 20        # statistical 探针对同一 prompt 的采样次数
  targets:
    - model: "claude-sonnet-4-20250514"
      enabled: true
      baseline_run_id: null      # null 表示使用最早一次成功 run 作为基线
    - model: "gpt-4o"
      enabled: true
      baseline_run_id: null

  # 告警阈值
  thresholds:
    capability_drop_warn: 0.05       # 约束满足率下降 5pp
    capability_drop_critical: 0.15   # 下降 15pp
    similarity_warn: 0.7             # 文本相似度低于 0.7
    similarity_critical: 0.5         # 低于 0.5
    behavior_js_warn: 0.1            # JS 散度超过 0.1
    behavior_js_critical: 0.3        # 超过 0.3
    metadata_length_warn: 0.1        # 长度变化超过 10%
    metadata_length_critical: 0.3    # 超过 30%

  # overall_score 为各维度分数的加权平均
  # 默认权重: capability 0.25, text_similarity 0.25, behavior 0.2, metadata 0.15, statistical 0.15
  # 权重可在配置中覆盖
  weights:
    capability: 0.30
    text_similarity: 0.25
    behavior: 0.20
    metadata: 0.10
    statistical: 0.15

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
- concurrency 在每个 provider 下独立配置，适应不同 provider 的 rate limit
- 约束：sum(provider.concurrency) <= max_llm_concurrent，避免全局 Semaphore 饥饿
- overall_score 为各维度加权平均，权重可配置

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

**第二阶段（设计纳入，实现延后）：**

| 类型 | 探测目标 | 区分度来源 |
|------|----------|-----------|
| probespec | 动态行为谱 | DCT 提取行为谱指纹 |

### 探针数据模型（分层定义）

**简单探针（instruction / statistical）：**

```json
[{
  "id": "instruction_001",
  "type": "instruction",
  "language": "en",
  "prompt": "...",
  "max_tokens": 500,
  "difficulty": "hard",
  "constraints": [
    {"type": "language", "value": "en", "description": "只使用英文回答"},
    {"type": "max_words", "value": 50, "description": "回答不超过50词"},
    {"type": "format", "value": "json", "description": "严格JSON格式"},
    {"type": "no_markdown", "value": true, "description": "不使用markdown标记"},
    {"type": "field_names", "value": ["answer", "confidence"], "description": "JSON字段名必须为answer和confidence"}
  ]
}]
```

**constraint type 定义：**

| type | value 类型 | 检查方法 |
|------|-----------|----------|
| `language` | str ("en"/"zh") | 检测输出中是否包含目标语言字符 |
| `max_words` | int | 统计词数（英文按空格，中文按字符） |
| `format` | str ("json"/"xml") | 尝试解析为对应格式 |
| `no_markdown` | bool | 检测是否包含 `**`、`#`、`` ` `` 等 markdown 符号 |
| `field_names` | list[str] | 解析 JSON 后检查字段名是否匹配 |
| `max_length` | int | 输出字符数 |
| `no_punctuation` | bool | 检测是否包含标点 |
| `conclusion_first` | bool | 检测首句是否为结论性陈述 |

**statistical 探针无 constraints，只有 prompt + max_tokens：**

```json
[{
  "id": "stat_001",
  "type": "statistical",
  "language": "en",
  "prompt": "Write a short paragraph about the benefits of reading.",
  "max_tokens": 300,
  "difficulty": "easy"
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
        self._global_sem = asyncio.Semaphore(config.evaluation.max_llm_concurrent)
        self._provider_sems = {
            name: asyncio.Semaphore(provider.concurrency)
            for name, provider in config.providers.items()
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

正常响应：
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
        "latency_ms": 1234,
        "input_tokens": 45,
        "output_tokens": 89,
        "stop_reason": "end_turn"
      }
    }
  ]
}
```

请求失败时 response 替换为 error：
```json
{
  "probe_id": "instruction_001",
  "request": { "prompt": "...", "temperature": 0, "max_tokens": 500 },
  "error": {
    "type": "timeout",
    "message": "Request timed out after 60s",
    "retries_attempted": 3,
    "last_retry_interval": 30
  }
}
```

分析引擎遇到 error 类结果时跳过该探针的评分，在 detail 中标注 "skipped: N errors"。

### 基线管理机制

- 首次对某模型执行探测时，自动将该次 run 标记为基线（`is_baseline: true`）
- 基线信息存储在模型根目录下的 `baseline.json`：
  ```json
  {
    "current_baseline_run_id": "20260414000003",
    "history": [
      {"run_id": "20260414000003", "set_at": "2026-04-14T00:00:03+08:00", "set_by": "auto"}
    ]
  }
  ```
- `fingerprint baseline --run-id XXX --model XXX` 命令更新 `baseline.json`
- 后续所有分析均与 `current_baseline_run_id` 指向的 run 对比
- 基线不会自动过期，需要用户手动更新（模型版本更新后应手动设置新基线）

### consistency 探针判定逻辑

consistency 探针在同一 run 内对同一组 variants 分别调用 API，然后：
1. 收集所有 variant 的响应文本
2. 如果 `expected_consistency: "same_answer"` → 提取各 variant 回答中的关键答案，检查是否语义一致
3. 计算各 variant 间的文本相似度矩阵
4. 与基线的一致性矩阵对比，检测一致性是否下降
5. 判定方式：先做 variant 间对比（同一 run 内），再做 run 间对比（与基线）

### statistical 探针采样机制

statistical 探针对同一 prompt 执行 `statistical_samples`（默认 20）次调用（temperature > 0）：
- 所有采样结果存储在同一个 `{run_id}.json` 的 results 数组中，通过 `sample_index` 字段区分
- 分析时将所有采样聚合成分布（输出长度分布、token 频率分布），再与基线分布做 KS 检验和 JS 散度

## 6. 分析引擎

### 分析模块与探针类型对应

| 模块 | 负责的探针类型 | 输出 |
|------|---------------|------|
| capability.py | instruction, coding | 约束满足率、代码覆盖率 |
| behavior.py | style_open | 词频/句长/标点/结构特征 |
| similarity.py | style_open, consistency | 文本相似度分数 |
| metadata.py | 所有类型 | 长度/延迟/token 用量变化率 |
| statistical.py | statistical | KS 检验 p-value、JS 散度 |
| probespec.py | probespec（第二阶段） | DCT 行为谱指纹 |

### 分析流程

输入：当前 run JSON + 基线 baseline JSON

对每个探针结果，根据 probe_type 条件执行对应分析：

| 步骤 | 适用的 probe_type | 说明 |
|------|-------------------|------|
| capability.check() | instruction, coding_frontend, coding_backend | 约束满足率 / 代码覆盖率 / 答案正确率 |
| behavior.extract() | style_open | 词频分布、句长分布、标点模式、结构特征 |
| similarity.compare() | style_open, consistency | 与基线文本计算余弦相似度；consistency 还做 variant 间一致性 |
| metadata.compare() | 所有类型 | 输出长度/响应延迟/token 用量变化率 |
| statistical.test() | statistical | KS 检验 + JS 散度 |

对于不匹配的步骤直接跳过，不产生评分。

### 各分析模块的具体算法

#### capability.check() — 能力评分

输入：当前 run 的探针结果 + 基线 run 的同类型探针结果

**instruction 探针：**
1. 对每个探针结果，解析 response.text
2. 按探针定义的约束条件逐条检查（如"只用英文回答"、"不超过50字"、"JSON格式"）
3. 约束满足率 = 满足的约束数 / 总约束数
4. 与基线对比：`capability_drop = baseline_rate - current_rate`
5. 按阈值映射为分数：无下降 → 1.0，下降 N pp → max(0, 1.0 - N * k)

**coding 探针：**
1. 对每个探针结果，提取 response.text 中的代码块
2. 检查 `scoring.must_contain`：每出现一个关键词 +1
3. 检查 `scoring.should_contain`：每出现一个 +0.5
4. 检查 `scoring.forbidden_patterns`：每出现一个 -0.5
5. 检查 `scoring.check_points`：用正则或关键词匹配，每命中一个 +1
6. 加权汇总为覆盖率分数
7. 与基线覆盖率对比，计算下降幅度

#### behavior.extract() — 行为特征提取

输入：当前 run 的 style_open 探针结果 + 基线 run 的同类型探针结果

提取维度：

| 特征 | 提取方法 | 比较方法 |
|------|----------|----------|
| 词频分布 | 分词后统计 top-50 高频词频率 | JS 散度 |
| 句长分布 | 按句号/问号/感叹号分句，统计每句字数 | KS 检验 |
| 标点模式 | 统计各类标点占总字符比例 | 欧氏距离 |
| 列表使用 | 检测是否包含有序/无序列表标记 | 布尔对比 |
| 段落数 | 按空行分段计数 | 绝对差 |
| 类比/比喻 | 检测"like"/"such as"/"就像"等类比关键词 | 频率对比 |
| 犹豫词 | 检测"maybe"/"perhaps"/"可能"/"或许" | 频率对比 |
| 首句模式 | 提取第一句话的结构（陈述/问句/感叹） | 布尔对比 |

行为维度评分 = 各子特征分数的加权平均，JS 散度和 KS 检验是主要判据。

#### similarity.compare() — 文本相似度

输入：当前 run + 基线 run 的 style_open / consistency 探针结果

**style_open 探针：**
1. 对同一探针 ID，取当前文本和基线文本
2. 使用 tf-idf 向量化 + 余弦相似度计算（不依赖外部 embedding 模型，保持零成本）
3. 如果 tf-idf 区分度不够，可选使用 `difflib.SequenceMatcher` 做字符级相似度补充
4. 最终相似度 = 0.7 * tf-idf 余弦 + 0.3 * SequenceMatcher 比率

**consistency 探针：**
1. 同一 run 内：计算所有 variant 对之间的文本相似度，形成相似度矩阵
2. 取矩阵最小值作为"最差一致性"
3. 与基线的一致性矩阵对比：当前最小值 vs 基线最小值
4. 如果 `expected_consistency: "same_answer"`：额外提取各 variant 的答案（取最后一个数字/短句），检查是否相同

#### metadata.compare() — 元数据分析

输入：当前 run + 基线 run 的所有探针结果

对每个探针结果提取元数据：
- `output_length`：response.text 的字符数
- `latency_ms`：API 响应延迟
- `input_tokens` / `output_tokens`：token 用量

比较方式：
- 输出长度变化率 = (current - baseline) / baseline
- 延迟变化率 = (current - baseline) / baseline
- token 用量变化率 = (current - baseline) / baseline

对所有探针的变化率取中位数（比均值更鲁棒），按阈值映射为分数。

#### statistical.test() — 统计检验

输入：当前 run 的 statistical 探针结果（N 个采样）+ 基线 run 的 statistical 探针结果（N 个采样）

1. 对同一探针 ID，收集当前 run 的 N 个采样的输出长度 → 形成长度分布
2. 收集基线 run 的 N 个采样的输出长度 → 形成基线长度分布
3. **KS 检验**：两样本 KS 检验，p-value < 0.05 则分布显著不同
4. **JS 散度**：将输出长度离散化为 25 个桶的直方图，计算 JS 散度
5. 对 token 频率做同样处理：统计 top-100 token 的频率分布，计算 JS 散度
6. 评分 = max(0, 1.0 - JS散度 * k)，KS p-value < 0.05 时额外扣分

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

APScheduler AsyncIOScheduler，与异步执行引擎在同一个 event loop 中运行，避免线程/异步桥接问题。

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

# 启动内置调度器（前台运行，Ctrl+C 优雅停止）
fingerprint serve

# 后台运行（用户可自行搭配 nohup / launchd / systemd）
# 项目不自带 daemon 模式，保持简单
fingerprint serve &

# 设置基线
fingerprint baseline --run-id 20260414000003 --model claude-sonnet-4-20250514
```

serve 模式说明：
- 前台进程，日志输出到 stdout/stderr
- Ctrl+C 触发优雅停止：等待当前 run 完成（最多 timeout 秒），然后退出
- 不使用 PID 文件或锁文件，用户如需 daemon 化可自行搭配系统工具

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

**单模型报告**（`data/{provider}__{model}/report/`）：
- 每次生成报告覆盖写入 `latest.html`，同时按日期保留 `report_{date}_{run_id}.html`
- 报告内容始终包含完整历史趋势（读取该模型所有 run 数据），不仅仅是最新一次
- 概览：评分、探测轮次、时间跨度
- 各维度评分趋势折线图（Chart.js）
- 告警时间线
- 各 probe_type 详细历史表格

**全局汇总报告**（`reports/report_{date}_{run_id}.html`）：
- 所有模型评分对比矩阵
- 同一 run_id 下各模型横向对比
- 全局告警汇总

## 9. 数据目录结构

```
data/
└── {provider}__{model}/
    ├── baseline.json             # 基线指针（指向基线 run_id）
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
    ├── analysis/
    │   └── {run_id}.json
    └── report/
        ├── latest.html
        └── report_{date}_{run_id}.html
```

设计原则：
- 按探测类型建子目录，分析时直接读整个目录获取时间序列
- 同一 run_id 贯穿所有文件，可跨目录关联
- analysis 和 report 在模型根目录下，支持 `fingerprint report .` 就地生成
