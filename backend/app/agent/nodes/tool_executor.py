import json
import logging
import time

from langgraph.types import StreamWriter

from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.tool_executor")


async def tool_executor_node(state, registry: ToolRegistry, writer: StreamWriter):
    start = time.perf_counter()
    name = state["tool_name"]
    # Task 5 起：会话学号从 state 侧取、服务端注入（模型侧 schema 看不见这列）。
    result = await registry.call_tool(name, state["tool_args"],
                                      student_id=state["student_id"])
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
        "step_details": [{"node": "tool_executor",
                          "latency_ms": int((time.perf_counter() - start) * 1000),
                          "detail": {"tool_name": name, "ok": result.ok}}],
    }
