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
