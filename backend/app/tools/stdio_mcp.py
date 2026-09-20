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
    async with AsyncExitStack() as stack:
        params = StdioServerParameters(
            command=sys.executable,        # 硬约束
            args=["server.py"],
            cwd=str(server_dir.resolve()),  # 硬约束：绝对路径
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        registry = StdioMcpRegistry(session)
        await registry.initialize()
        yield registry
