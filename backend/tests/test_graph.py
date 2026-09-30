import json

import pytest

from app.agent.graph import build_graph
from app.agent.nodes.router import router_node
from app.llm.base import RouteDecision
from app.llm.fake import FakeProvider
from app.tools.inmemory import InMemoryRegistry

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string"}, "params": {"type": "object"}},
    "required": ["intent"],
}


@pytest.fixture
def registry():
    async def fake_resolve(intent: str):
        if "成绩" in intent:
            return {"path": "/academic/grades", "title": "成绩查询", "capabilities": ["查看各科成绩"]}
        if "课" in intent:
            return {"path": "/academic/schedule", "title": "课表查询", "capabilities": ["查看课表"]}
        raise ValueError("no matching page for intent")

    return InMemoryRegistry(
        {
            "resolve_page": {
                "spec": {
                    "name": "resolve_page",
                    "description": "把意图映射到页面",
                    "input_schema": RESOLVE_SCHEMA,
                },
                "fn": fake_resolve,
            }
        }
    )


async def run_graph(graph, user_input: str, history: list | None = None):
    collected = {"tokens": [], "nav_card": None, "custom": []}
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
        if mode == "custom":
            collected["custom"].append(payload)
            if payload[0] == "token":
                collected["tokens"].append(payload[1]["text"])
            elif payload[0] == "nav_card":
                collected["nav_card"] = payload[1]
        else:
            final = payload
    return collected, final


class TestHappyPath:
    async def test_full_chain(self, registry):
        graph = build_graph(FakeProvider(), registry)
        collected, final = await run_graph(graph, "这学期上什么课")
        assert final["steps"] == ["router", "tool_executor", "generator"]
        assert collected["nav_card"]["path"] == "/academic/schedule"
        assert "".join(collected["tokens"])  # 有文本输出
        # 防回归：命中工具时首条话术须与 nav_card 语义一致，不得是兜底话术
        assert "课表查询" in "".join(collected["tokens"])
        tool_events = [c for c in collected["custom"] if c[0] == "tool_call"]
        assert tool_events and tool_events[0][1]["ok"] is True

    async def test_fallback_no_tool(self, registry):
        graph = build_graph(FakeProvider(), registry)
        collected, final = await run_graph(graph, "今天天气怎么样")
        assert final["steps"] == ["router", "generator"]
        assert collected["nav_card"] is None
        assert final["tool_name"] is None


class TestRouterGuards:
    async def test_unknown_tool_blocked(self, registry):
        class HallucinatingProvider(FakeProvider):
            async def route(self, user_input, tools):
                return RouteDecision(intent="x", tool_name="drop_database",
                                     tool_args={}, confidence=0.9)

        graph = build_graph(HallucinatingProvider(), registry)
        collected, final = await run_graph(graph, "随便什么")
        assert final["steps"] == ["router", "generator"]  # 未进 tool_executor
        assert final["error"] and "drop_database" in final["error"]

    async def test_tool_failure_degrades(self, registry):
        graph = build_graph(FakeProvider(), registry)
        # 三态后"补考"是取数提示词（spec 7.3 规则 2 → query），本用例要测的
        # navigate 降级路径得换不含查询提示词的输入："图书"命中路由关键词，
        # 但 registry 的 fake 只认含"成绩"/"课"的 intent → resolve 内部未命中。
        collected, final = await run_graph(graph, "查图书")  # 命中规则但 resolve 内部未命中
        assert final["steps"] == ["router", "tool_executor", "generator"]
        tool_events = [c for c in collected["custom"] if c[0] == "tool_call"]
        assert tool_events[0][1]["ok"] is False  # 失败仍走完，降级话术由 generator 出


class TestSSE:
    def test_sse_frame_format(self):
        from app.api.chat import sse_frame

        frame = sse_frame("token", {"text": "你好"})
        assert frame == 'event: token\ndata: {"text": "你好"}\n\n'


ACADEMIC_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}


@pytest.fixture
def academic_registry():
    # student_id：裁决 A 下 call_tool 会在校验后注入这一参（TRUSTED_ARGS），
    # brief 原签名 sql-only 会 TypeError 被 timed_call 吞成 ok=False。
    async def fake_run_sql(sql: str, student_id: str | None = None):
        if "student_id=" in sql.replace(" ", ""):
            return {"ok": False, "refused_code": "identity_column",
                    "scoped_sql": "", "rows": [], "columns": [], "row_count": 0}
        # 跨两个学期 → 触发澄清；若 SQL 里已被限定学期，则只剩该学期的行
        rows = [["高等数学（上）", "2025 秋"], ["数据结构", "2026 春"]]
        for term in ("2025 秋", "2026 春"):
            if f"term = '{term}'" in sql:
                rows = [r for r in rows if r[1] == term]
        return {"ok": True, "scoped_sql": sql, "columns": ["course", "term"],
                "rows": rows, "row_count": len(rows), "refused_code": None}

    # resolve 必须建模"未命中"（真 server 无匹配即 raise）：恒返回 dict 的桩
    # 会让「平均分」这类纯查数问句也配上卡片，掩盖规则 3 的未命中分支
    async def fake_resolve(intent: str):
        if "成绩" in intent:
            return {"path": "/academic/grades", "title": "成绩查询",
                    "capabilities": ["查成绩"]}
        if "重修" in intent or "补考" in intent:
            return {"path": "/academic/makeup", "title": "补考重修查询",
                    "capabilities": ["查补考安排", "查看重修报名"]}
        raise ValueError("no matching page for intent")

    return InMemoryRegistry({
        "resolve_page": {"spec": {"name": "resolve_page", "description": "d",
                                  "input_schema": RESOLVE_SCHEMA},
                         "fn": fake_resolve},
        "describe_schema": {"spec": {"name": "describe_schema", "description": "d",
                                     "input_schema": {"type": "object", "properties": {}}},
                            "fn": lambda: [{"name": "v_grades", "columns": ["course", "term"]}]},
        "run_sql": {"spec": {"name": "run_sql", "description": "d",
                             "input_schema": ACADEMIC_SCHEMA},
                    "fn": fake_run_sql},
    })


class McpShapeRegistry(InMemoryRegistry):
    """模拟真 MCP 形态：stdio_mcp.invoke() 恒返 result.content[0].text——JSON
    字符串（app/tools/stdio_mcp.py:48-55），而 InMemory 直接给 dict/list。
    sql_executor 的 str→loads 解析 seam 只在真 MCP 路径暴露，旧测试全绿也
    照不出它；这里把每个 ok 结果的 data 编码成 str，钉住真路径。"""

    async def call_tool(self, name: str, args: dict,
                        student_id: str | None = None):
        result = await super().call_tool(name, args, student_id=student_id)
        if result.ok and isinstance(result.data, (dict, list)):
            result = result.model_copy(
                update={"data": json.dumps(result.data, ensure_ascii=False)})
        return result


@pytest.fixture
def mcp_shape_registry(academic_registry):
    # 复用 academic 三件套（裁决 M 的 fake_run_sql 签名原样），只把 data 换成 str 形态
    return McpShapeRegistry(academic_registry._tools)


class Test三态分流:
    async def test_取数意图走query出数据而非跳转卡(self, academic_registry):
        graph = build_graph(FakeProvider(), academic_registry)
        collected, final = await run_graph(graph, "我这学期平均分多少")
        assert final["route"] == "query"
        assert final["steps"] == ["router", "sql_executor", "generator"]
        assert collected["nav_card"] is None          # 没跑 resolve_page
        assert final["sql"] and final["sql"]["row_count"] == 2

    async def test_纯跳转意图仍走navigate(self, registry):
        graph = build_graph(FakeProvider(), registry)
        _, final = await run_graph(graph, "这学期上什么课")
        assert final["route"] == "navigate"
        assert final["steps"] == ["router", "tool_executor", "generator"]

    async def test_两者都像_query优先且跳转卡仍出(self, academic_registry):
        """spec 7.3 规则 3：query 胜出，但两个 executor 结果可共存。"""
        graph = build_graph(FakeProvider(), academic_registry)
        collected, final = await run_graph(graph, "我成绩怎么样，顺便去成绩页看看")
        assert final["route"] == "query"
        assert final["tool_results"].get("resolve_page")   # sql_executor 先补跑了
        assert collected["nav_card"]["path"] == "/academic/grades"

    async def test_真模型选run_sql时_query轮仍补跑resolve出卡片(self, academic_registry):
        """用户实测「我有几门需要重修」无卡片：真 provider 对计数问句的
        function-calling 选中 run_sql，旧条件 tool_name=="resolve_page"
        为假 → 从不补跑 → tool_results 空 → 无卡片。规则 3 的补跑是
        输入驱动的——provider 选了谁都要把跳转意图问一次 resolve_page。"""
        class RunSqlProvider(FakeProvider):
            async def route(self, user_input, tools):
                return RouteDecision(intent=user_input, tool_name="run_sql",
                                     tool_args={"sql": "SELECT 1"},
                                     confidence=1.0)

        graph = build_graph(RunSqlProvider(), academic_registry)
        collected, final = await run_graph(graph, "我有几门需要重修")
        assert final["route"] == "query"
        assert final["steps"] == ["router", "sql_executor", "generator"]
        assert final["tool_results"].get("resolve_page")
        assert collected["nav_card"]["path"] == "/academic/makeup"

    async def test_都不像走answer(self, registry):
        graph = build_graph(FakeProvider(), registry)
        _, final = await run_graph(graph, "今天天气怎么样")
        assert final["route"] == "answer"
        assert final["steps"] == ["router", "generator"]


class Test澄清:
    async def test_跨学期且未指定学期_出clarify选项(self, academic_registry):
        graph = build_graph(FakeProvider(), academic_registry)
        collected, final = await run_graph(graph, "我的数据结构成绩")
        assert final["needs_clarification"] is True
        assert [o["label"] for o in final["clarification"]["options"]] == ["2025 秋", "2026 春"]
        clarify_events = [c for c in collected["custom"] if c[0] == "clarify"]
        assert clarify_events and clarify_events[0][1]["question"]

    async def test_点选项后第二轮收敛不再追问_spec9_2两轮闭环(self, academic_registry):
        """spec 9.2 集成测点名要的"澄清两轮闭环"：
        第一轮跨学期 → 出选项；用户点"2025 秋"后第二轮只剩该学期，不再追问。
        任何一轮 needs_clarification 仍为 True 都算没收敛。"""
        graph = build_graph(FakeProvider(), academic_registry)
        _, first = await run_graph(graph, "我的数据结构成绩")
        assert first["needs_clarification"] is True
        labels = [o["label"] for o in first["clarification"]["options"]]

        _, second = await run_graph(graph, f"{labels[0]} 我的数据结构成绩")
        assert second["needs_clarification"] is False
        assert second["clarification"] is None
        assert [r[1] for r in second["sql"]["rows"]] == ["2025 秋"]   # 只剩该学期
        assert second["error"] is None

    async def test_裸学期标签第二轮_仿ClarifyBar只发label(self, academic_registry):
        """生产 ClarifyBar 点选项只 send(label)——第二轮 user_input 是裸
        「2025 秋」，原话只在服务端 history 里。路由须凭学期词进 query、
        上下文须从 history 拼回，否则掉 answer 兜底/丢课程过滤。
        上一条用例喂的是 label+原话拼接，测不到这条真实生产路径。"""
        graph = build_graph(FakeProvider(), academic_registry)
        history = [
            {"role": "user", "content": "我的数据结构成绩"},
            {"role": "assistant", "content": "你要查哪个学期？"},
        ]
        collected, final = await run_graph(graph, "2025 秋", history=history)
        assert final["route"] == "query"
        assert final["steps"] == ["router", "sql_executor", "generator"]
        assert final["needs_clarification"] is False      # 不再追问
        assert final["error"] is None
        assert final["sql"]["rows"] and all(r[1] == "2025 秋" for r in final["sql"]["rows"])
        # 回答不是兜底话术（掉 answer 的旧症状）
        assert not any("我还不会" in t for t in collected["tokens"])


class Test真MCP路径:
    async def test_真MCP路径_str形态_卡片与schema都正确(self, mcp_shape_registry):
        """stdio_mcp 恒返 JSON 字符串；InMemory 直接给 dict，所以这个 seam
        在旧测试下必然漏掉。这里用返回 str 的 registry 替身钉住真路径。"""
        seen: dict = {}

        class RecordingProvider(FakeProvider):
            async def generate_sql(self, user_input: str, schema_json: str) -> str:
                seen["schema_json"] = schema_json
                return await super().generate_sql(user_input, schema_json)

        graph = build_graph(RecordingProvider(), mcp_shape_registry)
        collected, final = await run_graph(graph, "我成绩怎么样，顺便去成绩页看看")

        # 1) tool_results["resolve_page"]["data"] 必须是 dict（否则 generator 不出卡片）
        data = final["tool_results"]["resolve_page"]["data"]
        assert isinstance(data, dict), (
            f"resolve_page.data 必须是 dict，实为 {type(data).__name__}: {data!r}")
        assert collected["nav_card"] is not None, "str 形态没被解析 → 规则 3 卡片丢失"
        assert collected["nav_card"]["path"] == "/academic/grades"

        # 2) 收到 generate_sql 的 schema_json 必须 json.loads() 得回 list[...]，
        #    而不是"一段 JSON 字符串"（否则是双重编码）
        schema = json.loads(seen["schema_json"])
        assert isinstance(schema, list), (
            f"schema_json 双重编码：loads 后应为 list，实为 {type(schema).__name__}")
        assert schema and schema[0]["name"] == "v_grades"


class TestState扩展:
    def test_tool_results_累加不被覆盖(self):
        # 两次 executor 结果同在：第二次返回的 dict 与第一次合并，不是覆盖
        from app.agent.state import _merge_results

        first = {"resolve_page": {"ok": True, "data": {"path": "/a"}}}
        second = {"run_sql": {"ok": True, "row_count": 2}}
        merged = _merge_results(first, second)
        assert merged == {**first, **second}   # 异 key 并集
        # 同 key 后者覆盖（同工具重跑）
        assert _merge_results({"run_sql": {"row_count": 1}},
                              {"run_sql": {"row_count": 2}}) == {"run_sql": {"row_count": 2}}
        # None 容忍：langgraph 合并器首参可能是 None（该 key 尚无值）
        assert _merge_results(None, second) == second
        assert _merge_results(first, None) == first

    async def test_每节点都留step_details(self, academic_registry):
        # 跑一条 query 链路，断言 final_state["step_details"] 里
        # node 依次含 router/sql_executor/generator，且每个都有 latency_ms(int) 与 detail(dict)
        graph = build_graph(FakeProvider(), academic_registry)
        _, final = await run_graph(graph, "我这学期平均分多少")
        assert final["steps"] == ["router", "sql_executor", "generator"]
        details = final["step_details"]
        assert [d["node"] for d in details] == ["router", "sql_executor", "generator"]
        for d in details:
            assert isinstance(d["latency_ms"], int) and d["latency_ms"] >= 0
            assert isinstance(d["detail"], dict)
