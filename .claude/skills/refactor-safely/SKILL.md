---
name: refactor-safely
description: 使用依赖分析规划安全重构，支持重命名预览、死代码检测和影响评估
---

使用知识图谱规划和执行安全重构。

## 步骤

1. **获取建议** — `refactor_tool(mode="suggest")` 获取社区驱动的重构建议
2. **检测死代码** — `refactor_tool(mode="dead_code")` 查找无引用的代码
3. **预览重命名** — `refactor_tool(mode="rename")` 预览所有受影响位置
4. **应用变更** — `apply_refactor_tool(refactor_id=...)` 应用重命名
5. **验证影响** — `detect_changes` 验证重构的影响范围

## 安全检查

- 始终先预览再应用（rename 模式会返回编辑列表）
- 大范围重构前检查 `get_impact_radius`
- 用 `get_affected_flows` 确保关键路径未被破坏
- 用 `find_large_functions` 识别需要拆分的目标

## Token 效率规则

- 始终以 `get_minimal_context(task="...")` 开始
- 所有调用使用 `detail_level="minimal"`，仅在不足时升级为 "standard"
- 目标：5 次工具调用内完成，输出 ≤800 tokens
