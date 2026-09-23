# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

基于 MCP 协议的校园浏览器 Agent：前端输入一句话 → FastAPI `/chat`（SSE）→ LangGraph 路由 → 通过 stdio 子进程调用 MCP 工具 → 流式返回文本与跳转卡片 / 查数结果。**文档驱动开发**：需求出自 `方案.md`（8 周愿景），切片设计在 `docs/superpowers/specs/`，实施计划在 `docs/superpowers/plans/`（含逐步勾选与执行回填）。改动前先确认当前里程碑归属——已交付 M1–M6、S1（身份会话）、S2（MySQL 数据层）、S3（Text-to-SQL 查数与对话框数据表，2026-09-23 合入）、k6 门禁；下一个是 S4（多工具条件编排 + 操作确认与回放），S4–S7 见 `2026-09-22-campus-roadmap-s4-s7-design.md`。S3 台账在 `.superpowers/sdd/2026-09-22-campus-s3-text2sql/`（progress.md + 各 task report）。

文档与注释、commit message 一律中文。

## 常用命令

Python 侧一律 `uv`（禁止裸 pip 装进全局）。三个独立 uv 项目：`backend/`、`mcp_servers/navigation/`（将来还有 `mcp_servers/academic/`）。

```bash
# 后端（:8000）
cd backend
uv sync                                    # 装依赖（含 dev 组 pytest）
uv run uvicorn app.main:app --port 8000    # 启动（默认 DB_BACKEND=mysql）
DB_BACKEND=sqlite uv run uvicorn app.main:app --port 8000   # 无 Docker 降级
uv run pytest -v                           # 全部测试
uv run pytest tests/test_graph.py -v       # 单个测试文件
uv run pytest tests/test_graph.py::test_name -v  # 单条用例

# MCP server 测试与握手脚本（从 mcp_servers/navigation 目录跑）
uv run pytest tests/ -v
uv run python ../../scripts/check_mcp.py           # stdio 握手 + 工具调用验证
uv run python ../../scripts/check_routes_contract.py  # 跨层契约断言

# 前端（:5173，dev 代理 /api /chat /auth /health /debug → :8000）
cd frontend
npm install
npm run dev
npm run build          # vue-tsc 类型检查 + vite build
npm test               # vitest run
npx vitest run tests/sse.test.ts          # 单个测试文件

# 灌库（幂等，重跑即刷新；账号密码 20230001/demo1234 等，仅本地仿真）
cd backend && uv run python ../scripts/seed_academic.py
DB_BACKEND=sqlite uv run python ../scripts/seed_academic.py   # 指定后端

# k6 HTTP 门禁（独立于 pytest，不进 pytest 门禁）
# 需先装 k6：winget install GrafanaLabs.k6；在 Git Bash 里跑
bash scripts/run_k6.sh    # 自建临时 sqlite（backend/data/k6-smoke.db）+ 起 :8300 + 跑 k6/tests/*.js

# MySQL（容器名固定 campus-mysql，宿主机端口 3307——3306 被本机原生 mysqld 占用）
cd deploy && docker compose up -d
# backend/.env 需设 MYSQL_PORT=3307；凭据放 deploy/.env（不入库）
```

配置：复制 `.env.example` → `backend/.env`。`LLM_PROVIDER=fake`（默认，无 Key 全链路可跑）或 `openai_compat`（需 `OPENAI_BASE_URL`/`OPENAI_MODEL`/`OPENAI_API_KEY`）。进程 env 优先于 `.env`（pydantic-settings）。

## 架构

```
frontend/src/composables/useChatStream.ts   唯一网络出口（组件不发请求）
  └─ POST /chat ─ fetch + ReadableStream 解析 SSE（lib/sse.ts 纯函数解析器）
       ↓ SSE 事件: token / tool_call / nav_card / done / error
backend/app/api/chat.py                     手工帧化 StreamingResponse
  └─ agent/graph.py  LangGraph: START → router →(条件边)→ tool_executor → generator → END
       ├─ llm/       LLMProvider 协议；fake.py（规则式）| openai_compat.py（通义/DeepSeek）
       ├─ tools/     ToolRegistry 协议：stdio_mcp.py（真）| inmemory.py（测试/降级）
       └─ db/        Database 协议（aiomysql | aiosqlite）+ repository + 双方言迁移器
            ↓ stdio 子进程（AsyncExitStack，lifespan 内拉起）
mcp_servers/navigation/server.py            MCPServer("navigation") + PAGE_REGISTRY + resolve_page/list_pages
```

两条稳定接缝，两侧可独立演进：**SSE 事件表**（spec 5.5，前后端 `schemas.py` ↔ `types.ts` 一一对应）与 **`ToolRegistry` 协议**（`tools/base.py`，工具降级、埋点、测试注桩的唯一入口）。

关键跨层耦合由 `scripts/check_routes_contract.py` 钉住：`PAGE_REGISTRY` 路径 ↔ `frontend/src/router/index.ts` 路由 ↔ `/api/*` 端点 ↔ 双方言迁移文件名集合，一条命令任一断言失败即非零退出。

持久化：`DB_BACKEND=mysql|sqlite`（默认 mysql）。迁移文件在 `backend/app/db/migrations/{mysql,sqlite}/NNNN_*.sql`，**双方言目录文件名集合必须相同**（契约脚本断言）；启动时 `run_migrations` + `assert_current_schema`（发现 S2 前遗留表形状会拒绝启动，需人工清库）。

身份：HttpOnly Cookie `sid`（`SessionStore`）+ `require_student` 依赖；前端路由守卫 bootstrap `GET /auth/me`。seed 账号见 `scripts/seed_academic.py`。

## 硬约束（出自各 spec，违反即破坏验收）

- **`student_id` 只从会话取，绝不信请求体**：`ChatRequest` 不含该字段且 `extra="forbid"`（塞入即 422）。后端从 `request.state.student` 重写身份。
- **MCP stdio 三硬约束**：`command=sys.executable`（不用字符串 `"python"`）；`cwd` 用绝对路径；`server.py` 内**禁止 `print()` 到 stdout**（协议帧与杂质共流），日志一律 `logging`（stderr）。踩中表现为"server 起来了但零工具"。
- `mcp` 依赖两侧必须同为 `mcp>=2.2,<3`，server 类从 `mcp.server` 导入 `MCPServer`（`FastMCP` 路径已废弃）；版本不一致握手协商失败。
- CORS 显式白名单 `http://localhost:5173` 且 `allow_credentials=True`（会话 Cookie 需要），禁 `allow_origins=["*"]`。
- Markdown 渲染必须 `html:false`（模型输出直插 DOM 是 XSS 入口）。
- LangGraph 节点返回值带 `"steps": ["<节点名>"]`（`operator.add` reducer），禁止原地 append 后返回；图编译 `recursion_limit=8`，超限在 `api/chat.py` 转 `error` 事件。
- 工具参数在 `call_tool` 前按 `ToolSpec.input_schema` 校验，不合法直接 `ok=False`，不下发 MCP。
- SSE 响应头带 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`。
- `k6/lib/helpers.js`：cookie jar 必须延迟到首次请求（VU 上下文）创建——k6 init 上下文禁造 jar。
- 改 `/chat` 契约、`PAGE_REGISTRY`、迁移文件时，同步检查前后端与契约脚本三处（spec 明示"破坏性变更必须同步前端"）。

## 测试体系（三层，互不替代）

- **pytest**（`backend/tests/`）：证逻辑对错。跑 SQLite、`InMemoryRegistry`、`FakeProvider`，不起子进程不打网络。`asyncio_mode=auto`。
- **vitest**（`frontend/tests/`）：SSE 解析器、composables 状态机。
- **k6**（`k6/tests/`）：证"过了一层真网络之后还对不对"——401/422/429、会话隔离、SSE 完整事件序列。独立入口 `scripts/run_k6.sh`，**不进 pytest**（避免 pytest 里起子进程）。k6 运行时是 goja 不是 Node：只能 ES module，无 require/fs。
- 跨层契约：`scripts/check_routes_contract.py`。MCP 握手：`scripts/check_mcp.py`。

## 工作流与约定

- Spec → Plan → 实施：plan 文档用 `- [ ]` 步骤勾选，完成后回填执行结果（含偏离记录），见既有 plan 的写法。
- Commit 格式：`type(scope): 中文描述`，scope 如 `front` / `db,api,ui` / `k6` / `spec` / `plan`；多模块用逗号。分支按里程碑命名（`campus-s2`、`campus-k6`），完成后 merge 进 `main`。
- Docker 只管 MySQL（`deploy/`）；WSL Docker TCP 辅助脚本在 `scripts/wsl-docker-tcp/`。`.worktrees/` 是 git worktree 克隆，已 gitignore，勿把那边当主仓库。
- 本机端口事实：宿主 3306 被非本项目 mysqld 占用 → MySQL 映射 3307；后端 :8000、前端 :5173、k6 门禁 :8300。
