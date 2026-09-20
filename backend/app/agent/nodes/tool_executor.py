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
