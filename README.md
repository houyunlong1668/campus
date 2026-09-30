# 基于 MCP 协议的校园浏览器 Agent

一句话定位：一个**操作型**校园浏览器 Agent——前端输入一句话，Agent 理解意图、通过语义路由找到目标页面，经 MCP 协议调用工具完成信息查询、任务跳转与数据查询，并以 SSE 流式返回文本、跳转卡片与查数结果。

区别于只答文本的问答型机器人：它能看、能点、能读、能填，且配有完整的 Agent 行为测试体系。

## 核心特性

- **语义路由 + 页面能力注册**：`PAGE_REGISTRY` 注册各页面路径与能力，LLM 按语义匹配目标页，不做关键词硬匹配。
- **MCP 协议调用工具**：后端以 stdio 子进程拉起 MCP server（`mcp_servers/navigation`），工具协议与业务解耦、可独立演进。
- **SSE 流式交互**：`token / tool_call / nav_card / done / error` 事件表前后端一一对应，打字机输出 + 跳转卡片。
- **身份与会话**：HttpOnly Cookie `sid` + 学生身份依赖，`student_id` 只从会话取、绝不信请求体。
- **Text-to-SQL 查数**：对话框内自然语言转 SQL，返回对话内数据表（S3 已交付）。
- **MySQL / SQLite 双方言**：`DB_BACKEND` 一键切换，迁移文件双方言目录文件名集合由契约脚本钉死。

## 技术架构

```
frontend/src/composables/useChatStream.ts   唯一网络出口（组件不发请求）
  └─ POST /chat ─ fetch + ReadableStream 解析 SSE（lib/sse.ts 纯函数解析器）
       ↓ SSE 事件: token / tool_call / nav_card / done / error
backend/app/api/chat.py                     手工帧化 StreamingResponse
  └─ agent/graph.py  LangGraph: START → router →(条件边)→ tool_executor → generator → END
       ├─ llm/       LLMProvider 协议：fake.py（规则式）| openai_compat.py（通义/DeepSeek）
       ├─ tools/     ToolRegistry 协议：stdio_mcp.py（真）| inmemory.py（测试/降级）
       └─ db/        Database 协议（aiomysql | aiosqlite）+ repository + 双方言迁移器
            ↓ stdio 子进程（AsyncExitStack，lifespan 内拉起）
mcp_servers/navigation/server.py            MCPServer("navigation") + PAGE_REGISTRY
```

- **前端**：Vue 3 + Vite + TypeScript，dev 代理 `/api /chat /auth /health /debug` → :8000
- **后端**：FastAPI + LangGraph + SSE，uv 管理依赖
- **MCP**：`mcp>=2.2,<3`，stdio 握手，`MCPServer` 类
- **持久化**：MySQL（Docker 容器 `campus-mysql`，宿主端口 3307）或 SQLite 降级

## 目录结构

```
backend/            FastAPI 应用：api / agent / llm / tools / db / auth
frontend/           Vue 3 前端：门户首页、悬浮球、聊天窗口、路由与守卫
mcp_servers/        MCP 子进程服务：navigation（页面路由），将来 academic
k6/                 k6 HTTP 门禁测试（helpers + 场景脚本）
scripts/            灌库、MCP 握手、跨层契约断言、k6 启动脚本
deploy/             Docker Compose（只管 MySQL）
docs/superpowers/   文档驱动开发：specs/ 设计、plans/ 实施计划
方案.md             8 周愿景与总体方案
CLAUDE.md           Claude Code 工作指引与硬约束
```

## 快速开始

前置：Python 3.12+（[uv](https://docs.astral.sh/uv/)）、Node 18+、可选 Docker（MySQL）。

```bash
# 1. 配置
cp .env.example backend/.env        # 默认 LLM_PROVIDER=fake，无 Key 全链路可跑

# 2. 启动后端（:8000）
cd backend
uv sync
uv run uvicorn app.main:app --port 8000
# 无 Docker 降级：DB_BACKEND=sqlite uv run uvicorn app.main:app --port 8000

# 3. 启动前端（:5173）
cd frontend
npm install
npm run dev

# 4. 灌库（幂等，账号 20230001/demo1234 等，仅本地仿真）
cd backend && uv run python ../scripts/seed_academic.py

# 5.（可选）MySQL
cd deploy && docker compose up -d   # backend/.env 需设 MYSQL_PORT=3307
```

打开 http://localhost:5173 即可对话。

## 测试体系（三层，互不替代）

| 层 | 位置 | 证明什么 |
|----|------|---------|
| pytest | `backend/tests/` | 逻辑对错：SQLite + InMemoryRegistry + FakeProvider，不起子进程不打网络 |
| vitest | `frontend/tests/` | SSE 解析器、composables 状态机 |
| k6 | `k6/tests/` | 过了一层真网络之后还对不对：401/422/429、会话隔离、SSE 事件序列 |

```bash
cd backend && uv run pytest -v              # 全部 pytest
cd frontend && npm test                     # vitest
bash scripts/run_k6.sh                      # k6 门禁（需先 winget install GrafanaLabs.k6）

# 跨层契约：PAGE_REGISTRY ↔ 前端路由 ↔ /api/* ↔ 迁移文件名
uv run python scripts/check_routes_contract.py
# MCP stdio 握手 + 工具调用
cd mcp_servers/navigation && uv run python ../../scripts/check_mcp.py
```

## 里程碑进度

- ✅ **M1–M6**：Agent MVP（语义路由、SSE 对话、跳转卡片、门户页面）
- ✅ **S1** 身份会话 · **S2** MySQL 数据层 · **S3** Text-to-SQL 查数与对话框数据表 · **k6 门禁**
- 🚧 **S4** 多工具条件编排 + 操作确认与回放（设计见 `docs/superpowers/specs/2026-09-22-campus-roadmap-s4-s7-design.md`）

设计与实施文档见 [docs/superpowers/](docs/superpowers/)（specs 设计 / plans 逐步勾选与执行回填）。

## 许可证

[MIT](LICENSE)
