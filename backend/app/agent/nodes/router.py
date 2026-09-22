import logging

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.router")

_QUERY_HINTS = ("成绩", "分数", "绩点", "课表", "上课", "在借", "借书",
                "还书", "补考", "重修", "多少", "平均")


def _route_of(user_input: str, tool_name: str | None) -> str:
    """spec 7.3：取数优先于跳转（规则 3），都不像才 answer。"""
    if any(h in user_input for h in _QUERY_HINTS):
        return "query"
    if tool_name == "resolve_page":
        return "navigate"
    return "answer"


async def router_node(state, provider: LLMProvider, registry: ToolRegistry):
    tools = await registry.list_tools()
    decision = await provider.route(state["user_input"], tools)
    known = {t.name for t in tools}
    if decision.tool_name is not None and decision.tool_name not in known:
        logger.warning("LLM 幻觉工具已拦截: %s", decision.tool_name)
        return {
            "intent": decision.intent,
            "route": _route_of(state["user_input"], decision.tool_name),
            "tool_name": None,
            "tool_args": {},
            "error": f"未知工具: {decision.tool_name}",
            "steps": ["router"],
        }
    return {
        "intent": decision.intent,
        "route": _route_of(state["user_input"], decision.tool_name),
        "tool_name": decision.tool_name,
        "tool_args": decision.tool_args,
        "steps": ["router"],
    }
