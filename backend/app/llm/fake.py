import asyncio
from typing import Any, AsyncIterator

from ..tools.base import ToolSpec
from .base import RouteDecision

# 命中任一关键词即认为该意图应走 resolve_page；resolve_page 内部再做页面级匹配
_ROUTE_KEYWORDS = ("课表", "课程", "上什么课", "选课", "成绩", "分数", "绩点", "查分",
                   "补考", "重修", "图书馆", "借书", "还书", "图书")

_SQL_KEYWORDS = {"高数": "高等数学", "高等数学": "高等数学", "数据结构": "数据结构"}
_TERMS = ("2025 秋", "2026 春")   # 只这一条判定：用户点选项后文本里带学期 → 收窄


class FakeProvider:
    """规则式 Provider：无 Key、无网络、结果确定。是行为测试的基线。"""

    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision:
        hit = any(kw in user_input for kw in _ROUTE_KEYWORDS)
        if hit and any(t.name == "resolve_page" for t in tools):
            return RouteDecision(
                intent=user_input[:20], tool_name="resolve_page",
                tool_args={"intent": user_input}, confidence=1.0,
            )
        return RouteDecision(intent=user_input[:20], tool_name=None, tool_args={}, confidence=0.0)

    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        """规则只写"取数"一类最小判定（spec 12 警告过别膨胀成第二套假 NLU）。
        学期那一句是澄清闭环的必需品：没有它，第二轮仍返回跨学期结果，
        澄清会无限追问——spec 9.2 的"两轮收敛"测的就是这里。"""
        kw = next((v for k, v in _SQL_KEYWORDS.items() if k in user_input), None)
        term = next((t for t in _TERMS if t in user_input), None)
        sql = "SELECT course, term, score FROM v_grades WHERE 1=1"
        if kw:
            sql += f" AND course LIKE '%{kw}%'"
        if term:
            sql += f" AND term = '{term}'"
        return sql + " ORDER BY term"

    async def stream_answer(self, user_input: str, state: dict[str, Any]) -> AsyncIterator[str]:
        nav = state.get("nav_card")
        error = state.get("error")
        if nav:
            text = (f"已为你找到「{nav['title']}」页面。点击下方卡片即可跳转，"
                    f"你也可以在页面内查看详细内容。")
        elif error:
            text = (f"这次调用没有成功（{error}）。你可以换个说法再试一次，"
                    f"或者直接前往对应栏目手动查询。")
        else:
            text = ("我还不会回答这类问题。目前我可以帮你查课表、成绩、补考安排，"
                    "或者提供图书馆服务入口。")
        for i in range(0, len(text), 4):  # 每 4 字一段，模拟打字机节奏
            yield text[i : i + 4]
            await asyncio.sleep(0.01)
