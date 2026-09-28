import logging
import re
import time

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.router")

_QUERY_HINTS = ("成绩", "分数", "绩点", "课表", "上课", "在借", "借书",
                "还书", "补考", "重修", "多少", "平均")
# 澄清选项条点出来的只有裸学期词「2025 秋」（spec 7.2：点击=发 label 原文）。
# 它是上一轮取数问题的续答，不是闲聊——不认它，第二轮必掉 answer 兜底，
# 澄清闭环在生产上永远收敛不了（旧测试喂的是 label+原话拼接，测不到这里）。
_TERM_RE = re.compile(r"20\d{2}\s*(?:春|秋|夏|冬)")


def _route_of(user_input: str, tool_name: str | None) -> str:
    """spec 7.3：取数优先于跳转（规则 3），都不像才 answer。"""
    if any(h in user_input for h in _QUERY_HINTS) or _TERM_RE.search(user_input):
        return "query"
    if tool_name == "resolve_page":
        return "navigate"
    return "answer"


async def router_node(state, provider: LLMProvider, registry: ToolRegistry):
    start = time.perf_counter()
    tools = await registry.list_tools()
    decision = await provider.route(state["user_input"], tools)
    known = {t.name for t in tools}
    step_details = [{"node": "router",
                     "latency_ms": int((time.perf_counter() - start) * 1000),
                     "detail": {"tool_name": decision.tool_name}}]
    if decision.tool_name is not None and decision.tool_name not in known:
        logger.warning("LLM 幻觉工具已拦截: %s", decision.tool_name)
        return {
            "intent": decision.intent,
            "route": _route_of(state["user_input"], decision.tool_name),
            "tool_name": None,
            "tool_args": {},
            "error": f"未知工具: {decision.tool_name}",
            "steps": ["router"],
            "step_details": step_details,
        }
    return {
        "intent": decision.intent,
        "route": _route_of(state["user_input"], decision.tool_name),
        "tool_name": decision.tool_name,
        "tool_args": decision.tool_args,
        "steps": ["router"],
        "step_details": step_details,
    }
