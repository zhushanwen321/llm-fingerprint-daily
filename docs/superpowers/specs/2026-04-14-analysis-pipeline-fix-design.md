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

核心改动文件：
- `src/analysis/analyzer.py` — 问题 1/2/3
- `src/engine/orchestrator.py` — 流水线串联

需要同步更新的文件：
- `tests/test_e2e.py` — instruction 新增 text_similarity 维度后测试需适配

不改动：
- 子模块（behavior/similarity/statistical/metadata/capability）内部逻辑不变
- 探针定义（probes/*.json）不变
- 存储层不变

## 设计详情

### 1. baseline 部分缺失 → neutral

**根因：** `_compute_dimension` 只判断了全局 `no_baseline`（`baseline_runs is None`），没处理单个 probe_type 在 baseline 中缺失的情况。

实际行为差异：
- `_dim_behavior`：空 base_texts 时返回 `score=1.0, alert="normal"`（正确）
- `_dim_statistical`：空 base_texts 时返回 `score=0.0, alert="critical"`（bug）
- `_dim_metadata`：空 base_valid 时返回 `score=0.0, alert="critical"`（bug）

**修改：** 在 `_compute_dimension` 入口（分发到子模块之前）统一拦截——如果 `base_results` 为空列表，返回 `_NO_BASELINE`（score=1.0, alert=normal）。这样各子模块对空列表的行为差异被统一收敛，子模块中的防御性检查变为死代码但无害。

### 2. capability 接入 probe_defs

**根因：** `analyze()` 不接受 probe_defs 参数，`_dim_capability` 只能用 metadata 变化率做代理。`capability.py` 中已有 `check_instruction(probe_results, probe_defs)` 和 `check_coding(probe_results, probe_defs)`。

**修改：**

#### 2.1 参数传递链

```
analyze(probe_defs=...) → _compute_dimension(probe_defs=...) → _dim_capability(probe_defs=...)
```

- `analyze()` 新增第四个参数 `probe_defs: dict[str, list[Probe]] | None = None`（放在 `config` 之后，有默认值，不影响现有调用方）
- `_compute_dimension()` 新增参数 `probe_defs: dict[str, list[Probe]] | None = None`
- `_dim_capability()` 新增参数 `probe_defs: dict[str, list[Probe]] | None = None`

#### 2.2 多 probe_type 合并计算

instruction、coding_frontend、coding_backend 都映射到 `_DIM_CAPABILITY`，但 `if dim in dims: continue` 去重逻辑只让第一个触发的 probe_type 计算一次。

**修改去重逻辑：** capability 维度在第一次触发时，一次性合并所有 probe_type（instruction + coding_frontend + coding_backend）的 results 和 probe_defs：

```python
# _dim_capability 内部
_CAPABILITY_TYPES = {"instruction", "coding_frontend", "coding_backend"}

def _dim_capability(cur_results, base_results, config, probe_defs=None):
    if probe_defs is None:
        return _dim_metadata(cur_results, base_results, config, ...)  # fallback
    
    # 合并所有 capability probe_type 的 results（caller 需要传入全部）
    # caller 在第一次触发 _DIM_CAPABILITY 时，已经收集了所有相关 probe_type 的数据
    
    instruction_defs = probe_defs.get("instruction", [])
    coding_defs = probe_defs.get("coding_frontend", []) + probe_defs.get("coding_backend", [])
    
    cur_inst_rate = check_instruction(cur_results, instruction_defs)
    base_inst_rate = check_instruction(base_results, instruction_defs)
    cur_code_rate = check_coding(cur_results, coding_defs)
    base_code_rate = check_coding(base_results, coding_defs)
    
    # 加权平均
    cur_rate = (cur_inst_rate * len(instruction_defs) + cur_code_rate * len(coding_defs)) / max(1, total)
    base_rate = ...
    return compare(cur_rate, base_rate, thresholds)
```

**analyzer 的调用侧修改：** 不再在 `for probe_type` 循环内按单个 probe_type 传递 results，改为在循环开始前预收集所有 capability 相关 probe_type 的合并 results 和 probe_defs，在第一次遇到 `_DIM_CAPABILITY` 时传入合并后的数据。

### 3. text_similarity 按 probe_type 区分策略

**根因：** style_open 是开放性问题，不同次运行内容天然不同，逐字比对得分低不代表模型变化。

**修改：** 调整 `_PROBE_DIMENSIONS` 映射：

```python
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

**测试影响：** `test_e2e.py::test_full_pipeline` 使用 instruction 探针，修改后新增 text_similarity 维度。由于 mock gateway 返回相同文本，similarity 分数应接近 1.0，`assert result.overall_score >= 0.5` 不会断。但需要确认维度名称集合的变化不会影响其他断言。

### 4. 流水线串联 — 分析集成到 run

**当前流程：** `Orchestrator.run()` → 执行探针 → 设 baseline → 结束

**修改后：** `Orchestrator.run()` → 执行探针 → 设 baseline → **如果有历史 baseline → 自动分析 → 保存 → 生成报告**

#### 4.1 output_dir 来源

`Orchestrator.__init__` 不新增参数。直接从 `self._config.report.output_dir` 获取输出目录，避免增加外部传递复杂度。

#### 4.2 基线数据加载逻辑

对每个 target：
1. 获取 baseline_run_id = `await storage.get_baseline(model_dir)`
2. 如果 baseline_run_id == 当前 run_id（首次运行），跳过分析
3. 遍历当前 run 涉及的所有 probe_type（`probe_types` 变量），逐个调用：
   ```python
   base_data = await storage.load_run(model_dir, pt, baseline_run_id)
   ```
4. 只收集非空的 baseline 数据到 `baseline_runs` dict

#### 4.3 自动分析和报告生成

```python
# orchestrator.py run() 末尾（伪代码）
for t in targets:
    model_dir = f"{provider}__{t.model}"
    baseline_run_id = await self._storage.get_baseline(model_dir)
    if baseline_run_id is None or baseline_run_id == run_id:
        continue  # 首次运行，无 baseline 可比

    # 加载当前和基线数据
    current_runs = {}
    baseline_runs = {}
    for pt in probe_types:
        cur = await self._storage.load_run(model_dir, pt, run_id)
        if cur:
            current_runs[pt] = cur
        base = await self._storage.load_run(model_dir, pt, baseline_run_id)
        if base:
            baseline_runs[pt] = base

    if not baseline_runs:
        continue

    # 分析
    result = analyze(current_runs, baseline_runs, eval_cfg, probe_defs=all_probes)
    result_dict = _analysis_to_dict(result)
    await self._storage.save_analysis(model_dir, run_id, result_dict)

    # 报告
    from src.report.generator import ReportGenerator
    model_path = self._storage._base / "data" / model_dir
    gen = ReportGenerator(output_dir=Path(self._config.report.output_dir))
    gen.generate_and_save(model_path)
```

#### 4.4 all_probes 数据流

`all_probes` 在 `run()` 方法第 65 行通过 `load_probes()` 获取，作为局部变量。在方法末尾直接传给 `analyze()`，无需存储为实例变量。

#### 4.5 ReportGenerator import

`orchestrator.py` 需新增延迟导入 `from src.report.generator import ReportGenerator`（在方法内部导入，避免循环依赖）。
