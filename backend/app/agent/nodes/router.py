import logging

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.router")

_QUERY_HINTS = ("成绩", "分数", "绩点", "课表", "上课", "在借", "借书",
                "还书", "补考", "重修", "多少", "平均")

# spec 7.3 规则 1 的另一半："命中 resolve_page 且**未要求具体数值**"才算跳转意图。
# "多少/平均" 是取数问法（也在 _QUERY_HINTS 里，route 必为 query），
# 这类输入即使 FakeProvider 按关键词报了 resolve_page，也不该再补跑出跳转卡。
_VALUE_MARKERS = ("多少", "平均")


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
    value_asked = any(m in state["user_input"] for m in _VALUE_MARKERS)
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
    # 规则 1 门控：取值问法 → 不保留跳转决策（route 仍由 _route_of 判为 query）
    return {
        "intent": decision.intent,
        "route": _route_of(state["user_input"], decision.tool_name),
        "tool_name": None if value_asked else decision.tool_name,
        "tool_args": {} if value_asked else decision.tool_args,
        "steps": ["router"],
    }
