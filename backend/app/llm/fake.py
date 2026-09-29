import asyncio
import re
from typing import AsyncIterator

from ..agent.plan import (OrchestrationPlan, PlanBundle, ThresholdCondition,
                          WriteIntent)
from ..agent.state import AgentState
from ..tools.base import ToolSpec
from .base import RouteDecision

# 命中任一关键词即认为该意图应走 resolve_page；resolve_page 内部再做页面级匹配
_ROUTE_KEYWORDS = ("课表", "课程", "上什么课", "选课", "成绩", "分数", "绩点", "查分",
                   "补考", "重修", "图书馆", "借书", "还书", "图书")

_SQL_KEYWORDS = {"高数": "高等数学", "高等数学": "高等数学", "数据结构": "数据结构"}
_TERMS = ("2025 秋", "2026 春")   # 只这一条判定：用户点选项后文本里带学期 → 收窄

# 报名意图：课程短语 → 课程代码（fake 的确定性词典，与 _SQL_KEYWORDS 同风格）
_REGISTER_COURSES = {"大学物理": "PHY1031", "高等数学": "MATH2041",
                     "体育": "PE1011", "概率论": "MATH2042"}
_ORCHESTRATE_HINTS = ("不及格", "低于", "如果", "就告诉", "就提醒")

# 词典外的具体课程（「我的计算机导论成绩」）从问句尾部抠课程短语，否则 kw=None
# → SQL 不带 course 过滤 → 全表 14 行都回来，用户看到的是一堆无关项。
# 只认「(…的)? 短语 + 成绩|分数|多少分」这一种收尾形态；短语里带人称/动词/
# 指代/疑问字符一律不猜、退回无过滤（spec 12 的边界：这一条正则是 fake 允许
# 的唯一泛化，不是第二套 NLU——猜不准宁可不猜）。
_SUBJECT_RE = re.compile(r"(?:.*?的)?(.{2,12}?)(?:的)?(?:成绩|分数|多少分)$")
_BAD_SUBJECT_CHARS = "我你他咱查问想看要这那几哪是否"
_BAD_SUBJECT_WORDS = ("平均", "多少", "什么", "学期", "所有", "全部")


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
        # 裁决 R2：词典课程优先于补考分支——旗舰输入「查我上学期高数成绩，
        # 不及格就告诉我补考时间」同时含"高数"与"补考"，第一轮必须查分数
        # （v_grades）grader 才有 score 列可判；kw 落空（如 followup 轮
        # 「我的补考和重修时间安排」）才查补考安排（v_makeup）。
        if kw is None and "补考" in user_input:
            return "SELECT course, kind, scheduled_at, place, status FROM v_makeup"
        if kw is None:
            m = _SUBJECT_RE.match(user_input.strip())
            if m and not any(c in m.group(1) for c in _BAD_SUBJECT_CHARS) \
                    and not any(w in m.group(1) for w in _BAD_SUBJECT_WORDS):
                kw = m.group(1)
        term = next((t for t in _TERMS if t in user_input), None)
        sql = "SELECT course, term, score FROM v_grades WHERE 1=1"
        if kw:
            sql += f" AND course LIKE '%{kw}%'"
        if term:
            sql += f" AND term = '{term}'"
        return sql + " ORDER BY term"

    async def plan(self, user_input: str, route: str) -> PlanBundle:
        """编排二次判断（裁决 1：route 之后的独立方法）。
        只有 query 才可能挂条件分支（navigate 与纯取数零开销）；
        写意图与 route 无关——报名语句自带写目的，路由反转由 Task 6 的
        `_route_of(..., write)` 完成（裁决 R3）。"""
        if route == "query" and any(h in user_input for h in _ORCHESTRATE_HINTS):
            return PlanBundle(orchestration=OrchestrationPlan(
                condition=ThresholdCondition(column="score", op="lt", value=60),
                followup_user_input="我的补考和重修时间安排"))
        if "报名" in user_input:
            for phrase, code in _REGISTER_COURSES.items():
                if phrase in user_input:
                    return PlanBundle(write=WriteIntent(
                        course_code=code, course_name=phrase,
                        summary=f"为「{phrase}」提交补考/重修报名"))
        return PlanBundle()

    async def judge(self, condition_text: str, evidence: dict) -> bool:
        """LLM 模式的 fake 兜底：行里任一数值低于 60 即 True。"""
        for row in evidence.get("rows") or []:
            if any(isinstance(v, (int, float)) and v < 60 for v in row):
                return True
        return False

    async def stream_answer(self, user_input: str, state: AgentState) -> AsyncIterator[str]:
        # 分支次序即优先级：error 要先于一切（拒绝轮必须说人话解释拒绝，
        # 不能被卡片/表格盖住）；有查数结果时表格就是答案，话术给读数引导，
        # 否则「有表却说我还不会」（澄清第二轮无 nav_card，正是这条旧症状）。
        nav = state.get("nav_card")
        error = state.get("error")
        sql = state.get("sql")
        if error:
            text = (f"这次调用没有成功（{error}）。你可以换个说法再试一次，"
                    f"或者直接前往对应栏目手动查询。")
        elif sql is not None:
            n = sql.get("row_count") or 0
            text = ("没有查到符合条件的记录。" if n == 0
                    else f"已查到 {n} 条记录，见下方表格。")
        elif nav:
            text = (f"已为你找到「{nav['title']}」页面。点击下方卡片即可跳转，"
                    f"你也可以在页面内查看详细内容。")
        else:
            text = ("我还不会回答这类问题。目前我可以帮你查课表、成绩、补考安排，"
                    "或者提供图书馆服务入口。")
        for i in range(0, len(text), 4):  # 每 4 字一段，模拟打字机节奏
            yield text[i : i + 4]
            await asyncio.sleep(0.01)
