"""S4 编排：fake 规则、grader、降级、循环守卫。"""
import sys

import pytest

from app.agent.graph import build_graph
from app.agent.plan import OrchestrationPlan, PlanBundle, ThresholdCondition
from app.llm.fake import FakeProvider
from app.tools.inmemory import InMemoryRegistry


class TestFakePlan:
    async def test_不及格触发阈值编排(self):
        bundle = await FakeProvider().plan("查我上学期高数成绩，不及格就告诉我补考时间", "query")
        assert bundle.orchestration is not None
        assert bundle.orchestration.condition == ThresholdCondition(column="score", value=60)
        assert bundle.orchestration.followup_user_input

    async def test_纯取数不触发编排(self):
        bundle = await FakeProvider().plan("我这学期平均分多少", "query")
        assert bundle.orchestration is None and bundle.write is None

    async def test_报名触发写意图(self):
        bundle = await FakeProvider().plan("帮我报名大学物理（上）的补考", "answer")
        assert bundle.write is not None and bundle.write.course_code == "PHY1031"

    async def test_judge对分数行给布尔(self):
        assert await FakeProvider().judge("是否有不及格", {"columns": ["score"], "rows": [[91], [56]]}) is True
        assert await FakeProvider().judge("是否有不及格", {"columns": ["score"], "rows": [[91]]}) is False

    async def test_写意图不依赖route_answer(self):
        # 报名问句因含"补考"被 router 路由为 query——写意图必须照样检出（裁决 R3，Task 6 confirm_card 的前提）
        bundle = await FakeProvider().plan("帮我报名大学物理（上）的补考", "query")
        assert bundle.write is not None and bundle.write.course_code == "PHY1031"


class TestFakeSql补考分支:
    async def test_补考问句查v_makeup(self):
        sql = await FakeProvider().generate_sql("我的补考和重修时间安排", "[]")
        assert "v_makeup" in sql and "v_grades" not in sql


# —— 图级用例（Task 5）：InMemory 三件套 + FakeProvider 跑真图 ——
# schema 与桩照抄 test_graph.py 的 academic_registry（构造方式同款）。
RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string"}, "params": {"type": "object"}},
    "required": ["intent"],
}

ACADEMIC_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}


async def fake_run_sql(sql: str, student_id: str | None = None):
    """按 SQL 内容分流两批行：then 测试的分数 / else 测试的分数 / 补考安排。

    定义在模块层（而非 fixture 闭包内）：降级用例要 monkeypatch 它，
    闭包里的局部函数补丁够不着。签名带 student_id——裁决 A 下 call_tool
    校验后会注入该参，签名不带会 TypeError 被 timed_call 吞成 ok=False
    （test_graph 教训）。
    """
    if "v_makeup" in sql:
        return {"ok": True, "scoped_sql": sql,
                "columns": ["course", "kind", "scheduled_at", "place", "status"],
                "rows": [["高等数学（下）", "补考", "2026-03-02 09:00",
                          "主楼 A102", "报名中"]],
                "row_count": 1, "refused_code": None}
    if "数据结构" in sql:        # else 测试（裁决 R2b）：全过
        return {"ok": True, "scoped_sql": sql, "columns": ["course", "score"],
                "rows": [["数据结构", 88]], "row_count": 1, "refused_code": None}
    if "高等数学" in sql:        # then 测试：含 56 分不及格行
        return {"ok": True, "scoped_sql": sql, "columns": ["course", "score"],
                "rows": [["高等数学（上）", 91], ["高等数学（下）", 56]],
                "row_count": 2, "refused_code": None}
    return {"ok": True, "scoped_sql": sql, "columns": ["course", "score"],
            "rows": [["数据结构", 91]], "row_count": 1, "refused_code": None}


@pytest.fixture
def graph_with_fake():
    async def fake_resolve(intent: str):
        if "成绩" in intent:
            return {"path": "/academic/grades", "title": "成绩查询",
                    "capabilities": ["查成绩"]}
        if "重修" in intent or "补考" in intent:
            return {"path": "/academic/makeup", "title": "补考重修查询",
                    "capabilities": ["查补考安排", "查看重修报名"]}
        raise ValueError("no matching page for intent")

    registry = InMemoryRegistry({
        "resolve_page": {"spec": {"name": "resolve_page", "description": "d",
                                  "input_schema": RESOLVE_SCHEMA},
                         "fn": fake_resolve},
        "describe_schema": {"spec": {"name": "describe_schema", "description": "d",
                                     "input_schema": {"type": "object", "properties": {}}},
                            "fn": lambda: [{"name": "v_grades", "columns": ["course", "term"]}]},
        "run_sql": {"spec": {"name": "run_sql", "description": "d",
                             "input_schema": ACADEMIC_SCHEMA},
                    # 经模块名间接调用（调用时才查全局）：降级用例补丁
                    # fake_run_sql 后这里要拿到的是打过补丁的新函数
                    "fn": lambda **kw: fake_run_sql(**kw)},
    })
    return build_graph(FakeProvider(), registry)


async def run_graph(graph, user_input: str, history: list | None = None):
    """只回 final 单值（控制器注记 3）：本文件断言都不需要 token 采集。
    initial dict 从 test_graph.py 的同名 helper 照抄（含 Task 2 的 8 个新 key）。"""
    final = None
    async for mode, payload in graph.astream(
        {"user_input": user_input, "student_id": "20230001",
         "history": history or [],
         "intent": None, "route": None, "orchestration": None, "write": None,
         "orchestration_phase": None, "branch": None, "next_query": None,
         "tool_name": None, "tool_args": {},
         "tool_results": {}, "answer": "", "nav_card": None,
         "needs_clarification": False, "clarification": None, "sql": None,
         "sql_history": [], "confirm_card": None, "step_details": [],
         "steps": [], "error": None},
        stream_mode=["custom", "values"],
    ):
        if mode == "values":
            final = payload
    return final


class Test旗舰编排:
    async def test_then分支走grader再查补考(self, graph_with_fake):
        # InMemory 注册表里 run_sql 按 SQL 内容返回 v_grades / v_makeup 两类行
        final = await run_graph(graph_with_fake, "查我上学期高数成绩，不及格就告诉我补考时间")
        assert final["steps"] == ["router", "sql_executor", "grader",
                                  "sql_executor", "generator"]
        assert final["branch"] == "then"
        assert len(final["sql_history"]) == 2           # 两轮查数都在
        assert "grader" in final["steps"]
        assert "已报名" in final["answer"] or "补考" in final["answer"]

    async def test_else分支不进grader后续(self, graph_with_fake):
        # 数据结构全部及格的行 → then 不成立：steps 无第二个 sql_executor
        # （输入用数据结构而非高数——裁决 R2b：同一 fixture 下两测试必须产出不同 SQL）
        final = await run_graph(graph_with_fake, "查我上学期数据结构成绩，及格就告诉我奖学金")
        assert final["branch"] == "else"
        assert final["steps"] == ["router", "sql_executor", "grader", "generator"]

    async def test_失败降级保留已成功结果(self, graph_with_fake, monkeypatch):
        # 第二个工具（run_sql 的 v_makeup 查询）抛错：timed_call 已包成 ok=False，
        # grader 在前半段已放行 followup——降级发生在 followup executor：
        # 答案里既有第一轮的分数，又有失败说明，steps 正常收尾到 generator
        orig = fake_run_sql   # 先抓原对象：补丁改的是模块字典，闭包引用旧对象

        async def boom(sql: str, student_id: str | None = None):
            if "v_makeup" in sql:
                raise RuntimeError("boom")
            return await orig(sql, student_id)

        monkeypatch.setattr(sys.modules[__name__], "fake_run_sql", boom)
        final = await run_graph(graph_with_fake, "查我上学期高数成绩，不及格就告诉我补考时间")
        assert final["steps"] == ["router", "sql_executor", "grader",
                                  "sql_executor", "generator"]
        assert final["error"]
        assert "91" in final["answer"]            # 第一轮分数保留
        assert "没有成功" in final["answer"]       # fake error 话术

    async def test_循环守卫_grader只放行一次(self, graph_with_fake, monkeypatch):
        # plan.followup 本身又含触发词（「不及格」），若无守卫会无限循环。
        # 守卫 = orchestration_phase 标记：followup 轮不再回 grader。
        # 构造：monkeypatch FakeProvider.plan 让 followup 问句也命中编排，
        # 断言 steps 里 grader 恰好一次、序列有限长、正常收尾。
        async def always_plan(self, user_input, route):
            return PlanBundle(orchestration=OrchestrationPlan(
                condition=ThresholdCondition(column="score", op="lt", value=60),
                followup_user_input="我的补考和重修时间安排"))

        monkeypatch.setattr(FakeProvider, "plan", always_plan)
        final = await run_graph(graph_with_fake, "查我上学期高数成绩，不及格就告诉我补考时间")
        graders = [s for s in final["steps"] if s == "grader"]
        assert len(graders) == 1
        assert len(final["steps"]) <= 6
        assert final["steps"][-1] == "generator"
