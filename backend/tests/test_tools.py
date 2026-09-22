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

    def test_未声明字段被拒(self):
        """S3 的 student_id 注入依赖这条底线：schema 没写的键不能悄悄通过校验。"""
        ok, err = validate_args(self.schema, {"intent": "查成绩", "student_id": "20230002"})
        assert not ok and "student_id" in err

    def test_类型正确的多余键同样被拒(self):
        ok, err = validate_args(
            self.schema, {"intent": "查成绩", "params": {"a": 1}, "extra": 1})
        assert not ok and "extra" in err

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


def test_CompositeRegistry_按工具名分派():
    import asyncio

    from app.tools.composite import CompositeRegistry
    from app.tools.inmemory import InMemoryRegistry

    nav = InMemoryRegistry({"resolve_page": {"spec": {
        "name": "resolve_page", "description": "d",
        "input_schema": {"type": "object", "properties": {"intent": {"type": "string"}},
                         "required": ["intent"]}},
        "fn": lambda intent: {"path": "/x"}}})
    acad = InMemoryRegistry({"run_sql": {"spec": {
        "name": "run_sql", "description": "d",
        "input_schema": {"type": "object",
                         "properties": {"sql": {"type": "string"}},
                         "required": ["sql"]}},
        "fn": lambda sql: {"rows": []}}})

    reg = CompositeRegistry([nav, acad])
    names = asyncio.run(reg.list_tools())
    assert {s.name for s in names} == {"resolve_page", "run_sql"}

    res = asyncio.run(reg.call_tool("run_sql", {"sql": "SELECT 1"}))
    assert res.ok and res.data == {"rows": []}
    unknown = asyncio.run(reg.call_tool("nope", {}))
    assert unknown.ok is False and "未知工具" in unknown.error


async def test_academic子进程真能被拉起并列出工具():
    """端到端：确认 env 透传与独立 uv 项目都对。跑不通说明 Task 4 Step 6 没做实。"""
    import os

    from app.config import Settings
    from app.tools.stdio_mcp import stdio_registry

    s = Settings(db_backend="sqlite")
    env = {**os.environ, "DB_BACKEND": "sqlite",
           "SQLITE_PATH": str(s.sqlite_path)}
    # brief 原文是 Path("mcp_servers/academic")，相对 cwd=backend 解析不到——
    # 改用 Settings 的绝对路径（与 test_stdio_mcp 的 get_settings() 同一惯例）
    async with stdio_registry(s.academic_server_dir, env=env) as reg:
        names = {t.name for t in await reg.list_tools()}
    assert {"describe_schema", "run_sql"} <= names


def test_TRUSTED_ARGS_丢弃模型塞的并注入会话学号():
    from app.tools.base import TRUSTED_ARGS, with_trusted_args

    assert TRUSTED_ARGS == {"run_sql": {"student_id"}}
    out = with_trusted_args("run_sql",
                            {"sql": "SELECT 1", "student_id": "20230007"},
                            student_id="20230001")
    assert out == {"sql": "SELECT 1", "student_id": "20230001"}  # 塞的被丢弃


def test_TRUSTED_ARGS_无student_id会话时不注入_让必填校验去拦():
    from app.tools.base import with_trusted_args

    out = with_trusted_args("run_sql", {"sql": "SELECT 1"}, student_id=None)
    assert out == {"sql": "SELECT 1"}
    assert "student_id" not in out


def test_TRUSTED_ARGS_非受信工具原样透传():
    from app.tools.base import with_trusted_args

    args = {"intent": "查成绩"}
    assert with_trusted_args("resolve_page", args, student_id="20230001") is args


def test_strip_trusted_从schema里删掉student_id与required项():
    from app.tools.base import strip_trusted

    schema = {
        "type": "object",
        "properties": {"sql": {"type": "string"},
                       "student_id": {"type": "string"}},
        "required": ["sql", "student_id"],
    }
    out = strip_trusted("run_sql", schema)
    assert "student_id" not in out["properties"]
    assert out["required"] == ["sql"]
    assert "student_id" not in str(out)


def test_strip_trusted_不动非受信工具的schema():
    from app.tools.base import strip_trusted

    schema = {"type": "object", "properties": {"intent": {"type": "string"}},
              "required": ["intent"]}
    assert strip_trusted("resolve_page", schema) == schema


async def test_stdio_registry_给模型的run_sql_schema里没有student_id():
    """spec 7.4：描述里留着这列与模型看得见这列是两件事，后者会教模型拿它过滤。"""
    import os

    from app.config import Settings
    from app.tools.stdio_mcp import stdio_registry

    s = Settings(db_backend="sqlite")
    env = {**os.environ, "DB_BACKEND": "sqlite", "SQLITE_PATH": str(s.sqlite_path)}
    # 不用 brief 的 Path("mcp_servers/academic")：测试 cwd 是 backend/，相对路径
    # 解析不到（Task 4 踩过），改用 Settings 的绝对路径字段
    async with stdio_registry(s.academic_server_dir, env=env) as reg:
        spec = next(t for t in await reg.list_tools() if t.name == "run_sql")
    assert "student_id" not in str(spec.input_schema)


async def test_先校验后注入_注入值不会被extra_forbid误拒():
    """裁决 A 的守护测试：schema 已剥掉 student_id，args 注入后校验必须仍通过。
    把调用顺序改回「先注入后校验」这条就红。"""
    import os

    from app.config import Settings
    from app.tools.stdio_mcp import stdio_registry

    s = Settings(db_backend="sqlite")
    env = {**os.environ, "DB_BACKEND": "sqlite", "SQLITE_PATH": str(s.sqlite_path)}
    async with stdio_registry(s.academic_server_dir, env=env) as reg:
        # 走一次含 student_id 注入的完整 call_tool：
        # 顺序对（先校验后注入）→ 校验通过，且 server 侧必填的 student_id
        # 已由服务端写入（缺了它 MCP 会在 server 侧拒参，result.ok=False）；
        # 顺序错（先注入后校验）→ 「已剥离的 schema」+ extra="forbid"
        # 会在校验步拒掉注入键，error 含"参数校验失败"。
        result = await reg.call_tool(
            "run_sql", {"sql": "SELECT course, score FROM v_grades"},
            student_id="20230001")
    assert result.ok, result.error
    assert "参数校验失败" not in (result.error or "")
