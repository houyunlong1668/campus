# 校园浏览器 Agent MVP（M1–M6）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 今晚交付最小端到端链路：前端输入一句话 → LangGraph 路由 → MCP 工具调用 → SSE 流式返回文本与跳转卡片 → 前端真实跳转仿真页。

**Architecture:** 前端 Vue 3 + Vite（fetch + ReadableStream 解析 SSE）；后端 FastAPI，lifespan 内经 AsyncExitStack 拉起 navigation MCP server（stdio 子进程，独立 uv 项目）；LangGraph 单图 `router →(条件边)→ tool_executor → generator`；LLM 可插拔（fake / openai_compat）；SQLite 落 `tool_calls` 表。

**Tech Stack:** Vue 3 + Vite + Element Plus + markdown-it + highlight.js + vitest；Python 3.11+ / uv / FastAPI / LangGraph / mcp>=2.2,<3 / aiosqlite / openai。

**Spec:** `docs/superpowers/specs/2026-09-18-campus-agent-mvp-design.md`（本计划逐条对应该文档第 7 节的 M1–M6 里程碑与第 8 节测试策略）

## 全局约束

以下每条对全部任务生效，抄自 spec 第 6 节与第 5 节：

- `mcp` 依赖两侧一律 `mcp>=2.2,<3`，server 类从 `mcp.server` 导入 `MCPServer`（不用已废弃的 `FastMCP` 路径）。
- `mcp_servers/navigation/server.py` 内**禁止 `print()` 到 stdout**，日志一律走 `logging`（stderr）。协议帧与杂质共用 stdout。
- stdio 子进程三硬约束：`command=sys.executable`（不用字符串 `"python"`）；`cwd` 为 `mcp_servers/navigation` 绝对路径；启动期完成 `session.initialize()` 并缓存 `list_tools()`。
- `student_id` 只从会话取：`ChatRequest` 模型不得含 `student_id` 字段；今晚固定仿真用户 `20230001`，是 `config.py` 常量而非请求体字段。
- 工具参数在 `call_tool` 前按 `ToolSpec.input_schema` 校验，不合法直接 `ok=False`，不下发给 MCP。
- CORS 显式列 `http://localhost:5173`，禁止 `allow_origins=["*"]`。
- SSE 线格式：每帧 `event: <名>\ndata: <json>\n\n`（以空行结尾），响应头 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`。
- 事件名全集：`token` / `tool_call` / `nav_card` / `done` / `error`，data 结构见 spec 5.5 节，前后端必须一一对应。
- LangGraph 节点返回值一律带 `"steps": ["<节点名>"]`（`steps` 声明 `operator.add` reducer），禁止 `state["steps"].append(...)` 后原样返回。
- 图编译时 `.with_config(recursion_limit=8)`；超限在 `api/chat.py` 捕获转 `error` 事件。
- Python 一律 `uv venv` + `uv sync`；国内网络候选镜像：清华 `https://pypi.tuna.tsinghua.edu.cn/simple`、npm `https://registry.npmmirror.com`（写入 `.npmrc` 与 `[[tool.uv.index]]`）。
- `.gitignore` 必须含：`backend/.venv/`、`mcp_servers/*/.venv/`、`frontend/node_modules/`、`backend/data/*.db`、`.env`。
- 每请求生成 `request_id` 贯穿日志、`done` 事件与 `tool_calls` 表；节点耗时、工具耗时、首 token 延迟打日志。
- Markdown 渲染必须 `html: false`（模型输出直插 DOM 是 XSS 入口）。
- Docker 不参与本切片。

## 文件结构总览

```
backend/                    # 独立 uv 项目
├─ pyproject.toml           # M1 创建；M4/M6 增依赖
└─ app/
   ├─ main.py               # M1 创建（/health、CORS、lifespan）；M3 接 registry；M6 接 db
   ├─ config.py             # M1 创建；M6 增 LLM 选择与 Key 校验
   ├─ schemas.py            # M4 创建（ChatRequest + SSE 事件模型）
   ├─ api/chat.py           # M4 创建（POST /chat、GET /debug/tools）；M6 落库
   ├─ agent/state.py        # M4
   ├─ agent/graph.py        # M4
   ├─ agent/nodes/router.py        # M4
   ├─ agent/nodes/tool_executor.py # M4
   ├─ agent/nodes/generator.py     # M4
   ├─ llm/base.py           # M4（LLMProvider 协议 + RouteDecision）
   ├─ llm/fake.py           # M4
   ├─ llm/openai_compat.py  # M6
   ├─ tools/base.py         # M3（ToolSpec/ToolResult/ToolRegistry + timed_call + 参数校验）
   ├─ tools/stdio_mcp.py    # M3
   ├─ tools/inmemory.py     # M3
   └─ db/engine.py / db/repository.py  # M6
mcp_servers/navigation/     # 独立 uv 项目（M2）
├─ pyproject.toml
└─ server.py                # MCPServer + PAGE_REGISTRY + 2 tools
frontend/                   # M1 创建骨架；M5 填充
└─ src/
   ├─ views/Home.vue / ScheduleView.vue / GradesView.vue
   ├─ components/chat/FloatingBall.vue / ChatBox.vue / MessageList.vue
   │  └─ MessageBubble.vue / NavigationCard.vue
   ├─ composables/useChatStream.ts
   ├─ lib/sse.ts
   ├─ router/index.ts / types.ts / App.vue / main.ts
scripts/
├─ check_mcp.py             # M2
└─ check_routes_contract.py # M5
```

---

### Task M1: 仓库基线 — 后端 uv 骨架 + 前端 Vite 骨架

**对应里程碑：** M1（估时 20min）

**Files:**
- Create: `.gitignore`、`.npmrc`
- Create: `backend/pyproject.toml`、`backend/app/__init__.py`、`backend/app/config.py`、`backend/app/main.py`
- Create: `frontend/`（`npm create vite` 生成后修改）

**Interfaces:**
- Produces: `GET /health` 返回 `{"status":"ok"}`（M3/M4 全部手测都先依赖它）；`backend/app/config.py` 的 `Settings`（M3/M6 扩字段）；前端 dev server 起在 `:5173` 且 `/` 渲染 Home。

- [ ] **Step 1: 写 `.gitignore` 与 `.npmrc`**

`.gitignore`（追加到既有文件，若无则新建）：

```
# Python
__pycache__/
*.pyc
backend/.venv/
mcp_servers/*/.venv/
# Node
frontend/node_modules/
frontend/dist/
# Local data & secrets
backend/data/*.db
.env
```

`.npmrc`（仓库根）：

```
registry=https://registry.npmmirror.com
```

- [ ] **Step 2: 建后端 uv 骨架并实测镜像连通性**

```bash
mkdir -p backend/app
cd backend
uv venv
uv pip install fastapi "uvicorn[standard]" pydantic pydantic-settings
```

若上一步超时，改用清华镜像再试：`uv pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple fastapi "uvicorn[standard]" pydantic pydantic-settings`，并把镜像写进后续 `pyproject.toml` 的 `[[tool.uv.index]]`。

`backend/pyproject.toml`：

```toml
[project]
name = "campus-agent-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
]

[tool.uv]
package = false
```

`backend/app/config.py`：

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origin: str = "http://localhost:5173"
    # M6 会在此追加：llm_provider / openai_base_url / openai_model / openai_api_key
    # 及 navigation_server_dir / sqlite_path / fake_student_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/main.py`：

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M3 在此拉起 StdioMcpRegistry；M6 在此 init_db
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="campus-agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 3: 起后端验证**

```bash
cd backend
uv run uvicorn app.main:app --port 8000
```

另开一个终端：`curl -s http://localhost:8000/health`，期望输出 `{"status":"ok"}`。验证后停掉 uvicorn。

- [ ] **Step 4: 建前端 Vite 骨架**

```bash
cd <仓库根>
npm create vite@latest frontend -- --template vue-ts
cd frontend
npm install
npm install element-plus markdown-it highlight.js
npm install -D vitest @types/markdown-it
```

`frontend/vite.config.ts` 中追加 dev 代理（避免开发期 CORS，后端 CORS 配置仍保留给非代理场景）：

```ts
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/chat": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/debug": "http://localhost:8000",
    },
  },
})
```

M1 阶段先只保证 `npm run dev` 起在 `:5173` 且默认模板页可打开；`App.vue`/`main.ts` 的正式内容在 M5 重写。若 `npm create vite` 交互式询问覆盖等，选 Vue + TypeScript 模板即可。

- [ ] **Step 5: 提交**

```bash
git add .gitignore .npmrc backend/ frontend/package.json frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/src/ frontend/public/
git commit -m "feat(M1): 后端 uv 骨架 + 前端 Vite 骨架，/health 可达"
```

### Task M2: `mcp_servers/navigation` — PAGE_REGISTRY + 2 个工具 + 独立握手脚本

**对应里程碑：** M2（估时 40min）。**这是今晚两个"卡住则整体崩"环节中的第一个**，必须先做 `scripts/check_mcp.py` 并跑绿，再进 M3。

**Files:**
- Create: `mcp_servers/navigation/pyproject.toml`、`mcp_servers/navigation/server.py`
- Create: `mcp_servers/navigation/tests/test_resolve_page.py`
- Create: `scripts/check_mcp.py`

**Interfaces:**
- Produces: `PAGE_REGISTRY: list[PageEntry]`，其中 `PageEntry(path, title, keywords, capabilities)`，四条固定注册页（路径被 M5 契约测试与前端 router 钉住）：
  - `/academic/schedule` 课表查询 keywords `["课表","课程","上什么课","选课"]`
  - `/academic/grades` 成绩查询 keywords `["成绩","分数","绩点","查分"]`
  - `/academic/makeup` 补考重修查询 keywords `["补考","重修"]`
  - `/library` 图书馆服务 keywords `["图书馆","借书","还书","图书"]`
- Produces: 工具 `list_pages()` 与 `resolve_page(intent: str, params: dict | None = None) -> ResolvedPage`；`resolve_page` 无命中时 `raise ValueError("no matching page")`。
- Consumes: 无（叶子任务，只依赖 `mcp>=2.2,<3`）。

- [ ] **Step 1: 写 pyproject 并装依赖**

`mcp_servers/navigation/pyproject.toml`：

```toml
[project]
name = "campus-navigation-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.2,<3",
    "pydantic>=2.7",
]

[dependency-groups]
dev = ["pytest>=8"]

[tool.uv]
package = false
```

```bash
cd mcp_servers/navigation
uv sync
```

- [ ] **Step 2: 写失败测试**

`mcp_servers/navigation/tests/test_resolve_page.py`：

```python
import pytest

from server import PAGE_REGISTRY, resolve_page_impl


def test_registry_has_four_pages():
    assert len(PAGE_REGISTRY) == 4
    paths = {p.path for p in PAGE_REGISTRY}
    assert paths == {"/academic/schedule", "/academic/grades", "/academic/makeup", "/library"}


@pytest.mark.parametrize(
    ("intent", "expected_path"),
    [
        ("我想看看这学期要上什么课", "/academic/schedule"),
        ("查一下我的成绩", "/academic/grades"),
        ("补考时间是什么时候", "/academic/makeup"),
        ("图书馆还能借书吗", "/library"),
    ],
)
def test_keyword_hit(intent, expected_path):
    resolved = resolve_page_impl(intent)
    assert resolved.path == expected_path


def test_no_match_raises():
    with pytest.raises(ValueError, match="no matching page"):
        resolve_page_impl("今天天气怎么样")
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd mcp_servers/navigation
uv run pytest tests/test_resolve_page.py -v
```

期望：失败，报 `ModuleNotFoundError: No module named 'server'`（或 `resolve_page_impl` 未定义）。

- [ ] **Step 4: 实现 server.py**

`mcp_servers/navigation/server.py`：

```python
import logging
from typing import Any

from mcp.server import MCPServer
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)  # stderr，严禁 print 到 stdout

server = MCPServer("navigation")


class PageEntry(BaseModel):
    path: str
    title: str
    keywords: list[str]
    capabilities: list[str]


class ResolvedPage(BaseModel):
    path: str
    title: str
    capabilities: list[str]


PAGE_REGISTRY: list[PageEntry] = [
    PageEntry(
        path="/academic/schedule",
        title="课表查询",
        keywords=["课表", "课程", "上什么课", "选课"],
        capabilities=["查看本学期课表", "按周次筛选课程"],
    ),
    PageEntry(
        path="/academic/grades",
        title="成绩查询",
        keywords=["成绩", "分数", "绩点", "查分"],
        capabilities=["查看各科成绩", "查看 GPA"],
    ),
    PageEntry(
        path="/academic/makeup",
        title="补考重修查询",
        keywords=["补考", "重修"],
        capabilities=["查看补考安排", "查看重修报名"],
    ),
    PageEntry(
        path="/library",
        title="图书馆服务",
        keywords=["图书馆", "借书", "还书", "图书"],
        capabilities=["查询馆藏", "查看借阅记录"],
    ),
]


def resolve_page_impl(intent: str) -> ResolvedPage:
    best: PageEntry | None = None
    best_score = 0.0
    for entry in PAGE_REGISTRY:
        matched = sum(1 for kw in entry.keywords if kw in intent)
        if matched == 0:
            continue
        score = matched / len(entry.keywords)
        if score > best_score:
            best, best_score = entry, score
    if best is None:
        raise ValueError("no matching page for intent")
    return ResolvedPage(path=best.path, title=best.title, capabilities=best.capabilities)


@server.tool()
async def list_pages() -> list[PageEntry]:
    """返回所有已注册页面及其能力描述与关键词。"""
    return PAGE_REGISTRY


@server.tool()
async def resolve_page(intent: str, params: dict[str, Any] | None = None) -> ResolvedPage:
    """把一句意图映射到具体页面路径，返回 {path, title, capabilities}。"""
    logging.info("resolve_page intent=%s params=%s", intent, params)
    return resolve_page_impl(intent)


if __name__ == "__main__":
    server.run(transport="stdio")
```

注意：模块内只有 `logging` 输出到 stderr；`server.run` 是唯一的 stdio 占用者。

- [ ] **Step 5: 跑测试确认通过**

```bash
cd mcp_servers/navigation
uv run pytest tests/test_resolve_page.py -v
```

期望：6 条全部 PASS。

- [ ] **Step 6: 写并跑独立握手脚本**

`scripts/check_mcp.py`（在**仓库根**运行，用的是 navigation 自己的 venv）：

```python
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp_servers" / "navigation"


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,  # 硬约束：不用字符串 "python"
        args=["server.py"],
        cwd=str(SERVER_DIR),     # 硬约束：绝对路径
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", names)
            assert "list_pages" in names and "resolve_page" in names

            result = await session.call_tool("resolve_page", {"intent": "查成绩"})
            print("resolve_page('查成绩') ->", result.content[0].text)
            assert "/academic/grades" in result.content[0].text


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
cd mcp_servers/navigation
uv run python ../../scripts/check_mcp.py
```

期望输出：

```
tools: ['list_pages', 'resolve_page']
resolve_page('查成绩') -> {... 含 "/academic/grades" ...}
```

**跑绿之前不进 M3。** 若握手失败，对照全局约束三条硬约束逐条排查（最常见：`cwd` 相对路径、server 内残留 print）。

- [ ] **Step 7: 提交**

```bash
git add mcp_servers/navigation/ scripts/check_mcp.py
git commit -m "feat(M2): navigation MCP server，PAGE_REGISTRY + list_pages + resolve_page，握手脚本跑绿"
```

### Task M3: 后端 `tools/` 接缝 — ToolRegistry 协议 + stdio/inmemory 双实现 + lifespan

**对应里程碑：** M3（估时 40min）。**今晚第二个"卡住则整体崩"环节**：M2 已证明 stdio 握手可通，本任务把它接进 FastAPI 生命周期。

**Files:**
- Create: `backend/app/tools/__init__.py`、`backend/app/tools/base.py`、`backend/app/tools/stdio_mcp.py`、`backend/app/tools/inmemory.py`
- Create: `backend/tests/test_tools.py`
- Modify: `backend/pyproject.toml`（增 `mcp>=2.2,<3`、pytest 依赖）、`backend/app/config.py`（增 `navigation_server_dir`）、`backend/app/main.py`（lifespan 拉起 registry、`GET /debug/tools`）

**Interfaces:**
- Produces（M4 全靠这组签名）：
  ```python
  class ToolSpec(BaseModel):
      name: str
      description: str
      input_schema: dict[str, Any]

  class ToolResult(BaseModel):
      ok: bool
      data: Any | None = None
      error: str | None = None
      latency_ms: int

  class ToolRegistry(Protocol):
      async def list_tools(self) -> list[ToolSpec]: ...
      async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult: ...

  async def timed_call(fn: Callable[[], Awaitable[Any]]) -> ToolResult  # 计时 + 全异常转 ok=False
  def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> tuple[bool, str | None]
  def build_registry(settings) -> AsyncIterator[ToolRegistry]  # lifespan 用
  ```
- Produces: `app.state.registry: ToolRegistry`；`GET /debug/tools -> {"tools": [ToolSpec, ...]}`。
- Consumes: M2 的 `mcp_servers/navigation`（经 stdio，不 import 其代码——两个独立 venv）。

- [ ] **Step 1: 增依赖并写失败测试**

`backend/pyproject.toml` dependencies 追加 `"mcp>=2.2,<3"`，并追加：

```toml
[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

```bash
cd backend
uv sync
```

`backend/tests/test_tools.py`：

```python
import pytest

from app.tools.base import ToolResult, validate_args
from app.tools.inmemory import InMemoryRegistry


class TestValidateArgs:
    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": ["intent"],
    }

    def test_valid(self):
        ok, err = validate_args(self.schema, {"intent": "查成绩"})
        assert ok and err is None

    def test_missing_required(self):
        ok, err = validate_args(self.schema, {})
        assert not ok and "intent" in err

    def test_wrong_type(self):
        ok, err = validate_args(self.schema, {"intent": 123})
        assert not ok and err


class TestInMemoryRegistry:
    async def test_list_and_call(self):
        async def fake_resolve(intent: str):
            return {"path": "/academic/grades"}

        registry = InMemoryRegistry(
            {
                "resolve_page": {
                    "spec": {
                        "name": "resolve_page",
                        "description": "解析页面",
                        "input_schema": TestValidateArgs.schema,
                    },
                    "fn": fake_resolve,
                }
            }
        )
        tools = await registry.list_tools()
        assert [t.name for t in tools] == ["resolve_page"]

        good = await registry.call_tool("resolve_page", {"intent": "查成绩"})
        assert isinstance(good, ToolResult) and good.ok and good.data["path"] == "/academic/grades"
        assert good.latency_ms >= 0

        bad = await registry.call_tool("resolve_page", {"intent": 123})
        assert not bad.ok and bad.error  # 参数校验拦截，fn 未执行

        missing = await registry.call_tool("nope", {})
        assert not missing.ok
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
uv run pytest tests/test_tools.py -v
```

期望：`ModuleNotFoundError: No module named 'app.tools'`。

- [ ] **Step 3: 实现 `tools/base.py`**

`backend/app/tools/base.py`：

```python
import time
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel, create_model


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolResult(BaseModel):
    ok: bool
    data: Any | None = None
    error: str | None = None
    latency_ms: int


class ToolRegistry(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult: ...


async def timed_call(fn: Callable[[], Awaitable[Any]]) -> ToolResult:
    start = time.perf_counter()
    try:
        data = await fn()
        return ToolResult(ok=True, data=data, latency_ms=int((time.perf_counter() - start) * 1000))
    except Exception as exc:  # 统一降级点：任何工具异常不向上抛
        return ToolResult(
            ok=False, error=f"{type(exc).__name__}: {exc}",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )


_TYPE_MAP = {
    "string": str, "integer": int, "number": float,
    "boolean": bool, "object": dict, "array": list,
}


def _args_model(schema: dict[str, Any]):
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = {}
    for name, spec in props.items():
        py_type = _TYPE_MAP.get(spec.get("type", "string"), str)
        if name not in required:
            py_type = py_type | None
        default = ... if name in required else None
        fields[name] = (py_type, default)
    return create_model("ToolArgs", **fields)


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        _args_model(schema)(**args)
        return True, None
    except Exception as exc:
        return False, f"参数校验失败: {exc}"
```

`backend/app/tools/__init__.py`：空文件。

- [ ] **Step 4: 实现 `tools/inmemory.py`**

`backend/app/tools/inmemory.py`：

```python
from typing import Any, Awaitable, Callable

from .base import ToolRegistry, ToolResult, ToolSpec, timed_call, validate_args


class InMemoryRegistry(ToolRegistry):
    """测试与降级用：构造时接收 {name: {"spec": ..., "fn": ...}}。"""

    def __init__(self, tools: dict[str, dict[str, Any]]):
        self._tools = tools

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(**entry["spec"]) for entry in self._tools.values()]

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        entry = self._tools.get(name)
        if entry is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
        ok, err = validate_args(entry["spec"]["input_schema"], args)
        if not ok:
            return ToolResult(ok=False, error=err, latency_ms=0)
        fn: Callable[..., Awaitable[Any]] = entry["fn"]
        return await timed_call(lambda: fn(**args))
```

- [ ] **Step 5: 实现 `tools/stdio_mcp.py`**

`backend/app/tools/stdio_mcp.py`：

```python
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .base import ToolRegistry, ToolResult, ToolSpec, timed_call, validate_args


class StdioMcpRegistry(ToolRegistry):
    def __init__(self, session: ClientSession):
        self._session = session
        self._specs: list[ToolSpec] = []

    async def initialize(self) -> None:
        await self._session.initialize()
        listed = await self._session.list_tools()
        self._specs = [
            ToolSpec(name=t.name, description=t.description or "", input_schema=t.inputSchema or {})
            for t in listed.tools
        ]

    async def list_tools(self) -> list[ToolSpec]:
        return self._specs

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = next((s for s in self._specs if s.name == name), None)
        if spec is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
        ok, err = validate_args(spec.input_schema, args)
        if not ok:
            return ToolResult(ok=False, error=err, latency_ms=0)

        async def invoke():
            result = await self._session.call_tool(name, args)
            return result.content[0].text  # JSON 字符串，generator 负责 loads

        return await timed_call(invoke)


@asynccontextmanager
async def stdio_registry(server_dir: Path):
    """lifespan 用：拉起 MCP 子进程，退出时随 AsyncExitStack 关闭。"""
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        params = StdioServerParameters(
            command=sys.executable,       # 硬约束
            args=["server.py"],
            cwd=str(server_dir.resolve()), # 硬约束：绝对路径
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        registry = StdioMcpRegistry(session)
        await registry.initialize()
        yield registry
```

- [ ] **Step 6: 接进 config 与 main，跑测试**

`backend/app/config.py` 的 `Settings` 追加：

```python
    navigation_server_dir: Path = Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "navigation"
```

`backend/app/main.py` 改为：

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .tools.base import ToolRegistry
from .tools.stdio_mcp import stdio_registry

logger = logging.getLogger("campus-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with stdio_registry(settings.navigation_server_dir) as registry:
        app.state.registry = registry
        logger.info("MCP tools ready: %s", [t.name for t in await registry.list_tools()])
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="campus-agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/debug/tools")
    async def debug_tools():
        registry: ToolRegistry = app.state.registry
        return {"tools": [t.model_dump() for t in await registry.list_tools()]}

    return app


app = create_app()
```

```bash
cd backend
uv run pytest tests/test_tools.py -v
```

期望：6 条全部 PASS。

- [ ] **Step 7: 起服务手测**

```bash
cd backend
uv run uvicorn app.main:app --port 8000
```

另开终端：

```bash
curl -s http://localhost:8000/debug/tools
```

期望：启动日志出现 `MCP tools ready: ['list_pages', 'resolve_page']`；curl 返回含两个工具的 JSON。

- [ ] **Step 8: 提交**

```bash
git add backend/ 
git commit -m "feat(M3): ToolRegistry 接缝，stdio/inmemory 双实现，lifespan 拉起 MCP 子进程"
```

### Task M4: `llm/fake.py` + LangGraph 三节点图 + `POST /chat` SSE

**对应里程碑：** M4（估时 50min）。M4 之后所有风险都是可增量调试的。

**Files:**
- Create: `backend/app/schemas.py`、`backend/app/llm/__init__.py`、`backend/app/llm/base.py`、`backend/app/llm/fake.py`
- Create: `backend/app/agent/__init__.py`、`backend/app/agent/state.py`、`backend/app/agent/nodes/__init__.py`、`backend/app/agent/nodes/router.py`、`backend/app/agent/nodes/tool_executor.py`、`backend/app/agent/nodes/generator.py`、`backend/app/agent/graph.py`
- Create: `backend/app/api/__init__.py`、`backend/app/api/chat.py`
- Create: `backend/tests/test_graph.py`
- Modify: `backend/pyproject.toml`（增 `langgraph>=0.3`）、`backend/app/main.py`（挂 chat router）

**Interfaces:**
- Produces（M6 的 `openai_compat.py` 实现同一协议）：
  ```python
  class RouteDecision(BaseModel):
      intent: str
      tool_name: str | None
      tool_args: dict[str, Any]
      confidence: float

  class LLMProvider(Protocol):
      async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision: ...
      def stream_answer(self, user_input: str, state: AgentState) -> AsyncIterator[str]: ...
  ```
- Produces:
  ```python
  class AgentState(TypedDict):
      user_input: str
      session_id: str
      intent: str | None
      tool_name: str | None
      tool_args: dict[str, Any]
      tool_results: dict[str, Any]
      answer: str
      nav_card: dict[str, Any] | None
      steps: Annotated[list[str], operator.add]
      error: str | None

  def build_graph(provider: LLMProvider, registry: ToolRegistry) -> CompiledGraph  # recursion_limit=8
  def sse_frame(event: str, data: dict[str, Any]) -> str  # "event: <名>\ndata: <json>\n\n"
  POST /chat -> StreamingResponse(text/event-stream)  # 事件序列见下
  ```
- Produces SSE 事件序（M5 前端按此实现）：`tool_call?`（调了工具才有）→ `token*` → `nav_card?` → `done`；异常时 `error`。
  - `tool_call` data：`{"name","args","ok","error","latency_ms"}`
  - `nav_card` data：`{"path","title","reason"}`
  - `done` data：`{"message_id","steps":[...],"session_id"}`
  - `token` data：`{"text":"..."}`；`error` data：`{"code","message"}`
- Consumes: M3 的 `ToolRegistry` / `timed_call` / `validate_args`。

- [ ] **Step 1: 增依赖并写失败集成测试**

`backend/pyproject.toml` dependencies 追加 `"langgraph>=0.3"`，`uv sync`。

`backend/tests/test_graph.py`：

```python
import pytest

from app.agent.graph import build_graph
from app.agent.nodes.router import router_node
from app.llm.base import RouteDecision
from app.llm.fake import FakeProvider
from app.tools.inmemory import InMemoryRegistry

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string"}, "params": {"type": "object"}},
    "required": ["intent"],
}


@pytest.fixture
def registry():
    async def fake_resolve(intent: str):
        if "成绩" in intent:
            return {"path": "/academic/grades", "title": "成绩查询", "capabilities": ["查看各科成绩"]}
        raise ValueError("no matching page for intent")

    return InMemoryRegistry(
        {
            "resolve_page": {
                "spec": {
                    "name": "resolve_page",
                    "description": "把意图映射到页面",
                    "input_schema": RESOLVE_SCHEMA,
                },
                "fn": fake_resolve,
            }
        }
    )


async def run_graph(graph, user_input: str):
    collected = {"tokens": [], "nav_card": None, "custom": []}
    final = None
    async for mode, payload in graph.astream(
        {"user_input": user_input, "session_id": "s-test",
         "intent": None, "tool_name": None, "tool_args": {},
         "tool_results": {}, "answer": "", "nav_card": None, "steps": [], "error": None},
        stream_mode=["custom", "values"],
    ):
        if mode == "custom":
            collected["custom"].append(payload)
            if payload[0] == "token":
                collected["tokens"].append(payload[1]["text"])
            elif payload[0] == "nav_card":
                collected["nav_card"] = payload[1]
        else:
            final = payload
    return collected, final


class TestHappyPath:
    async def test_full_chain(self, registry):
        graph = build_graph(FakeProvider(), registry)
        collected, final = await run_graph(graph, "这学期上什么课")
        assert final["steps"] == ["router", "tool_executor", "generator"]
        assert collected["nav_card"]["path"] == "/academic/schedule"
        assert "".join(collected["tokens"])  # 有文本输出
        tool_events = [c for c in collected["custom"] if c[0] == "tool_call"]
        assert tool_events and tool_events[0][1]["ok"] is True

    async def test_fallback_no_tool(self, registry):
        graph = build_graph(FakeProvider(), registry)
        collected, final = await run_graph(graph, "今天天气怎么样")
        assert final["steps"] == ["router", "generator"]
        assert collected["nav_card"] is None
        assert final["tool_name"] is None


class TestRouterGuards:
    async def test_unknown_tool_blocked(self, registry):
        class HallucinatingProvider(FakeProvider):
            async def route(self, user_input, tools):
                return RouteDecision(intent="x", tool_name="drop_database",
                                     tool_args={}, confidence=0.9)

        graph = build_graph(HallucinatingProvider(), registry)
        collected, final = await run_graph(graph, "随便什么")
        assert final["steps"] == ["router", "generator"]  # 未进 tool_executor
        assert final["error"] and "drop_database" in final["error"]

    async def test_tool_failure_degrades(self, registry):
        graph = build_graph(FakeProvider(), registry)
        # "查成绩" 在 FakeProvider 规则里命中工具，但 registry 的 fake 只对含"成绩"的 intent 返回
        collected, final = await run_graph(graph, "查补考安排")  # 命中规则但 resolve 内部未命中
        assert final["steps"] == ["router", "tool_executor", "generator"]
        tool_events = [c for c in collected["custom"] if c[0] == "tool_call"]
        assert tool_events[0][1]["ok"] is False  # 失败仍走完，降级话术由 generator 出
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
uv run pytest tests/test_graph.py -v
```

期望：`ModuleNotFoundError`（`app.agent` 等不存在）。

- [ ] **Step 3: 实现 schemas 与 llm 基座**

`backend/app/schemas.py`：

```python
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=64)
    # 注意：此处永远没有 student_id 字段——它只从会话取（全局约束）
```

`backend/app/llm/base.py`：

```python
from typing import Any, AsyncIterator, Protocol

from pydantic import BaseModel

from ..tools.base import ToolSpec


class RouteDecision(BaseModel):
    intent: str
    tool_name: str | None
    tool_args: dict[str, Any]
    confidence: float


class LLMProvider(Protocol):
    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision: ...
    def stream_answer(self, user_input: str, state: "AgentState") -> AsyncIterator[str]: ...
```

`backend/app/llm/__init__.py`、`backend/app/agent/__init__.py`、`backend/app/agent/nodes/__init__.py`、`backend/app/api/__init__.py`：均为空文件。

`backend/app/llm/fake.py`：

```python
import asyncio
from typing import Any, AsyncIterator

from ..tools.base import ToolSpec
from .base import RouteDecision

# 命中任一关键词即认为该意图应走 resolve_page；resolve_page 内部再做页面级匹配
_ROUTE_KEYWORDS = ("课表", "课程", "上什么课", "选课", "成绩", "分数", "绩点", "查分",
                   "补考", "重修", "图书馆", "借书", "还书", "图书")


class FakeProvider:
    """规则式 Provider：无 Key、无网络、结果确定。是行为测试的基线。"""

    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision:
        hit = any(kw in user_input for kw in _ROUTE_KEYWORDS)
        if hit and any(t.name == "resolve_page" for t in tools):
            return RouteDecision(
                intent=user_input[:20], tool_name="resolve_page",
                tool_args={"intent": user_input}, confidence=1.0,
            )
        return RouteDecision(intent=user_input[:20], tool_name=None, tool_args={}, confidence=0.0)

    async def stream_answer(self, user_input: str, state: dict[str, Any]) -> AsyncIterator[str]:
        nav = state.get("nav_card")
        error = state.get("error")
        if nav:
            text = (f"已为你找到「{nav['title']}」页面。点击下方卡片即可跳转，"
                    f"你也可以在页面内查看详细内容。")
        elif error:
            text = (f"这次调用没有成功（{error}）。你可以换个说法再试一次，"
                    f"或者直接前往对应栏目手动查询。")
        else:
            text = ("我还不会回答这类问题。目前我可以帮你查课表、成绩、补考安排，"
                    "或者提供图书馆服务入口。")
        for i in range(0, len(text), 4):  # 每 4 字一段，模拟打字机节奏
            yield text[i : i + 4]
            await asyncio.sleep(0.01)
```

注意：`LLMProvider` 协议里 `stream_answer` 是无 `async def` 的生成器签名（`def ... -> AsyncIterator[str]`），实现类写成 `async def` + `yield` 的异步生成器函数同样满足调用方 `async for` 的使用方式，pytest 中按调用方语义验证。

- [ ] **Step 4: 实现 agent 状态与三个节点**

`backend/app/agent/state.py`：

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
    steps: Annotated[list[str], operator.add]
    error: str | None
```

`backend/app/agent/nodes/router.py`：

```python
import logging

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.router")


async def router_node(state, provider: LLMProvider, registry: ToolRegistry):
    tools = await registry.list_tools()
    decision = await provider.route(state["user_input"], tools)
    known = {t.name for t in tools}
    if decision.tool_name is not None and decision.tool_name not in known:
        logger.warning("LLM 幻觉工具已拦截: %s", decision.tool_name)
        return {
            "intent": decision.intent,
            "tool_name": None,
            "tool_args": {},
            "error": f"未知工具: {decision.tool_name}",
            "steps": ["router"],
        }
    return {
        "intent": decision.intent,
        "tool_name": decision.tool_name,
        "tool_args": decision.tool_args,
        "steps": ["router"],
    }
```

`backend/app/agent/nodes/tool_executor.py`：

```python
import json
import logging

from langgraph.types import StreamWriter

from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.tool_executor")


async def tool_executor_node(state, registry: ToolRegistry, writer: StreamWriter):
    name = state["tool_name"]
    result = await registry.call_tool(name, state["tool_args"])
    writer(("tool_call", {
        "name": name,
        "args": state["tool_args"],
        "ok": result.ok,
        "error": result.error,
        "latency_ms": result.latency_ms,
    }))
    logger.info("tool=%s ok=%s latency_ms=%s", name, result.ok, result.latency_ms)

    data: dict | None = None
    if result.ok:
        try:
            data = json.loads(result.data) if isinstance(result.data, str) else result.data
        except json.JSONDecodeError:
            result = result.model_copy(update={"ok": False, "error": "工具返回非 JSON"})
    return {
        "tool_results": {name: result.model_dump() | ({"data": data} if data else {})},
        "error": None if result.ok else result.error,
        "steps": ["tool_executor"],
    }
```

`backend/app/agent/nodes/generator.py`：

```python
from langgraph.types import StreamWriter

from ...llm.base import LLMProvider


async def generator_node(state, provider: LLMProvider, writer: StreamWriter):
    answer_parts: list[str] = []
    async for chunk in provider.stream_answer(state["user_input"], state):
        answer_parts.append(chunk)
        writer(("token", {"text": chunk}))

    nav_card = None
    tool_result = state.get("tool_results", {}).get("resolve_page", {})
    if tool_result.get("ok") and isinstance(tool_result.get("data"), dict):
        page = tool_result["data"]
        nav_card = {"path": page["path"], "title": page["title"],
                    "reason": f"与「{state['intent']}」最匹配的页面"}
        writer(("nav_card", nav_card))

    return {"answer": "".join(answer_parts), "nav_card": nav_card, "steps": ["generator"]}
```

- [ ] **Step 5: 实现 graph 装配**

`backend/app/agent/graph.py`：

```python
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from ..llm.base import LLMProvider
from ..tools.base import ToolRegistry
from .nodes.generator import generator_node
from .nodes.router import router_node
from .nodes.tool_executor import tool_executor_node
from .state import AgentState


def build_graph(provider: LLMProvider, registry: ToolRegistry):
    async def router(state: AgentState):
        return await router_node(state, provider, registry)

    async def tool_executor(state: AgentState, writer: StreamWriter):
        return await tool_executor_node(state, registry, writer)

    async def generator(state: AgentState, writer: StreamWriter):
        return await generator_node(state, provider, writer)

    workflow = StateGraph(AgentState)
    workflow.add_node("router", router)
    workflow.add_node("tool_executor", tool_executor)
    workflow.add_node("generator", generator)
    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state["tool_name"] is not None,
        {True: "tool_executor", False: "generator"},
    )
    workflow.add_edge("tool_executor", "generator")
    workflow.add_edge("generator", END)
    return workflow.compile().with_config(recursion_limit=8)
```

- [ ] **Step 6: 跑集成测试确认通过**

```bash
cd backend
uv run pytest tests/test_graph.py -v
```

期望：5 条全部 PASS。若 `test_unknown_tool_blocked` 失败，检查 router 是否在 `tool_name not in known` 时把它置 None（条件边只认 `tool_name is not None`）。

- [ ] **Step 7: 实现 `POST /chat` SSE**

`backend/app/api/chat.py`：

```python
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError

from ..agent.graph import build_graph
from ..llm.fake import FakeProvider
from ..schemas import ChatRequest

logger = logging.getLogger("campus-agent.chat")
router = APIRouter()


def sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest, req: Request):
    registry = req.app.state.registry
    provider = FakeProvider()  # M6 换成 config 选择器
    graph = build_graph(provider, registry)
    request_id = uuid.uuid4().hex[:12]
    message_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    initial_state = {
        "user_input": request.message,
        "session_id": request.session_id,
        "intent": None, "tool_name": None, "tool_args": {},
        "tool_results": {}, "answer": "", "nav_card": None,
        "steps": [], "error": None,
    }

    async def stream():
        first_token_at: float | None = None
        final_state: dict | None = None
        try:
            async for mode, payload in graph.astream(
                initial_state, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    event, data = payload
                    if event == "token" and first_token_at is None:
                        first_token_at = time.perf_counter()
                        logger.info("request_id=%s 首token延迟=%.0fms",
                                    request_id, (first_token_at - start) * 1000)
                    yield sse_frame(event, data)
                else:
                    final_state = payload  # values 模式最后一条即合并后的最终 state
            yield sse_frame("done", {
                "message_id": message_id,
                "steps": (final_state or {}).get("steps", []),
                "session_id": request.session_id,
            })
        except GraphRecursionError:
            logger.error("request_id=%s 触发 recursion_limit", request_id)
            yield sse_frame("error", {"code": "recursion_limit", "message": "执行步数超限，请重试"})
        except Exception as exc:  # 兜底：任何异常都以 error 事件收尾，不裸断流
            logger.exception("request_id=%s 链路异常", request_id)
            yield sse_frame("error", {"code": "internal", "message": str(exc)})
        logger.info("request_id=%s 总耗时=%.0fms", request_id, (time.perf_counter() - start) * 1000)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

说明：`done.steps` 取自 `values` 模式的最后一个 payload——LangGraph 不会原地更新 `initial_state`，且 `steps` 经 `operator.add` 累加，最终 state 里的值即完整轨迹。

`backend/app/main.py` 的 `create_app()` 中挂路由：`from .api.chat import router as chat_router`、`app.include_router(chat_router)`。

- [ ] **Step 8: 手测 curl 复现完整事件序列**

```bash
cd backend
uv run uvicorn app.main:app --port 8000
```

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"我想看看这学期要上什么课","session_id":"curl-test-1"}'
```

期望依次看到（顺序即协议）：

```
event: tool_call
data: {"name":"resolve_page","args":{"intent":"我想看看这学期要上什么课"},"ok":true,"error":null,"latency_ms":...}

event: token
data: {"text":"..."}   （多条）

event: nav_card
data: {"path":"/academic/schedule","title":"课表查询","reason":"..."}

event: done
data: {"message_id":"...","steps":["router","tool_executor","generator"],"session_id":"curl-test-1"}
```

再验证无工具分支：

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"今天天气怎么样","session_id":"curl-test-2"}'
```

期望：`token*` 后直接 `done`，`steps == ["router","generator"]`，无 `tool_call`/`nav_card`。

- [ ] **Step 9: 提交**

```bash
git add backend/
git commit -m "feat(M4): FakeProvider + LangGraph 三节点图 + POST /chat SSE 全事件序列"
```

### Task M5: 前端全链路 — 悬浮球 + 聊天窗 + SSE 解析器 + 跳转卡片 + 2 仿真页

**对应里程碑：** M5（估时 30min）。

**Files:**
- Create: `frontend/src/types.ts`、`frontend/src/lib/sse.ts`、`frontend/tests/sse.test.ts`
- Create: `frontend/src/composables/useChatStream.ts`
- Create: `frontend/src/components/chat/FloatingBall.vue`、`ChatBox.vue`、`MessageList.vue`、`MessageBubble.vue`、`NavigationCard.vue`
- Create: `frontend/src/views/ScheduleView.vue`、`GradesView.vue`
- Create: `scripts/check_routes_contract.py`
- Modify: `frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/main.ts`

**Interfaces:**
- Produces: `createSSEParser(): { feed(chunk: Uint8Array): SSEFrame[] }`，`SSEFrame = { event: string; data: string }`（纯函数，与 Vue 解耦）。
- Produces: `useChatStream()` 暴露响应式状态 `messages: Ref<ChatMessage[]>`、`streaming: Ref<boolean>`、`pendingCard: Ref<NavCard | null>`、`sessionId: string` 与方法 `send(text: string): Promise<void>`、`abort(): void`。组件只消费，不发请求。
  ```ts
  type ChatMessage = {
    id: string
    role: 'user' | 'assistant'
    text: string                       // token 增量就地追加
    toolCall?: { name: string; ok: boolean; latencyMs: number } | null
    navCard?: NavCard | null
    error?: string | null
  }
  type NavCard = { path: string; title: string; reason: string }
  ```
- Consumes: M4 的 SSE 事件契约（`token`/`tool_call`/`nav_card`/`done`/`error`）；M2 的 `PAGE_REGISTRY` 四条路径（契约测试钉住）。

- [ ] **Step 1: 写 SSE 解析器及失败测试**

`frontend/src/lib/sse.ts`：

```ts
export interface SSEFrame {
  event: string
  data: string
}

export function createSSEParser() {
  const decoder = new TextDecoder()
  let buffer = ''
  return {
    feed(chunk: Uint8Array): SSEFrame[] {
      buffer += decoder.decode(chunk, { stream: true })
      const frames: SSEFrame[] = []
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        let event = 'message'
        const dataLines: string[] = []
        for (const line of raw.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
        }
        if (dataLines.length) frames.push({ event, data: dataLines.join('\n') })
      }
      return frames
    },
  }
}
```

`frontend/tests/sse.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { createSSEParser } from '../src/lib/sse'

const enc = (s: string) => new TextEncoder().encode(s)

describe('createSSEParser', () => {
  it('解析单个完整帧', () => {
    const p = createSSEParser()
    expect(p.feed(enc('event: token\ndata: {"text":"你好"}\n\n'))).toEqual([
      { event: 'token', data: '{"text":"你好"}' },
    ])
  })

  it('跨 chunk 的半截帧先不产出', () => {
    const p = createSSEParser()
    expect(p.feed(enc('event: token\nda'))).toEqual([])
    expect(p.feed(enc('ta: {"text":"x"}\n\n'))).toEqual([
      { event: 'token', data: '{"text":"x"}' },
    ])
  })

  it('多帧粘连一次产出', () => {
    const p = createSSEParser()
    const frames = p.feed(enc(
      'event: token\ndata: {"text":"a"}\n\nevent: nav_card\ndata: {"path":"/x"}\n\n',
    ))
    expect(frames.map((f) => f.event)).toEqual(['token', 'nav_card'])
  })

  it('UTF-8 多字节字符被 chunk 切断后正确重组', () => {
    const p = createSSEParser()
    const bytes = enc('data: {"text":"课表"}\n\n')
    const cut = bytes.slice(0, 12) // 恰好在"课"的中间切开
    expect(p.feed(cut)).toEqual([])
    expect(p.feed(bytes.slice(12))).toEqual([
      { event: 'message', data: '{"text":"课表"}' },
    ])
  })
})
```

`frontend/package.json` 的 `scripts` 增 `"test": "vitest run"`，然后：

```bash
cd frontend
npx vitest run tests/sse.test.ts
```

期望：4 条全部 PASS（先写测试再补实现也可按本文件顺序执行；若解析器已实现则直接绿）。

- [ ] **Step 2: 类型与唯一网络出口**

`frontend/src/types.ts`（与 `backend/app/schemas.py` 及 SSE 事件表一一对应）：

```ts
export interface ChatRequest {
  message: string
  session_id: string
}

export interface ToolCallEvent {
  name: string
  args: Record<string, unknown>
  ok: boolean
  error: string | null
  latency_ms: number
}

export interface TokenEvent { text: string }
export interface NavCardEvent { path: string; title: string; reason: string }
export interface DoneEvent { message_id: string; steps: string[]; session_id: string }
export interface ErrorEvent { code: string; message: string }
```

`frontend/src/composables/useChatStream.ts`：

```ts
import { ref } from 'vue'
import { createSSEParser } from '../lib/sse'
import type {
  ChatRequest, DoneEvent, ErrorEvent, NavCardEvent, TokenEvent, ToolCallEvent,
} from '../types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  toolCall: { name: string; ok: boolean; latencyMs: number } | null
  navCard: NavCard | null
  error: string | null
}

export function useChatStream() {
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const pendingCard = ref<NavCard | null>(null)
  const sessionId = crypto.randomUUID()
  let controller: AbortController | null = null

  async function send(text: string) {
    if (streaming.value) return
    messages.value.push({ id: crypto.randomUUID(), role: 'user', text, toolCall: null, navCard: null, error: null })
    const assistant: ChatMessage = {
      id: crypto.randomUUID(), role: 'assistant', text: '',
      toolCall: null, navCard: null, error: null,
    }
    messages.value.push(assistant)
    streaming.value = true
    controller = new AbortController()

    const body: ChatRequest = { message: text, session_id: sessionId }
    try {
      const resp = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)

      const parser = createSSEParser()
      const reader = resp.body.getReader()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        for (const frame of parser.feed(value)) {
          if (frame.event === 'token') {
            assistant.text += (JSON.parse(frame.data) as TokenEvent).text
          } else if (frame.event === 'tool_call') {
            const e = JSON.parse(frame.data) as ToolCallEvent
            assistant.toolCall = { name: e.name, ok: e.ok, latencyMs: e.latency_ms }
          } else if (frame.event === 'nav_card') {
            const e = JSON.parse(frame.data) as NavCardEvent
            assistant.navCard = e
            pendingCard.value = e
          } else if (frame.event === 'done') {
            void (JSON.parse(frame.data) as DoneEvent) // steps 留作操作日志面板数据源
          } else if (frame.event === 'error') {
            const e = JSON.parse(frame.data) as ErrorEvent
            assistant.error = `${e.code}: ${e.message}`
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        assistant.error = (err as Error).message
      }
    } finally {
      streaming.value = false
      controller = null
    }
  }

  function abort() {
    controller?.abort()
  }

  return { messages, streaming, pendingCard, sessionId, send, abort }
}
```

- [ ] **Step 3: 五个聊天组件与两个仿真页**

`frontend/src/components/chat/MessageBubble.vue`：

```vue
<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { computed } from 'vue'
import type { ChatMessage } from '../../composables/useChatStream'
import NavigationCard from './NavigationCard.vue'

const props = defineProps<{ message: ChatMessage }>()

const md = new MarkdownIt({
  html: false, // 硬约束：模型输出直插 DOM 是 XSS 入口
  highlight(code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext'
    return `<pre><code class="hljs">${hljs.highlight(code, { language }).value}</code></pre>`
  },
})
const rendered = computed(() => md.render(props.message.text))
</script>

<template>
  <div class="bubble" :class="message.role">
    <div v-if="message.toolCall" class="tool-call">
      正在调用 {{ message.toolCall.name }}（{{ message.toolCall.latencyMs }}ms）{{
        message.toolCall.ok ? '' : ' — 失败，已降级回答'
      }}
    </div>
    <div v-if="message.text" class="markdown-body" v-html="rendered" />
    <NavigationCard v-if="message.navCard" :card="message.navCard" />
    <div v-if="message.error" class="error">{{ message.error }}</div>
  </div>
</template>
```

`frontend/src/components/chat/NavigationCard.vue`：

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { NavCard } from '../../types'

const props = defineProps<{ card: NavCard }>()
const router = useRouter()

function go() {
  router.push(props.card.path) // 验收关键：跳转必须真实发生
}
</script>

<template>
  <el-card class="nav-card" shadow="hover" @click="go">
    <div class="title">{{ card.title }}</div>
    <div class="reason">{{ card.reason }}</div>
    <div class="path">{{ card.path }}</div>
  </el-card>
</template>
```

`frontend/src/components/chat/MessageList.vue`：

```vue
<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '../../composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ messages: ChatMessage[]; streaming: boolean }>()
const bottom = ref<HTMLElement | null>(null)
watch(
  () => props.messages.at(-1)?.text,
  async () => {
    await nextTick()
    bottom.value?.scrollIntoView({ behavior: 'smooth' })
  },
)
</script>

<template>
  <div class="message-list">
    <MessageBubble v-for="m in messages" :key="m.id" :message="m" />
    <div ref="bottom" />
  </div>
</template>
```

`frontend/src/components/chat/ChatBox.vue`：

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useChatStream } from '../../composables/useChatStream'
import MessageList from './MessageList.vue'

const { messages, streaming, send, abort } = useChatStream()
const input = ref('')
const placeholder = '试试：这学期上什么课 / 查成绩 / 补考安排 / 图书馆'

async function submit() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  input.value = ''
  await send(text)
}
</script>

<template>
  <div class="chat-box">
    <MessageList :messages="messages" :streaming="streaming" />
    <div class="input-row">
      <el-input
        v-model="input"
        :placeholder="placeholder"
        :disabled="streaming"
        @keyup.enter="submit"
      />
      <el-button v-if="!streaming" type="primary" @click="submit">发送</el-button>
      <el-button v-else @click="abort">停止</el-button>
    </div>
  </div>
</template>
```

`frontend/src/components/chat/FloatingBall.vue`（首次展开显示免责声明）：

```vue
<script setup lang="ts">
import { ref } from 'vue'
import ChatBox from './ChatBox.vue'

const open = ref(false)
const showDisclaimer = ref(true) // 每次会话首次展开显示
</script>

<template>
  <div class="floating-ball">
    <el-button v-if="!open" circle class="ball" @click="open = true">问</el-button>
    <div v-else class="panel">
      <div class="panel-header">
        <span>校园助手</span>
        <el-button text @click="open = false">收起</el-button>
      </div>
      <el-alert
        v-if="showDisclaimer"
        type="info"
        :closable="true"
        title="演示环境声明"
        description="本助手由 AI 驱动，当前为课程项目仿真数据，仅供参考；跳转页面为本地仿真校园站。"
        @close="showDisclaimer = false"
        class="disclaimer"
      />
      <ChatBox />
    </div>
  </div>
</template>
```

`frontend/src/views/ScheduleView.vue` 与 `GradesView.vue` 结构相同（静态占位）：

```vue
<script setup lang="ts"></script>

<template>
  <el-card class="fake-page">
    <h2>课表查询</h2>
    <p>这是仿真教务页面的占位内容。本学期课表数据为 seed 假数据，用于演示跳转链路与后续 Page Agent 注入。</p>
  </el-card>
</template>
```

`GradesView.vue` 标题改为"成绩查询"，正文相应改写。

- [ ] **Step 4: 路由、App、main**

`frontend/src/router/index.ts`（**路径必须与 M2 的 PAGE_REGISTRY 逐条一致**）：

```ts
import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('../views/HomeView.vue') },
    { path: '/academic/schedule', component: () => import('../views/ScheduleView.vue') },
    { path: '/academic/grades', component: () => import('../views/GradesView.vue') },
  ],
})
```

`frontend/src/App.vue`：

```vue
<script setup lang="ts">
import FloatingBall from './components/chat/FloatingBall.vue'
</script>

<template>
  <router-view />
  <FloatingBall />
</template>
```

`frontend/src/main.ts`：

```ts
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'highlight.js/styles/github.css'
import App from './App.vue'
import router from './router'

createApp(App).use(router).use(ElementPlus).mount('#app')
```

注意：M1 用 Vite 默认模板，若 `App.vue` 存在默认内容则整体覆盖；`HomeView.vue` 用模板自带或最小改写为项目标题页。

- [ ] **Step 5: 契约测试钉住隐式耦合**

`scripts/check_routes_contract.py`（用 **navigation venv** 跑，因为需要 import server.py）：

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_servers" / "navigation"))

from server import PAGE_REGISTRY  # noqa: E402

router_src = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")

missing = [
    entry.path for entry in PAGE_REGISTRY
    if f'"{entry.path}"' not in router_src
]
if missing:
    print("FAIL: 以下 PAGE_REGISTRY 路径未在前端 router 注册:", missing)
    sys.exit(1)
print(f"OK: {len(PAGE_REGISTRY)} 条页面路径全部已注册")
```

```bash
cd mcp_servers/navigation
uv run python ../../scripts/check_routes_contract.py
```

- [ ] **Step 6: 端到端手测（M5 验收）**

```bash
cd backend && uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

浏览器打开 `http://localhost:5173`：
1. 点悬浮球"问"→ 出现免责声明 → 关闭 → 输入"这学期上什么课"回车。
2. 看到状态条 `正在调用 resolve_page（…ms）` → 打字机式回答 → 出现"课表查询"卡片。
3. 点卡片 → **地址栏变 `/academic/schedule` 且页面渲染出占位内容**。
4. 输入"今天天气怎么样" → 无卡片、无 tool_call 条，出现兜底回答。

四项全过即 M5 完成。

- [ ] **Step 7: 提交**

```bash
git add frontend/ scripts/check_routes_contract.py
git commit -m "feat(M5): 悬浮球聊天窗 + SSE 流式渲染 + 跳转卡片 + 仿真页与路由契约测试"
```

### Task M6: 真模型 Provider + SQLite 落库 + 全量验收

**对应里程碑：** M6（估时 30min）。**允许降级**：若今晚真模型 Key 不可用，验收改为 `FakeProvider` 全绿 + `openai_compat.py` 通过 import 与结构检查，Key 到位后单独验证。

**Files:**
- Create: `backend/app/llm/openai_compat.py`、`backend/app/db/__init__.py`、`backend/app/db/engine.py`、`backend/app/db/repository.py`、`.env.example`
- Modify: `backend/pyproject.toml`（增 `aiosqlite>=0.20`、`openai>=1.50`）、`backend/app/config.py`（LLM 选择 + db 路径 + 仿真学号）、`backend/app/main.py`（lifespan init_db）、`backend/app/api/chat.py`（done 前落库）

**Interfaces:**
- Produces: `def build_provider(settings) -> LLMProvider`（启动期校验，缺 Key 即报错并提示改用 fake）。
- Produces:
  ```python
  class ToolCallRecord(BaseModel):
      tool_name: str
      args_json: str
      ok: bool
      error: str | None
      latency_ms: int

  class ConversationRepository(Protocol):
      async def record_exchange(self, *, session_id: str, user_text: str,
                                assistant_text: str,
                                tool_call: ToolCallRecord | None,
                                steps: list[str]) -> None: ...

  async def init_db(path: Path) -> None
  def build_repository(path: Path) -> ConversationRepository  # sqlite 实现
  ```
- Consumes: M4 的 `LLMProvider` 协议、`ChatRequest`；M3 的 `ToolRegistry`。

- [ ] **Step 1: 增依赖、.env.example、config 扩展**

```bash
cd backend
# pyproject dependencies 追加 "aiosqlite>=0.20", "openai>=1.50"
uv sync
```

`.env.example`（进仓库；真实 `.env` 进 .gitignore）：

```
# LLM_PROVIDER=fake | openai_compat
LLM_PROVIDER=fake
# 通义千问 DashScope compatible-mode: https://dashscope.aliyuncs.com/compatible-mode/v1
# DeepSeek: https://api.deepseek.com/v1
OPENAI_BASE_URL=
OPENAI_MODEL=
OPENAI_API_KEY=
```

`backend/app/config.py` 的 `Settings` 追加：

```python
from pathlib import Path

    llm_provider: str = "fake"
    openai_base_url: str = ""
    openai_model: str = ""
    openai_api_key: str = ""
    sqlite_path: Path = Path(__file__).resolve().parent.parent / "data" / "campus.db"
    fake_student_id: str = "20230001"  # 仿真用户，只从会话取，永不来自请求体
```

- [ ] **Step 2: 实现 `openai_compat.py`**

`backend/app/llm/openai_compat.py`：

```python
import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ..tools.base import ToolSpec
from .base import RouteDecision

ROUTER_SYSTEM = (
    "你是校园助手的路由器。用户输入一句话，判断是否需要调用工具。"
    "需要时用工具调用表达，不要直接回答。可用工具只有系统提供的那些。"
)

ANSWER_SYSTEM = (
    "你是校园助手。基于工具返回结果用中文简短回答；若工具有 nav 信息，"
    "引导用户点击跳转卡片。不要编造工具里没有的数据。"
)


class OpenAICompatProvider:
    """一份代码服务通义千问 compatible-mode 与 DeepSeek，差异全在三个环境变量。"""

    def __init__(self, base_url: str, model: str, api_key: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
        self.model = model

    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": user_input},
            ],
            tools=[
                {"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.input_schema}}
                for t in tools
            ],
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            call = msg.tool_calls[0]
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            return RouteDecision(intent=user_input[:20], tool_name=call.function.name,
                                 tool_args=args, confidence=1.0)
        return RouteDecision(intent=user_input[:20], tool_name=None,
                             tool_args={}, confidence=0.5)

    async def stream_answer(self, user_input: str, state: dict[str, Any]) -> AsyncIterator[str]:
        tool_note = ""
        for name, result in (state.get("tool_results") or {}).items():
            tool_note += f"\n工具 {name} 返回: {json.dumps(result.get('data'), ensure_ascii=False)}"
        messages = [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"用户问: {user_input}{tool_note}"},
        ]
        if state.get("error"):
            messages.append({"role": "user",
                             "content": f"工具调用失败({state['error']})，请给出降级说明。"})
        stream = await self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
```

- [ ] **Step 3: 实现 provider 选择器（启动期校验）**

`backend/app/llm/__init__.py`：

```python
import logging

from .base import LLMProvider
from .fake import FakeProvider

logger = logging.getLogger("campus-agent.llm")


def build_provider(settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        logger.info("使用 FakeProvider（规则式，无外部依赖）")
        return FakeProvider()
    if settings.llm_provider == "openai_compat":
        if not settings.openai_api_key:
            raise RuntimeError(
                "LLM_PROVIDER=openai_compat 需要 OPENAI_API_KEY；"
                "请在 backend/.env 配置，或改用 LLM_PROVIDER=fake"
            )
        from .openai_compat import OpenAICompatProvider

        logger.info("使用 OpenAICompatProvider model=%s", settings.openai_model)
        return OpenAICompatProvider(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )
    raise RuntimeError(f"未知 LLM_PROVIDER: {settings.llm_provider}")
```

- [ ] **Step 4: 实现 db 层**

`backend/app/db/__init__.py`：空文件。

`backend/app/db/engine.py`：

```python
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    latency_ms INTEGER NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.commit()
```

`backend/app/db/repository.py`：

```python
import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from ..tools.base import ToolResult


class ToolCallRecord(BaseModel):
    tool_name: str
    args_json: str
    ok: bool
    error: str | None
    latency_ms: int


class ConversationRepository(Protocol):
    async def record_exchange(self, *, session_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str]) -> None: ...


class SqliteConversationRepository:
    def __init__(self, path: Path):
        self._path = path

    async def record_exchange(self, *, session_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str]) -> None:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "INSERT INTO conversations(session_id) VALUES (?)", (session_id,))
            conv_id = cur.lastrowid
            await db.executemany(
                "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
                [(conv_id, "user", user_text), (conv_id, "assistant", assistant_text)],
            )
            if tool_call is not None:
                await db.execute(
                    """INSERT INTO tool_calls
                       (conversation_id, tool_name, args_json, ok, error, latency_ms, steps_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (conv_id, tool_call.tool_name, tool_call.args_json,
                     int(tool_call.ok), tool_call.error, tool_call.latency_ms,
                     json.dumps(steps, ensure_ascii=False)),
                )
            await db.commit()


def build_repository(path: Path) -> ConversationRepository:
    return SqliteConversationRepository(path)
```

- [ ] **Step 5: 接线 main.py 与 chat.py**

`backend/app/main.py` 的 lifespan：

```python
from .db.engine import init_db
from .db.repository import build_repository

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db(settings.sqlite_path)
    app.state.repository = build_repository(settings.sqlite_path)
    async with stdio_registry(settings.navigation_server_dir) as registry:
        app.state.registry = registry
        logger.info("MCP tools ready: %s", [t.name for t in await registry.list_tools()])
        yield
```

`backend/app/api/chat.py` 的改动：

1. 顶部 `from ..llm import build_provider`，`from ..config import get_settings`；`provider = build_provider(get_settings())` 替代 `FakeProvider()`。
2. `stream()` 里 `done` 事件之前落库（**失败不得中断对话流**）：

```python
            tool_results = (final_state or {}).get("tool_results", {})
            first = next(iter(tool_results.values()), None)
            try:
                from ..db.repository import ToolCallRecord

                record = None
                if first:
                    record = ToolCallRecord(
                        tool_name=first.get("name") or request.message and "resolve_page",
                        args_json=json.dumps((final_state or {}).get("tool_args", {}), ensure_ascii=False),
                        ok=bool(first.get("ok")),
                        error=first.get("error"),
                        latency_ms=int(first.get("latency_ms") or 0),
                    )
                await req.app.state.repository.record_exchange(
                    session_id=request.session_id,
                    user_text=request.message,
                    assistant_text=(final_state or {}).get("answer", ""),
                    tool_call=record,
                    steps=(final_state or {}).get("steps", []),
                )
            except Exception:
                logger.exception("request_id=%s 落库失败（不中断对话流）", request_id)
```

注意：`tool_results` 的 value 结构是 M4 `tool_executor_node` 返回的 `result.model_dump() | {"data": ...}`，不含 `name` 字段——`tool_name` 应从 `(final_state or {}).get("tool_name")` 取。修正上面 record 构造：

```python
                record = None
                if first and (final_state or {}).get("tool_name"):
                    record = ToolCallRecord(
                        tool_name=(final_state or {})["tool_name"],
                        args_json=json.dumps((final_state or {}).get("tool_args", {}), ensure_ascii=False),
                        ok=bool(first.get("ok")),
                        error=first.get("error"),
                        latency_ms=int(first.get("latency_ms") or 0),
                    )
```

- [ ] **Step 6: 全量验收（对应 spec 第 11 节完成定义）**

```bash
cd backend
uv run pytest -v            # 全部单测/集成测
cd ../mcp_servers/navigation && uv run pytest tests/ -v
uv run python ../../scripts/check_mcp.py
uv run python ../../scripts/check_routes_contract.py
cd ../../frontend && npx vitest run
```

手测三条用例（`LLM_PROVIDER=fake`）：

```bash
cd backend && uv run uvicorn app.main:app --port 8000
```

| # | 输入 | 期望 |
|---|---|---|
| 1 | 我想看看这学期要上什么课 | `nav_card.path == /academic/schedule`，事件序列完整 |
| 2 | 查一下我的成绩 | `nav_card.path == /academic/grades` |
| 3 | 今天天气怎么样 | 无卡片，兜底回答，`steps == ["router","generator"]` |

```bash
sqlite3 backend/data/campus.db \
  "select tool_name, ok, latency_ms, steps_json from tool_calls order by id desc limit 3;"
```

期望：三条记录，`steps_json` 分别为 `["router","tool_executor","generator"]`（用例 1、2）与 `["router","generator"]`（用例 3）。

真模型验证（Key 可用时）：`backend/.env` 填 `LLM_PROVIDER=openai_compat` 与三个 OPENAI_* 变量，重启后用例 1 重跑——期望语义一致、措辞不同、卡片正确。Key 不可用时按降级条款：import 检查 `uv run python -c "from app.llm.openai_compat import OpenAICompatProvider"` 通过即可。

最后逐条核对 spec 第 11 节 8 条完成定义，全过才算 M6 完成。

- [ ] **Step 7: 提交**

```bash
git status   # 确认 .env 未被跟踪、backend/data/*.db 未被跟踪
git add backend/ .env.example
git commit -m "feat(M6): openai_compat 真模型 Provider + SQLite tool_calls 落库 + 全量验收"
```

推送 `origin/main` 前需经用户确认（执行阶段再询问）。

---

## 风险与应对（照录 spec 第 7 节，执行时置顶）

1. **M2/M3 是唯二"卡住则整体崩"环节**：MCP v2 陌生 API + Windows stdio 子进程。应对：`scripts/check_mcp.py` 必须先做先跑绿，再进 M3；失败按全局约束三条硬约束排查。
2. **M6 允许降级**：Key 不可用时 fake 全绿 + `openai_compat.py` 过结构检查即可收工。
3. **M4 之后全部风险可增量调试**：LangGraph 图、SSE、前端各自有独立的测试/手测出口，不必串行返工。

## 自审记录

- **Spec 覆盖**：spec 第 7 节 M1–M6 六个里程碑各对应一个 Task；第 8 节四类测试（sse 单测、resolve_page 单测、router 拦截单测、集成测、契约测）分别落在 M2/M4/M5；第 6.1 节安全约束落实在 schemas（无 student_id 字段）、validate_args、CORS 白名单、markdown `html:false`；第 6.3 节 request_id 与三项耗时日志落在 M4 chat.py。
- **占位符扫描**：已清除 M4 Step 7 初稿中的占位函数与中间修正痕迹，最终版无 TBD/TODO。
- **类型一致性**：`ToolSpec`/`ToolResult`/`ToolRegistry` 签名在 M3 定义、M4 消费、M6 落库一致；SSE 事件名与字段在 M4 后端、M5 `types.ts`/`useChatStream.ts` 一致；`PAGE_REGISTRY` 四条路径在 M2 定义、M5 router 与契约测试钉住。
