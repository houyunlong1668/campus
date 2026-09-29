"""S4 编排：fake 规则、grader、降级、循环守卫。"""
from app.agent.plan import ThresholdCondition
from app.llm.fake import FakeProvider


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
