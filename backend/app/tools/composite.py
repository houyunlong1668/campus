from typing import Any

from .base import ToolRegistry, ToolResult, ToolSpec


class CompositeRegistry(ToolRegistry):
    """多个 MCP 子进程按工具名分派。spec 的接入点写的是"server 清单加一条"，
    而每个 server 各是一个 session，所以这里做的是聚合而不是合并 session。
    """

    def __init__(self, registries: list[ToolRegistry]):
        self._regs = list(registries)

    async def list_tools(self) -> list[ToolSpec]:
        out: list[ToolSpec] = []
        for reg in self._regs:
            out.extend(await reg.list_tools())
        return out

    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult:
        for reg in self._regs:
            specs = await reg.list_tools()
            if any(s.name == name for s in specs):
                return await reg.call_tool(name, args, student_id=student_id)
        return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
