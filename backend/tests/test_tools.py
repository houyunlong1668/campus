import pytest

from app.tools.base import ToolResult, validate_args
from app.tools.inmemory import InMemoryRegistry


class TestValidateArgs:
    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": ["intent"],
    }

    def test_valid(self):
        ok, err = validate_args(self.schema, {"intent": "查成绩"})
        assert ok and err is None

    def test_missing_required(self):
        ok, err = validate_args(self.schema, {})
        assert not ok and "intent" in err

    def test_wrong_type(self):
        ok, err = validate_args(self.schema, {"intent": 123})
        assert not ok and err

    def test_anyof_对象参数不再被当成字符串(self):
        """真模型回归：MCP 把 params 声明为 anyOf[object,null]，早先被误判成 str 而拒收。"""
        anyof_schema = {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "params": {"anyOf": [{"additionalProperties": True, "type": "object"},
                                     {"type": "null"}],
                           "default": None},
            },
            "required": ["intent"],
        }
        ok, err = validate_args(anyof_schema, {
            "intent": "查看这学期的课程安排",
            "params": {"semester": "current", "action": "view_schedule"},
        })
        assert ok, err
        assert validate_args(anyof_schema, {"intent": "查课表"})[0]


class TestInMemoryRegistry:
    async def test_list_and_call(self):
        async def fake_resolve(intent: str):
            return {"path": "/academic/grades"}

        registry = InMemoryRegistry(
            {
                "resolve_page": {
                    "spec": {
                        "name": "resolve_page",
                        "description": "解析页面",
                        "input_schema": TestValidateArgs.schema,
                    },
                    "fn": fake_resolve,
                }
            }
        )
        tools = await registry.list_tools()
        assert [t.name for t in tools] == ["resolve_page"]

        good = await registry.call_tool("resolve_page", {"intent": "查成绩"})
        assert isinstance(good, ToolResult) and good.ok and good.data["path"] == "/academic/grades"
        assert good.latency_ms >= 0

        bad = await registry.call_tool("resolve_page", {"intent": 123})
        assert not bad.ok and bad.error  # 参数校验拦截，fn 未执行

        missing = await registry.call_tool("nope", {})
        assert not missing.ok
