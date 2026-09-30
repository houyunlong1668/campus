import logging
import re
import time

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry
from ..plan import WriteIntent

logger = logging.getLogger("campus-agent.router")

_QUERY_HINTS = ("成绩", "分数", "绩点", "课表", "上课", "在借", "借书",
                "还书", "补考", "重修", "多少", "平均")
# 澄清选项条点出来的只有裸学期词「2025 秋」（spec 7.2：点击=发 label 原文）。
# 它是上一轮取数问题的续答，不是闲聊——不认它，第二轮必掉 answer 兜底，
# 澄清闭环在生产上永远收敛不了（旧测试喂的是 label+原话拼接，测不到这里）。
_TERM_RE = re.compile(r"20\d{2}\s*(?:春|秋|夏|冬)")


def _route_of(user_input: str, tool_name: str | None,
              write: WriteIntent | None = None) -> str:
    """spec 7.3：取数优先于跳转（规则 3），都不像才 answer。
    write 非空时最高优先（裁决 R3）：写意图直接反转到 write 路由，
    不受「补考」等关键词落进 query 的影响。"""
    if write is not None:
        return "write"
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
    # route 与 plan 的鸡生蛋顺序（简报注 1）：final route 依赖 bundle.write，
    # 而 plan() 要收 route——唯一可行解是「base_route → 一次 plan → 最终 route」。
    # plan 收 base_route：写意图检测不依赖 route（R3），注册类输入即使
    # base_route 落 query（「补考」∈ _QUERY_HINTS）照样检出 write。
    base_route = _route_of(state["user_input"], decision.tool_name)
    bundle = await provider.plan(state["user_input"], base_route)
    route = _route_of(state["user_input"], decision.tool_name, bundle.write)
    # 编排二次判断（Task 4 的 plan()）：两个 return 分支共用同一 bundle 与
    # 最终 route——幻觉拦截分支也可能带编排/写意图，信息不能丢。plan 只调一次。
    step_details = [{"node": "router",
                     "latency_ms": int((time.perf_counter() - start) * 1000),
                     "detail": {"tool_name": decision.tool_name}}]
    if decision.tool_name is not None and decision.tool_name not in known:
        logger.warning("LLM 幻觉工具已拦截: %s", decision.tool_name)
        return {
            "intent": decision.intent,
            "route": route,
            "tool_name": None,
            "tool_args": {},
            "orchestration": bundle.orchestration,
            "write": bundle.write,
            "error": f"未知工具: {decision.tool_name}",
            "steps": ["router"],
            "step_details": step_details,
        }
    return {
        "intent": decision.intent,
        "route": route,
        "tool_name": decision.tool_name,
        "tool_args": decision.tool_args,
        "orchestration": bundle.orchestration,
        "write": bundle.write,
        "steps": ["router"],
        "step_details": step_details,
    }
