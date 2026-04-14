# Quickstart

## 安装

要求 Python >= 3.12。

```bash
# 克隆项目
git clone <repo-url>
cd llm-fingerprint-daily

# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# 安装依赖（运行时 + 开发）
pip install -e ".[dev]"
```

依赖列表：pydantic, httpx, apscheduler, typer, jinja2, scikit-learn, scipy, numpy, pyyaml。

## 配置

```bash
# 复制示例配置
cp config.example.yaml config.yaml

# 设置环境变量（api_key 中的 ${...} 会被自动解析）
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENROUTER_API_KEY="sk-or-..."
```

配置文件说明见 `config.example.yaml`，关键配置项：

| 配置项 | 说明 |
|--------|------|
| `providers` | LLM 服务提供者（base_url, api_key, concurrency） |
| `models` | 模型列表（name, provider, display_name） |
| `evaluation.schedule` | 调度时间（小时列表，如 `[0, 4, 6, 10, 14, 18, 22]`） |
| `evaluation.targets` | 评测目标模型（从 models 中选择，可 enabled: false 跳过） |
| `evaluation.thresholds` | 各维度告警阈值（warn/critical） |
| `evaluation.weights` | 各维度权重（总和必须为 1.0） |

## CLI 用法

CLI 入口为 `fingerprint` 命令（安装后自动注册）。

### fingerprint run — 执行一次评测

```bash
# 对所有已启用的模型和探针类型执行完整评测
fingerprint run

# 只评测指定模型
fingerprint run --model claude-sonnet-4-20250514

# 只运行指定探针类型（逗号分隔）
fingerprint run --type instruction,style_open

# 指定配置文件和数据目录
fingerprint run --config /path/to/config.yaml --data-dir ./data --probe-dir ./probes
```

首次运行会自动将结果设为基线，后续运行与基线对比分析。

输出示例：
```
运行完成: run_id=20260414100003
评测模型: claude-sonnet-4-20250514, gpt-4o
```

### fingerprint report — 生成 HTML 报告

```bash
# 为指定模型目录生成报告（含趋势图和维度详情）
fingerprint report data/anthropic__claude-sonnet-4-20250514/

# 生成全局汇总报告（所有模型横向对比）
fingerprint report --all

# 指定数据目录和配置文件
fingerprint report --data-dir ./data --config config.yaml
```

报告输出为自包含 HTML（内嵌 CSS + Chart.js），双写到 `latest.html` 和归档文件。

### fingerprint history — 查看历史评分

```bash
# 查看指定模型目录的历史趋势
fingerprint history data/anthropic__claude-sonnet-4-20250514/

# 查看整个 data 目录下所有模型的历史
fingerprint history .
```

输出示例：
```
run_id             model                 score
------------------------------------------------
20260414000003     claude-sonnet-4        100.00%
20260414100003     claude-sonnet-4         92.50%
20260414140003     claude-sonnet-4         87.30%
```

### fingerprint serve — 启动定时调度

```bash
# 前台运行，按 config 中的 schedule 定时执行评测
fingerprint serve

# 后台运行（搭配 nohup / launchd / systemd）
fingerprint serve &
```

- 按 `schedule` 配置在每小时 +3 分钟执行（如 00:03, 04:03, 06:03...）
- 同一时刻最多一个 run 在执行（`max_instances=1`）
- `Ctrl+C` 优雅停止，等待当前 run 完成

可选参数：`--config`, `--data-dir`, `--probe-dir`。

### fingerprint baseline — 手动设置基线

```bash
# 将指定 run 设为某模型的基线
fingerprint baseline --run-id 20260414000003 --model claude-sonnet-4-20250514

# 指定数据目录
fingerprint baseline --run-id 20260414000003 --model claude-sonnet-4-20250514 --data-dir ./data
```

模型版本更新后建议手动设新基线，基线不会自动过期。

## 数据目录结构

```
data/
└── {provider}__{model}/
    ├── baseline.json           # 基线指针
    ├── instruction/
    │   └── {run_id}.json       # 探测结果
    ├── style_open/
    ├── coding_frontend/
    ├── coding_backend/
    ├── consistency/
    ├── statistical/
    ├── analysis/
    │   └── {run_id}.json       # 分析结果
    └── report/
        ├── latest.html         # 最新报告（覆盖）
        └── report_{date}_{run_id}.html  # 归档报告
```

## 探针类型

| 类型 | 文件 | 探测目标 |
|------|------|----------|
| instruction | `probes/instruction.json` | 多约束指令遵循精确度 |
| style_open | `probes/style_open.json` | 开放性问题风格特征 |
| coding_frontend | `probes/coding_frontend.json` | 前端代码质量 |
| coding_backend | `probes/coding_backend.json` | 后端代码质量 |
| consistency | `probes/consistency.json` | 同义变体语义一致性 |
| statistical | `probes/statistical.json` | 输出分布统计特征 |

## 分析维度

| 维度 | 权重（默认） | 说明 |
|------|-------------|------|
| capability | 0.30 | 约束满足率 / 代码覆盖率 |
| text_similarity | 0.25 | tf-idf + SequenceMatcher 文本相似度 |
| behavior | 0.20 | 词频 JS 散度 + 句长 KS 检验 |
| statistical | 0.15 | KS 检验 + JS 散度 |
| metadata | 0.10 | 输出长度 / 延迟 / token 用量变化率 |
