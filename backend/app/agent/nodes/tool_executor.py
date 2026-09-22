import json
import logging

from langgraph.types import StreamWriter

from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.tool_executor")


async def tool_executor_node(state, registry: ToolRegistry, writer: StreamWriter):
    name = state["tool_name"]
    # Task 5：会话学号从 state 侧取、服务端注入（模型侧 schema 看不见这列）。
    # 现字段名 session_id（chat.py 里存的就是 student_id）；Task 6 改名 student_id。
    result = await registry.call_tool(name, state["tool_args"],
                                      student_id=state["session_id"])
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
