import json
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .base import (ToolRegistry, ToolResult, ToolSpec, strip_trusted,
                   timed_call, validate_args, with_trusted_args)


def _text_blocks(result: Any) -> list[str]:
    """无结构化内容时的退路：拼全部 text 块，而不是只取第一块。

    单块（navigation 的 resolve_page）与旧行为逐字一致。多块时每个块各是一个
    JSON 对象（list 型工具被线上拆成每元素一块），所以先逐个 loads 成 JSON
    数组，让下游的 json.loads 仍成立；任何一块不是 JSON 才退回普通文本拼接。
    只取第一块曾让 describe_schema 的 4 张视图在真环境只剩 v_grades 一张。
    """
    parts = [c.text for c in result.content if getattr(c, "text", None) is not None]
    if len(parts) == 1:
        return parts[0]
    try:
        return json.dumps([json.loads(p) for p in parts], ensure_ascii=False)
    except ValueError:
        return "\n".join(parts)


def _result_json(result: Any) -> str:
    """把 MCP 返回折算成一段可 json.loads 的文本（下游 tool_executor /
    sql_executor 都按字符串解析）。

    优先 structured_content：MCP 2.x 把结构化结果放在这里，对非对象结果按
    规范包一层 {"result": ...}（describe_schema 的 list[SchemaTable] 就是这样，
    4 张视图同时在 structured_content 里），拆掉这层包装才能与
    InMemoryRegistry 直给 list/dict 的形状同构——两条路径语义一致，
    真路径与测试路径才不会各写各的。
    """
    data = getattr(result, "structured_content", None)
    if data is not None:
        if isinstance(data, dict) and list(data) == ["result"]:
            data = data["result"]
        return json.dumps(data, ensure_ascii=False)
    return _text_blocks(result)


class StdioMcpRegistry(ToolRegistry):
    def __init__(self, session: ClientSession):
        self._session = session
        self._specs: list[ToolSpec] = []

    async def initialize(self) -> None:
        await self._session.initialize()
        listed = await self._session.list_tools()
        self._specs = [
            # 适配说明：mcp 2.x Python 模型字段为 input_schema（wire 上仍是 inputSchema）
            ToolSpec(name=t.name, description=t.description or "",
                     input_schema=strip_trusted(t.name, t.input_schema or {}))
            for t in listed.tools
        ]

    async def list_tools(self) -> list[ToolSpec]:
        return self._specs

    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult:
        spec = next((s for s in self._specs if s.name == name), None)
        if spec is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
        # 裁决 A 三步（覆盖 brief 的"先注入后校验"两步）：
        # ① 只丢弃模型塞的受信键、不注入——让"模型视角的 args"与
        #    已被 strip_trusted 剥过的 schema 一致；
        # ② 用剥离后的 schema 校验剥离后的 args（extra="forbid" 底线不拆）；
        # ③ 校验通过后才注入服务端学号——注入值来自会话、不是模型输入，
        #    不过模型侧 schema 的关（spec 4.2"先校验再改写"的参数层同构延伸）。
        args = with_trusted_args(name, args, None)
        ok, err = validate_args(spec.input_schema, args)
        if not ok:
            return ToolResult(ok=False, error=err, latency_ms=0)
        args = with_trusted_args(name, args, student_id)

        async def invoke():
            result = await self._session.call_tool(name, args)
            text = _result_json(result)
            # MCP 把 server 侧工具异常包成 isError=True 的正常响应帧：
            # 不判它就把"工具失败"当成功返回，落库错误原因也会被扭曲
            if result.is_error:
                raise RuntimeError(text or f"工具 {name} 执行失败")
            return text  # JSON 字符串，generator 负责 loads

        return await timed_call(invoke)


def _server_python(server_dir: Path) -> Path:
    """选启动解释器：server 自带 .venv（uv sync 产物）就用它的绝对路径。

    academic 的 sqlglot/aiosqlite 只在它自己 uv 项目的 venv 里——backend venv
    （sys.executable）启动会在 import guard 时 ModuleNotFoundError；navigation
    没有 .venv，维持 sys.executable 不变。M1 硬约束的本意是"不用 PATH 上的
    裸 python"，venv 解释器绝对路径同样满足，且子进程环境 == uv.lock 锁定环境。
    """
    for stem, exe in (("Scripts", "python.exe"), ("bin", "python")):
        candidate = server_dir / ".venv" / stem / exe
        if candidate.exists():
            return candidate
    return Path(sys.executable)


@asynccontextmanager
async def stdio_registry(server_dir: Path, env: dict[str, str] | None = None):
    """lifespan 用：拉起 MCP 子进程，退出时随 AsyncExitStack 关闭。

    env 必须显式传给 academic：MCP 的 StdioServerParameters 在 env=None 时
    走白名单环境（只留 PATH/HOME 之类），DB_BACKEND 之类自定义变量传不进去。
    navigation 不连库，仍用默认。
    """
    resolved = server_dir.resolve()
    async with AsyncExitStack() as stack:
        params = StdioServerParameters(
            command=str(_server_python(resolved)),  # 硬约束：解释器绝对路径，不用裸 "python"
            args=["server.py"],
            cwd=str(resolved),                      # 硬约束：绝对路径
            env=env,
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        registry = StdioMcpRegistry(session)
        await registry.initialize()
        yield registry
