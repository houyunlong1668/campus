import sys
from contextlib import AsyncExitStack, asynccontextmanager
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
            # 适配说明：mcp 2.x Python 模型字段为 input_schema（wire 上仍是 inputSchema）
            ToolSpec(name=t.name, description=t.description or "", input_schema=t.input_schema or {})
            for t in listed.tools
        ]

    async def list_tools(self) -> list[ToolSpec]:
        return self._specs

    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult:
        # student_id 在 Task 4 只收不注入；Task 5 按裁决 A 在此做
        # "先丢弃模型塞的、校验、再注入"（TRUSTED_ARGS）
        spec = next((s for s in self._specs if s.name == name), None)
        if spec is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
        ok, err = validate_args(spec.input_schema, args)
        if not ok:
            return ToolResult(ok=False, error=err, latency_ms=0)

        async def invoke():
            result = await self._session.call_tool(name, args)
            text = result.content[0].text if result.content else ""
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
