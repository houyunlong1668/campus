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


async def run_graph(graph, user_input: str):
    collected = {"tokens": [], "nav_card": None, "custom": []}
    final = None
    async for mode, payload in graph.astream(
        {"user_input": user_input, "session_id": "s-test",
         "intent": None, "tool_name": None, "tool_args": {},
         "tool_results": {}, "answer": "", "nav_card": None, "steps": [], "error": None},
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
        # "查补考安排" 在 FakeProvider 规则里命中工具，但 registry 的 fake 只对含"成绩"/"课"的 intent 返回
        collected, final = await run_graph(graph, "查补考安排")  # 命中规则但 resolve 内部未命中
        assert final["steps"] == ["router", "tool_executor", "generator"]
        tool_events = [c for c in collected["custom"] if c[0] == "tool_call"]
        assert tool_events[0][1]["ok"] is False  # 失败仍走完，降级话术由 generator 出


class TestSSE:
    def test_sse_frame_format(self):
        from app.api.chat import sse_frame

        frame = sse_frame("token", {"text": "你好"})
        assert frame == 'event: token\ndata: {"text": "你好"}\n\n'
