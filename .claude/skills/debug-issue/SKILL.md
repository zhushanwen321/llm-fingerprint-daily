---
name: debug-issue
description: 使用知识图谱系统性追踪和调试问题，通过调用链分析和影响半径定位 bug
---

使用 code-review-graph MCP 工具系统性追踪和调试问题。

## 步骤

1. **定位相关代码** — `semantic_search_nodes` 搜索与问题相关的函数/类
2. **追踪调用链** — `query_graph` 使用 `callers_of` 和 `callees_of` 追踪上下游
3. **查看执行路径** — `get_flow` 查看疑似区域的完整执行路径
4. **检查近期变更** — `detect_changes` 查看是否由最近修改引入
5. **评估影响范围** — `get_impact_radius` 查看疑似文件的连带影响

## 要点

- 同时检查 callers 和 callees，理解完整上下文
- 通过 affected flows 找到触发 bug 的入口点
- 近期变更是新问题最常见的来源

## Token 效率规则

- 始终以 `get_minimal_context(task="...")` 开始
- 所有调用使用 `detail_level="minimal"`，仅在不足时升级为 "standard"
- 目标：5 次工具调用内完成，输出 ≤800 tokens
