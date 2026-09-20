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
