# 分析管线修复与流水线集成设计

日期: 2026-04-14

## 背景

系统跑完第一轮真实评测后，分析报告暴露出三个问题：

1. **statistical=0（bug）** — baseline 部分缺失时维度误报 critical
2. **capability 用 metadata 代理** — 已有约束检查代码但 analyze() 没有传入 probe_defs
3. **text_similarity=37%** — style_open 开放性问题逐字比对不合理

此外，CLI 流程断裂：`fingerprint run` 只执行探针，分析和报告需要手动触发。

## 方案选择

选择了方案 C：修复三个问题 + 将分析集成到 `fingerprint run` 流程。

理由：方案 A（只修 bug）没有解决流水线断裂；方案 B（按 probe_type 重构 scorer）改动过大，当前 6→5 的映射关系稳定，不值得重写。

## 修改范围

仅涉及两个核心文件的改动：
- `src/analysis/analyzer.py` — 问题 1/2/3
- `src/engine/orchestrator.py` — 流水线串联

子模块（behavior/similarity/statistical/metadata/capability）不需要改动。

## 设计详情

### 1. baseline 部分缺失 → neutral

**根因：** `_compute_dimension` 只判断了全局 `no_baseline`，没处理单个 probe_type 在 baseline 中缺失的情况。子模块（如 `statistical.py`）在单侧为空时返回 score=0, alert=critical。

**修改：** `_compute_dimension` 入口增加判断——如果 `base_results` 为空，返回 `_NO_BASELINE`（score=1.0, alert=normal）。

```
_compute_dimension 入口：
  如果 base_results 为空 → 返回 _NO_BASELINE
```

metadata 维度同理——如果 baseline 没有对应数据，返回 neutral。

### 2. capability 接入 probe_defs

**根因：** `analyze()` 不接受 probe_defs 参数，`_dim_capability` 只能用 metadata 变化率做代理。

**修改：**

- `analyze()` 新增参数 `probe_defs: dict[str, list[Probe]] | None = None`
- `_dim_capability` 改为优先使用 probe_defs：
  - 从 `probe_defs["instruction"]` 获取 SimpleProbe 列表，调用 `check_instruction(cur_results, instruction_defs)`
  - 从 `probe_defs["coding_frontend"]` + `probe_defs["coding_backend"]` 获取 CodingProbe 列表，调用 `check_coding(cur_results, coding_defs)`
  - 当前和基线分别计算满足率后，用 `compare(cur_rate, base_rate, thresholds)` 做对比
  - 如果 probe_defs 为空，保持 fallback 到 metadata

### 3. text_similarity 按 probe_type 区分策略

**根因：** style_open 是开放性问题，不同次运行内容天然不同，逐字比对得分低不代表模型变化。

**修改：** 调整 `_PROBE_DIMENSIONS` 映射：

```python
# 修改前
_PROBE_DIMENSIONS = {
    "instruction": [_DIM_CAPABILITY],
    "style_open": [_DIM_BEHAVIOR, _DIM_TEXT_SIM],
    "consistency": [_DIM_TEXT_SIM],
    ...
}

# 修改后
_PROBE_DIMENSIONS = {
    "instruction": [_DIM_CAPABILITY, _DIM_TEXT_SIM],  # 新增 text_sim
    "coding_frontend": [_DIM_CAPABILITY],
    "coding_backend": [_DIM_CAPABILITY],
    "style_open": [_DIM_BEHAVIOR],                      # 去掉 text_sim
    "consistency": [_DIM_TEXT_SIM],
    "statistical": [_DIM_STATISTICAL],
}
```

- instruction 探针输出有明确格式约束（JSON、特定结构），逐字比较有合理性
- style_open 的特征对比已由 behavior 维度覆盖（词频 JS 散度 + 句长 KS + 标点比例）

### 4. 流水线串联 — 分析集成到 run

**当前流程：** `Orchestrator.run()` → 执行探针 → 设 baseline → 结束

**修改后：** `Orchestrator.run()` → 执行探针 → 设 baseline → **如果有历史 baseline → 自动分析 → 保存 → 生成报告**

具体修改：

- `Orchestrator.__init__` 新增 `output_dir: str | None = None` 参数
- `Orchestrator.run()` 末尾增加自动分析和报告生成：
  1. 对每个 target，检查是否已有 baseline（且不是本次 run）
  2. 如果有：加载 baseline 各 probe_type 的 run 数据
  3. 调用 `analyze(current_runs, baseline_runs, config, probe_defs=all_probes)`
  4. 序列化并保存到 `storage.save_analysis()`
  5. 调用 `ReportGenerator(output_dir).generate_and_save(model_dir)`
- `cli_service.py` 和 `main.py` 传递 `output_dir` 到 Orchestrator

## 不改的部分

- 各子模块（behavior/similarity/statistical/metadata/capability）内部逻辑不变
- 探针定义（probes/*.json）不变
- 存储层不变
