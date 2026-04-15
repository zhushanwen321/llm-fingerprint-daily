<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

# LLM Fingerprint Daily

## 项目概述
LLM 指纹追踪工具 - 通过定时评测追踪大语言模型的能力变化和指纹特征。

## 关键目录

| 路径 | 用途 |
|------|------|
| `/home/zhushanwen/scripts/llm-fingerprint-daily/` | 部署脚本存放位置，负责拉取 GitHub Docker 镜像并部署 |
| `/home/zhushanwen/app/llm-fingerprint-daily/` | 镜像部署后的数据目录映射（配置文件、评测数据、报告等） |

## 技术栈
- Python 3.12, Typer CLI, Pydantic, httpx
- Docker 部署，ENTRYPOINT 为 `fingerprint`
- 配置文件为 `config.yaml`，支持 `${ENV_VAR}` 环境变量引用

## CLI 子命令
- `fingerprint run` - 执行一次评测
- `fingerprint serve` - 启动定时调度
- `fingerprint report` - 生成 HTML 报告
- `fingerprint history` - 查看历史评分
- `fingerprint baseline` - 手动设置基线
