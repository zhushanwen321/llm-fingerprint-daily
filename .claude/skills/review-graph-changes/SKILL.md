---
name: review-graph-changes
description: 使用知识图谱的变更检测和影响分析执行结构化代码审查
---

使用知识图谱执行结构化、风险感知的代码审查。

## 步骤

1. **变更检测** — `detect_changes` 获取带风险评分的变更分析
2. **影响路径** — `get_affected_flows` 查找受影响的执行路径
3. **测试覆盖** — 对每个高风险函数运行 `query_graph(pattern="tests_for")` 检查测试覆盖
4. **影响半径** — `get_impact_radius` 理解变更的波及范围
5. **补充建议** — 对未覆盖的变更建议具体测试用例

## 输出格式

按风险等级（high/medium/low）分组：
- 变更内容及影响
- 测试覆盖状态
- 改进建议
- 合并建议

## Token 效率规则

- 始终以 `get_minimal_context(task="...")` 开始
- 所有调用使用 `detail_level="minimal"`，仅在不足时升级为 "standard"
- 目标：5 次工具调用内完成，输出 ≤800 tokens
