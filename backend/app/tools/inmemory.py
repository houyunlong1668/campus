from inspect import isawaitable
from typing import Any, Callable

from .base import (ToolRegistry, ToolResult, ToolSpec, timed_call, validate_args,
                   with_trusted_args)


class InMemoryRegistry(ToolRegistry):
    """测试与降级用：构造时接收 {name: {"spec": ..., "fn": ...}}。"""

    def __init__(self, tools: dict[str, dict[str, Any]]):
        self._tools = tools

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(**entry["spec"]) for entry in self._tools.values()]

    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult:
        entry = self._tools.get(name)
        if entry is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
        # 裁决 A 的三步同构到 InMemory：它同样用 extra="forbid" 校验，
        # 「先注入后校验」会让注入键被自己的 schema 拒掉。
        args = with_trusted_args(name, args, None)   # ① 只丢弃模型塞的
        ok, err = validate_args(entry["spec"]["input_schema"], args)  # ② 剥离后校验
        if not ok:
            return ToolResult(ok=False, error=err, latency_ms=0)
        args = with_trusted_args(name, args, student_id)  # ③ 校验后注入
        fn: Callable[..., Any] = entry["fn"]

        # fn 同步异步都要接得住：Task 4 的 composite 测试用同步 lambda 造工具
        async def invoke() -> Any:
            result = fn(**args)
            return await result if isawaitable(result) else result

        return await timed_call(invoke)
