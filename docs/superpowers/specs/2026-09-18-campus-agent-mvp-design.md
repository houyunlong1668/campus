# 校园浏览器 Agent — MVP 设计文档

**日期**：2026-09-18
**状态**：已与用户逐节确认
**范围**：`方案.md` 阶段一（第 1–2 周）中的"最小端到端链路"切片，对应 2026-09-18 当晚的产出

---

## 0. 本文与 `方案.md` 的关系

`方案.md` 描述的是 8 周完整愿景，包含至少 6 个可独立交付的子系统：前端门户、FastAPI + SSE 后端、LangGraph 编排、5 个 MCP Server、Page Agent 运行时、Agent 行为测试体系。这超出单份 spec 的可实施范围。

本文只覆盖**第一个可运行切片**：用户在前端输入一句话 → 后端 LangGraph 路由 → 通过 MCP 协议调用工具 → 流式返回文本与跳转卡片 → 前端渲染并真实跳转。其余子系统在本文第 10 节声明接入点，各自后续独立成 spec。

本文对 `方案.md` 原文有三处修正或收窄，见第 2 节，每一处都附证据或理由。

---

## 1. 已确认的前提决策

| 议题 | 决策 | 理由 |
|---|---|---|
| 数据来源 | **自建仿真校园站**（同一 Vue 应用内的教务/成绩/课表/新闻页 + seed 假数据） | `方案.md` 第四节设想用 `iframe + postMessage` 操作目标页面。真实教务系统普遍返回 `X-Frame-Options: DENY` 且跨域，浏览器会拒绝嵌入与 DOM 注入，该设计对学校系统不成立。自建同源页面后，注入、通信、五级降级、操作回放全部可真实运行。 |
| 持久化 | **SQLite + 进程内字典** | Docker 在 WSL 内、不在 Windows PATH。今晚链路不依赖容器。存储访问经 repository 接口隔离，换 MySQL 只改连接串与驱动。 |
| 大模型 | **可插拔 Provider + 内置 Fake** | 见第 5.3 节。Fake provider 让全链路无 Key、无网络也能跑通，同时是行为测试体系的确定性基线。 |
| 编排框架 | **今晚即引入 LangGraph 单图** | 图结构、State、节点埋点一旦定型，后续加 `grader`/`rewrite` 节点是纯增量。先用手写 if-else 再换，等于把工具调用与降级逻辑重写一遍。 |
| 前端范围 | 首页 + 悬浮球 + 聊天窗 + 2 个仿真页占位 | 跳转卡片必须能真的跳，否则演示链路断在最后一环。 |
| MCP 接入 | **stdio 子进程 + ToolRegistry 协议抽象** | 见第 5.1 节。 |

---

## 2. 对 `方案.md` 的技术修正

### 2.1 MCP Python SDK 已发布 v2，server 类改名

PyPI 上 `mcp` 包最新为 **2.2.0（2026-09-07 发布）**，官方文档 `docs/whats-new.md` 明确：

```python
from mcp.server import MCPServer          # v2
from mcp.server.fastmcp import FastMCP    # v1，已废弃路径
```

绝大多数现存教程与示例写的是 `FastMCP`。本项目一律按 v2 写，`pyproject.toml` 钉 `mcp>=2.2,<3`。`mcp_servers/` 与 `backend/` 两侧版本必须一致，否则握手期协议版本协商会失败。

### 2.2 `EventSource` 无法承载对话请求体

`方案.md` 决策二选择 SSE 并依赖"浏览器原生 `EventSource` 自带断线重连"。但 `EventSource` API 只支持 GET，不能带请求体，也无法带自定义 Header。这留下两个选项：

1. 把用户输入放进 query string —— 对话内容会写进 Nginx access log 与浏览器历史，等同于把用户输入明文落盘，不可接受。
2. 前端改用 `fetch()` + `ReadableStream` 手工解析 SSE 帧 —— 放弃 `EventSource` 的自动重连。

**取选项 2。** 放弃自动重连的代价很小：对话场景的续传要求客户端知道"最后收到的 token 偏移量"，这本身就要自己维护状态，`EventSource` 的 `Last-Event-ID` 机制对逐 token 流式输出并不省事。线格式仍是标准 SSE，后端不需要为此写任何特殊代码。

`方案.md` 决策二"用 SSE 而非 WebSocket"的结论不变，仅实现载体从 `EventSource` 换成 `fetch` 流。

### 2.3 Page Agent 推迟到独立 spec

`方案.md` 第四节的 Page Agent 运行时、五级降级、操作回放不在本切片内。本文只保证跳转卡片能真的 `router.push` 到仿真页面——这是"操作型 Agent"链路的最小可演示形态。Page Agent 的注入协议依赖本文的仿真页面结构先稳定，顺序上本就该在后。

---

## 3. 架构总览（本切片）

```
┌───────────────────────────── 浏览器 (Vite dev :5173) ─────────────────────────────┐
│  Home.vue ──┐                                                                      │
│  Schedule.vue  Grades.vue（仿真页）                                                │
│             │                                                                      │
│  FloatingBall ── ChatBox ── useChatStream.ts ── fetch POST /chat + ReadableStream  │
└──────────────────────────────────────────┬─────────────────────────────────────────┘
                                           │  SSE 线格式（命名事件）
┌──────────────────────────────────────────▼───────────── FastAPI (:8000) ───────────┐
│  api/chat.py  ── StreamingResponse                                                 │
│       │                                                                            │
│  agent/graph.py  LangGraph: START → router ─(cond)→ tool_executor → generator → END │
│       │              │                                        │                    │
│  llm/provider.py     │                            tools/registry.py                │
│   ├ fake.py          │                             ├ stdio_mcp.py  ── AsyncExitStack│
│   └ openai_compat.py │                                        │                     │
│  db/sqlite.py ◄──────┘                                        │                     │
│    （steps + tool_calls 落表）                                  │                     │
└───────────────────────────────────────────────────────────────┼─────────────────────┘
                                                    stdio 子进程  │
                                          ┌───────────────────────▼──────────────────┐
                                          │  mcp_servers/navigation (: 无端口)        │
                                          │  MCPServer("navigation")                 │
                                          │  PAGE_REGISTRY + resolve_page / list_pages│
                                          └──────────────────────────────────────────┘
```

前后端之间唯一的契约是第 5.5 节的 SSE 事件表；后端与工具之间唯一的契约是第 5.1 节的 `ToolRegistry` 协议。这两条接缝稳定，第 4/5 节的前端与 `mcp_servers/` 就能并行演进。

---

## 4. 仓库结构

```
campusProject/
├─ 方案.md                              # 既有，愿景文档
├─ docs/superpowers/specs/              # 设计文档
├─ frontend/                            # Vue 3 + Vite + Element Plus
│  └─ src/
│     ├─ views/                         # Home.vue / ScheduleView.vue / GradesView.vue
│     ├─ components/chat/               # FloatingBall.vue / ChatBox.vue / MessageList.vue
│     │                                 # MessageBubble.vue / NavigationCard.vue
│     ├─ composables/useChatStream.ts   # 唯一的网络出口
│     ├─ lib/sse.ts                     # SSE 帧解析器（纯函数，可单测）
│     ├─ router/index.ts
│     └─ types.ts                       # 与后端 schemas.py 一一对应
├─ backend/                             # 独立 uv 项目
│  ├─ pyproject.toml
│  └─ app/
│     ├─ main.py                        # FastAPI app + lifespan + CORS
│     ├─ config.py                      # pydantic-settings 读 .env
│     ├─ schemas.py                     # 请求体与 SSE 事件的 pydantic 模型
│     ├─ api/chat.py                    # POST /chat, GET /health, GET /debug/tools
│     ├─ agent/
│     │  ├─ state.py                    # AgentState TypedDict
│     │  ├─ graph.py                    # 图装配 + recursion_limit
│     │  └─ nodes/                      # router.py / tool_executor.py / generator.py
│     ├─ llm/
│     │  ├─ base.py                     # LLMProvider 协议 + RouteDecision
│     │  ├─ fake.py                     # 规则式，无外部依赖
│     │  └─ openai_compat.py            # 通义千问 / DeepSeek 共用
│     ├─ tools/
│     │  ├─ base.py                     # ToolRegistry 协议 + ToolSpec/ToolResult
│     │  ├─ stdio_mcp.py                # 真实实现
│     │  └─ inmemory.py                 # 测试/降级实现
│     └─ db/
│        ├─ engine.py                   # aiosqlite 连接与建表
│        └─ repository.py               # ConversationRepository 协议 + sqlite 实现
├─ mcp_servers/
│  └─ navigation/                       # 独立 uv 项目
│     ├─ pyproject.toml
│     └─ server.py                      # MCPServer + PAGE_REGISTRY + 2 tools
├─ scripts/
│  └─ check_mcp.py                      # 单独握手 MCP server 的验证脚本
├─ .env.example
├─ .gitignore
└─ README.md
```

`mcp_servers/navigation` 与 `backend` 是**两个独立的 uv 项目**，各有自己的 `pyproject.toml` 与虚拟环境。原因：MCP server 要能被当作子进程独立拉起，不能依赖后端的包路径；同时它的依赖树应当只有 `mcp` 一个重量级包，保持冷启动快。

---

## 5. 组件设计

### 5.1 `ToolRegistry` —— 后端与工具之间的接缝

```python
# app/tools/base.py
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]      # JSON Schema，直接喂给 LLM 的 function 定义

class ToolResult(BaseModel):
    ok: bool
    data: Any | None = None
    error: str | None = None
    latency_ms: int

class ToolRegistry(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult: ...
```

两个实现：

- **`StdioMcpRegistry`** —— 在 FastAPI `lifespan` 里用 `AsyncExitStack` 打开 `stdio_client(StdioServerParameters(...))`，创建 `ClientSession` 并 `await session.initialize()`，随后 `list_tools()` 的结果缓存为 `ToolSpec` 列表。请求路径上只做 `session.call_tool()`。
- **`InMemoryRegistry`** —— 构造时接收 `dict[str, Callable]`，返回固定桩数据。

`call_tool` 在两个实现里共用同一段包装逻辑（`tools/base.py` 的 `timed_call()`）：捕获全部异常转成 `ToolResult(ok=False, error=...)`、计时、追加一条 `ToolCallLog`。

这一层同时承担三件事，所以必须是个显式接缝而不是散落的调用：
1. `方案.md` 第七节"工具选择准确率""参数正确率"的数据来源；
2. "第二个工具失败怎么降级"的统一 catch 点；
3. 行为测试注入桩工具的唯一入口（测试不需要真的起子进程）。

**StdioMcpRegistry 的三个硬性约束**（踩中任一即表现为"server 起来了但零工具"或连接被静默关闭）：

- `command` 用 `sys.executable`，不用字符串 `"python"` —— uv 虚拟环境下 PATH 上的 `python` 未必指向项目环境。
- `cwd` 必须是 `mcp_servers/navigation` 的绝对路径。
- server 进程内**禁止 `print()` 到 stdout**。协议帧走同一条流，任何一行杂质都会让客户端判定连接异常。日志一律 `logging`（stderr）。

### 5.2 `mcp_servers/navigation`

```python
server = MCPServer("navigation")

PAGE_REGISTRY: list[PageEntry] = [ ... ]   # 方案.md 第五节的四条：课表/成绩/补考/图书馆

@server.tool()
async def list_pages() -> list[PageEntry]:
    """返回所有已注册页面及其能力描述与关键词。"""

@server.tool()
async def resolve_page(intent: str, params: dict[str, str] | None = None) -> ResolvedPage:
    """把一句意图映射到具体页面路径，返回 {path, title, capabilities}。"""
```

`resolve_page` 今晚用关键词命中（`intent` 与 `keywords` 交并集打分），**不做向量检索**。函数签名与返回结构按向量版设计，内部实现换掉即可，调用方无感。

数据放在 `PAGE_REGISTRY` 一个常量里，前后端共用同一份页面清单——`frontend/src/router/index.ts` 的路径必须与之逐条对齐，这是两半之间唯一的隐式耦合，第 8 节用一条测试把它钉住。

### 5.3 LLM Provider

```python
class RouteDecision(BaseModel):
    intent: str
    tool_name: str | None
    tool_args: dict[str, Any]
    confidence: float

class LLMProvider(Protocol):
    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision: ...
    async def stream_answer(self, user_input: str, state: "AgentState") -> AsyncIterator[str]: ...
```

- **`FakeProvider`** —— 对 `user_input` 做关键词规则匹配，产出确定的 `RouteDecision`；`stream_answer` 用固定模板把工具结果切成若干小段依次 yield（模拟打字机节奏）。无 Key、无网络、结果确定。
- **`OpenAICompatProvider`** —— 一份代码服务通义千问 DashScope compatible-mode 与 DeepSeek，差异全在 `base_url` / `model` / `api_key` 三个环境变量。`route()` 走 tool calling 并强制解析为 `RouteDecision`；`stream_answer()` 透传流式增量。

选择器在 `config.py`：`LLM_PROVIDER=fake|openai_compat`。缺 Key 而选了 `openai_compat` 时，启动即报错并提示改用 fake，而不是第一个请求才失败。

### 5.4 LangGraph 图

```python
import operator
from typing import Annotated, Any, TypedDict

class AgentState(TypedDict):
    user_input: str
    session_id: str
    intent: str | None
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_results: dict[str, Any]
    answer: str
    nav_card: dict[str, Any] | None
    steps: Annotated[list[str], operator.add]   # 累加 reducer，见下
    error: str | None
```

```
START → router ──(cond: tool_name is not None and registry 有该工具)──→ tool_executor → generator → END
                     └──(else)──────────────────────────────────────→ generator → END

graph = workflow.compile().with_config(recursion_limit=8)
```

三个节点各自单一职责：

- `router`：`LLMProvider.route()` + 校验 `tool_name` 确实在 `list_tools()` 结果内（不在则置空并记 `error`，走无工具分支）。这是防 LLM 幻觉出不存在工具的第一道闸。
- `tool_executor`：`registry.call_tool()`，结果写 `state["tool_results"]`。`ok=False` 时不抛异常，写 `error` 后仍流向 `generator`，由 generator 输出降级话术。
- `generator`：组合文本与跳转卡片，`astream` 逐块产出。

**每个节点返回值里带 `"steps": ["<节点名>"]`。** 因为 `steps` 声明了 `operator.add` reducer，LangGraph 会把各节点的增量累加成完整执行轨迹，而不是相互覆盖。这里不能改用 `state["steps"].append(...)` 再原样返回：那是在 mutate 上游同一个 list 对象，配合默认（replace）语义时轨迹会重复或丢失，是一类难查的 LangGraph 状态污染。**执行路径异常检测**（同一节点连续 >3 次、跳过必要节点、Generator 回退 Router）到时有现成轨迹可解析，成本是每节点一个键。

`recursion_limit=8` 兜住无限循环，超限由 `api/chat.py` 捕获并转 `error` 事件。

### 5.5 SSE 事件契约

| event | data | 前端处理 |
|---|---|---|
| `token` | `{"text": "…"}` | 追加到当前气泡 |
| `tool_call` | `{"name","args","ok","error","latency_ms"}` | 气泡上方折叠状态条："正在调用 navigation.resolve_page（38ms）" |
| `nav_card` | `{"path","title","reason"}` | 渲染可点击卡片 → `router.push(path)` |
| `done` | `{"message_id","steps":[…],"session_id"}` | 结束流；`steps` 存入本地操作日志面板 |
| `error` | `{"code","message"}` | 气泡内错误态 |

后端用 `StreamingResponse(media_type="text/event-stream")` 手工帧化为 `event: <名>\ndata: <json>\n\n`（一帧以空行结束，即两个换行），并带 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`（后者防止将来 Nginx 缓冲把流式变成一次性返回）。

`tool_call` 事件从第一版就推给前端：后端本来就产生了这个数据，而它把"Agent 真的在调用工具"变成可见证据——这是本项目区别于问答型 Demo 的核心展示点。

### 5.6 前端组件边界

- **`useChatStream()` composable 是唯一的网络出口**，持有 `messages`、`streaming`、`pendingCard`、`session_id` 与 `AbortController`。组件不发请求，只消费它暴露的响应式状态。停止生成 = `abort()`。
- **`lib/sse.ts`** —— 纯函数解析器：输入 `Uint8Array` 增量，输出完整事件帧。它必须与 Vue 解耦，因为它是今晚最需要单测的一段（跨 chunk 的半截帧、`\n\n` 分界、UTF-8 多字节被切断）。
- **`ChatBox.vue`** 渲染 `MessageList` + 输入框；`MessageBubble.vue` 用 `markdown-it` + `highlight.js` 渲染，`html: false` 关原始 HTML（模型输出直插 DOM 是 XSS 入口）。
- **`FloatingBall.vue`** 固定定位，首次展开显示免责声明。
- **仿真页** `ScheduleView.vue` / `GradesView.vue` 为静态占位，含正确的页面标题与一段说明文字，路径 `/academic/schedule`、`/academic/grades`。

### 5.7 持久化

SQLite 单文件 `backend/data/campus.db`，启动时 `CREATE TABLE IF NOT EXISTS`。三张表：

- `conversations(id, session_id, created_at)`
- `messages(id, conversation_id, role, content, created_at)`
- `tool_calls(id, conversation_id, tool_name, args_json, ok, error, latency_ms, steps_json, created_at)`

`tool_calls` 是今晚唯一的真实产出诉求：让行为测试与路径异常检测脚本在明天有真实历史数据可读，而不是从零造样本。`InMemoryRegistry` 走同一张表，因此测试产生的记录与真实链路同构。

写入失败不得中断对话流——repository 调用包 try-catch，失败记 error 日志后继续。

---

## 6. 横切约束

### 6.1 安全（今晚必须就位，后补要改所有调用点）

- **`student_id` 只从会话取，绝不从请求体接受。** `ChatRequest` 模型不含 `student_id` 字段，从 schema 层面堵死参数篡改。今晚用固定的仿真用户 `20230001`（`config.py` 常量），但这个值的来源必须是 session 而非 client。`方案.md` 第七节的越权测试用例依赖这条接缝存在。
- 工具参数在 `call_tool` 前按 `ToolSpec.input_schema` 做一次 pydantic 校验，不合法直接 `ok=False`，不下发给 MCP。
- API Key 只进 `.env`（`.gitignore` 收录），`.env.example` 进仓库。前端不出现任何 Key。
- 启用 CORS 时显式列出 `http://localhost:5173`，不用 `allow_origins=["*"]`。
- Prompt 注入本切片不做检测，但 `router` 节点把工具清单限定为 `list_tools()` 返回值，LLM 无法发明未注册工具——这已是当前最有效的约束。

### 6.2 环境与构建

- Python 一律 `uv`：`uv venv` + `uv sync`，不用裸 `pip install` 进全局。
- 国内网络装包慢，M1 阶段用一次 `uv pip install mcp` 实测连通性再定镜像。候选：清华 `https://pypi.tuna.tsinghua.edu.cn/simple`、阿里 `https://mirrors.aliyun.com/pypi/simple/`，写进两个 `pyproject.toml` 的 `[[tool.uv.index]]`；npm 侧候选 `https://registry.npmmirror.com`，用 `npm config set registry` 或项目内 `.npmrc`。
- 前后端各自的 `.venv` / `node_modules` 均入 `.gitignore`；`backend/data/*.db` 与 `.env` 同样不入库。
- Docker 全程不参与本切片；阶段四再走 `wsl docker compose`。

### 6.3 可观测

- 每个请求生成 `request_id`，贯穿日志、`done` 事件与 `tool_calls` 表，便于串起一次链路。
- 节点耗时、工具耗时、首 token 延迟三项打日志。首 token 延迟是流式体验的唯一有效指标，必须在有真 LLM 时能读到。

---

## 7. 今晚里程碑

| # | 内容 | 验收（可执行、可判定） | 估时 |
|---|---|---|---|
| M1 | `git init` + 远端基线合并（已完成）+ 后端 uv 骨架 + 前端 Vite 骨架 + `.gitignore` | 后端 `uv run uvicorn` 起 :8000，`GET /health` 返回 200；前端 `npm run dev` 起 :5173 显示 Home | 20min |
| M2 | `mcp_servers/navigation`：`PAGE_REGISTRY` + `list_pages` + `resolve_page` | `uv run python scripts/check_mcp.py` 完成握手并打印 2 个工具；`resolve_page("查成绩")` 返回 `/academic/grades` | 40min |
| M3 | `tools/base.py` + `stdio_mcp.py` + `inmemory.py`，lifespan 拉起与关闭 | FastAPI 启动日志出现工具清单；`GET /debug/tools` 返回缓存的 `ToolSpec`；调一次 `resolve_page` 拿到结构化 `ToolResult` | 40min |
| M4 | `llm/fake.py` + LangGraph 三节点图 + `POST /chat` SSE | `curl -N -X POST` 看到完整事件序列 `tool_call → token* → nav_card → done`，`done.steps` == `["router","tool_executor","generator"]` | 50min |
| M5 | 悬浮球 + ChatBox + `lib/sse.ts` + Markdown + 跳转卡片 + 2 仿真页 | 浏览器输入"这学期上什么课" → 打字机输出 → 点卡片 → 地址栏变 `/academic/schedule` 且页面渲染 | 30min |
| M6 | `openai_compat.py` 接真模型 + SQLite 落 `tool_calls` + 3 条用例手测 + 提交 | 同一用例在 `LLM_PROVIDER=fake` 与真模型下都产出正确卡片；`sqlite3 campus.db "select …"` 有记录 | 30min |

合计约 3.5 小时。

**风险排序**：M2、M3 是今晚唯二"卡住则整体崩"的环节（MCP v2 陌生 API + Windows stdio 子进程）。因此 M2 的独立验证脚本 `scripts/check_mcp.py` 必须先做、必须先跑绿，再进 M3——不要等到前后端联调时才回头发现 stdio 握手不通。M4 之后的风险都是可增量调试的。

**M6 允许降级**：若今晚真模型 Key 不可用，M6 的验收改为 `FakeProvider` 全绿 + `openai_compat.py` 写完并通过 import 与结构检查，Key 到位后单独验证。

---

## 8. 测试策略（本切片）

范围与 `方案.md` 第七节的完整体系无关，只覆盖今晚这份链路：

- **单测**：`lib/sse.ts` 解析器（半截帧、多帧粘连、UTF-8 跨 chunk 切断）；`resolve_page` 关键词命中（含 4 条注册页与 1 条未命中）；`router` 节点对未注册工具名的拦截。
- **集成测**：`InMemoryRegistry` + `FakeProvider` 跑完整图，断言 `steps` 序列与 `nav_card.path` 正确 —— 不起子进程、不打网络，这是明天 50 条行为用例的宿主。
- **契约测**：一条脚本断言 `PAGE_REGISTRY` 里每个 `path` 在 `frontend/src/router/index.ts` 中都有对应路由，把第 5.2 节声明的隐式耦合钉住。
- **手测**：M2/M3/M4/M5 的验收列。

Playwright E2E 与 RAGAS 属于后续 spec。

---

## 9. 明确不做（本切片）

Page Agent iframe 注入、五级元素定位降级、操作确认弹窗、操作回放、ChromaDB 语义路由与向量匹配、其余 4 个 MCP Server（knowledge / academic / news / page-control）、MySQL、Redis、`grader` 与 `rewrite` 节点、多工具条件编排、Docker 化、RAGAS、越权测试用例集。

---

## 10. 后续阶段接入点

本切片刻意留下的接缝，使后续工作成为增量而非重写：

| 后续工作 | 接入方式 |
|---|---|
| 语义路由（向量匹配） | 换 `resolve_page` 内部实现 + 加 ChromaDB 依赖；`ToolSpec` 与调用方不变 |
| 多工具条件编排 | 往 `agent/graph.py` 加 `grader` 节点与 `add_conditional_edges`；`tool_results` 已是 dict 累加结构 |
| 新增 MCP Server | `config.py` 的 server 清单加一条 `StdioServerParameters`，`StdioMcpRegistry` 天然支持多 session |
| Page Agent | 新增 `mcp_servers/page_agent`，其"前端执行"半段走 `useChatStream` 已有的双向通道（新增 `POST /confirm` + 前端回传结果）；`/chat` 侧协议不动 |
| Agent 行为测试体系 | 以第 8 节集成测为宿主，加参数化用例文件；`tool_calls` 表即埋点数据源 |
| MySQL / Redis | 实现 `ConversationRepository` 协议的另一个类；`tools/registry` 之上加 Redis 版 session store |
| 越权防护测试 | 第 6.1 节"`student_id` 只从会话取"已是其前置结构 |

---

## 11. 完成定义

今晚收工前，以下每一条都能被现场演示或被一条命令验证，缺一不算完成：

1. 前端首页可打开，悬浮球点开聊天窗，首次有免责声明。
2. 输入"我想看看这学期要上什么课" → 打字机式流式回答 → 出现"课表查询"跳转卡片 → 点击后路由真的到 `/academic/schedule`。
3. 回答期间前端可见 `正在调用 navigation.resolve_page（…ms）` 状态条。
4. 输入一句与所有注册页面无关的话 → 不出卡片，`generator` 给出兜底回答（验证条件边两条路径）。
5. `LLM_PROVIDER` 改为 `openai_compat` 且 Key 可用时，同一输入得到语义一致但措辞不同的真实回答。
6. `curl -N` 直接打后端能复现完整事件序列，证明前端不是链路正确性的必要环节。
7. SQLite `tool_calls` 表中有上述对话的记录，含 `steps_json`。
8. 仓库已提交并推送至 `origin/main`，CI 无关，但 `git status` 干净且 `.env` 未被跟踪。
