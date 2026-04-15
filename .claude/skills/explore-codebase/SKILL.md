---
name: explore-codebase
description: 使用知识图谱导航和理解代码库结构，快速定位模块、函数和依赖关系
---

使用 code-review-graph MCP 工具探索和理解代码库。

## 步骤

1. **全局概览** — `list_graph_stats` 查看代码库指标
2. **架构视图** — `get_architecture_overview` 获取高层社区结构
3. **模块细节** — `list_communities` 发现主要模块，`get_community` 查看详情
4. **精确搜索** — `semantic_search_nodes` 查找特定函数或类
5. **关系追踪** — `query_graph` 使用 `callers_of`、`callees_of`、`imports_of` 追踪关系
6. **执行路径** — `list_flows` + `get_flow` 理解完整执行链路

## 要点

- 先广后深：从 stats、architecture 开始，再聚焦具体区域
- `children_of` 查看文件中的所有函数和类
- `find_large_functions` 识别复杂代码

## Token 效率规则

- 始终以 `get_minimal_context(task="...")` 开始
- 所有调用使用 `detail_level="minimal"`，仅在不足时升级为 "standard"
- 目标：5 次工具调用内完成，输出 ≤800 tokens
