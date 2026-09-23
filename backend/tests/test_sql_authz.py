"""spec 9.1 A1–A6：必须走真 academic 子进程 + 真 SQLite，
mock 掉校验函数就测不出绕过——校验层和被测代码之间隔一层 mock 等于没测。"""
import asyncio
import os

import pytest

from app.agent.graph import build_graph
from app.config import Settings
from app.db.migrations import init_sqlite
from app.llm.base import RouteDecision
from app.llm.fake import FakeProvider
from app.tools.composite import CompositeRegistry
from app.tools.inmemory import InMemoryRegistry
from app.tools.stdio_mcp import stdio_registry

NAV_SPEC = {"name": "resolve_page", "description": "d",
            "input_schema": {"type": "object",
                             "properties": {"intent": {"type": "string"}},
                             "required": ["intent"]}}


class ScriptedProvider(FakeProvider):
    """按脚本吐 SQL：A3–A6 直接把要被拒的语句交给真 run_sql。"""

    def __init__(self, sql: str):
        self._sql = sql

    async def route(self, user_input, tools):
        return RouteDecision(intent=user_input, tool_name=None,
                             tool_args={}, confidence=1.0)

    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        return self._sql


@pytest.fixture
async def academic_registry(tmp_path):
    db_path = tmp_path / "campus.db"
    db = await init_sqlite(db_path)
    await db.execute(
        "INSERT INTO students (student_id, name, password_hash)"
        " VALUES ('20230001','周晓楠','x'),('20230007','林知远','x')")
    # course_code 是迁移里的 NOT NULL 列（brief 原样漏了它，建库即 IntegrityError）；
    # 值取 seed 脚本里同名的课程编号。外键未强制（无 PRAGMA foreign_keys=ON），
    # 故不建 courses 行也能插。
    await db.execute(
        "INSERT INTO enrollments (student_id, course_code, course_name, term, credits,"
        " score, grade_points, teacher) VALUES"
        " ('20230001','CS2052','数据结构','2026 春',4,87,3.7,'李慧'),"
        " ('20230007','CS2052','数据结构','2026 春',4,93,4.3,'李慧'),"
        " ('20230001','MATH2031','高等数学（上）','2025 秋',5,91,4.1,'王建国')")

    env = {**os.environ, "DB_BACKEND": "sqlite", "SQLITE_PATH": str(db_path)}
    nav = InMemoryRegistry({"resolve_page": {
        "spec": NAV_SPEC, "fn": lambda intent: {"path": "/x", "title": "t",
                                                "capabilities": []}}})
    # 绝对路径必走 Settings()：测试 cwd 是 backend/，相对路径 "mcp_servers/academic"
    # 解析不到（Task 4 踩过同一个坑）。
    #
    # 子进程的进出必须落在同一个 task 里：pytest-asyncio 的 async 生成器 fixture
    # 用 runner.run 分两次执行 setup 与 finalizer，各是一个新 task，anyio 退出
    # cancel scope 时会炸 "Attempted to exit cancel scope in a different task"
    # （实测：断言全过但 6 个用例全报 teardown error）。所以交给一个自持 task
    # 拉起来并收尾，测试里照常 await；同一条事件循环上的跨 task 调用本身没问题。
    ready, stop = asyncio.Event(), asyncio.Event()
    holder: dict = {}

    async def owner():
        async with stdio_registry(Settings().academic_server_dir, env=env) as acad:
            holder["registry"] = CompositeRegistry([nav, acad])
            ready.set()
            await stop.wait()

    task = asyncio.create_task(owner())
    await ready.wait()
    yield holder["registry"]
    stop.set()
    await task


async def run(provider, registry, student_id="20230001"):
    graph = build_graph(provider, registry)
    final = None
    async for mode, payload in graph.astream(
        {"user_input": "查我的成绩", "student_id": student_id,
         "history": [], "intent": None, "route": None,
         "tool_name": None, "tool_args": {}, "tool_results": {},
         "answer": "", "nav_card": None, "needs_clarification": False,
         "clarification": None, "sql": None, "steps": [], "error": None},
        stream_mode=["custom", "values"],
    ):
        if mode == "values":
            final = payload
    return final


class TestA1到A6:
    async def test_A1_只返回自己的行且scoped留下证据(self, academic_registry):
        final = await run(FakeProvider(), academic_registry)
        assert final["error"] is None
        rows = final["sql"]["rows"]
        assert rows and all("林知远" not in str(r) for r in rows)
        assert "student_id = ?" in final["sql"]["scoped"]

    async def test_A2_同名课程分数按人隔离(self, academic_registry):
        provider = ScriptedProvider(
            "SELECT course, term, score FROM v_grades"
            " WHERE course = '数据结构' ORDER BY term")
        final = await run(provider, academic_registry)
        assert final["sql"]["rows"] == [["数据结构", "2026 春", 87]]   # 不是 93

    async def test_A3_身份列拒绝并记录refused_code(self, academic_registry):
        provider = ScriptedProvider(
            "SELECT * FROM v_grades WHERE student_id='20230007'")
        final = await run(provider, academic_registry)
        assert final["sql"]["refused_code"] == "identity_column"
        assert final["sql"]["scoped"] == ""
        assert final["sql"]["row_count"] == 0

    async def test_A4_基表拒绝(self, academic_registry):
        final = await run(
            ScriptedProvider("SELECT * FROM enrollments"), academic_registry)
        assert final["sql"]["refused_code"] == "relation_not_whitelisted"

    async def test_A5_多语句拒绝(self, academic_registry):
        final = await run(
            ScriptedProvider("SELECT 1; DROP TABLE students"), academic_registry)
        assert final["sql"]["refused_code"] == "multi_statement"

    async def test_A6_耗时函数拒绝且不占连接(self, academic_registry, tmp_path):
        final = await run(ScriptedProvider("SELECT SLEEP(30)"), academic_registry)
        assert final["sql"]["refused_code"] == "cost_function"
        # 拒绝后库仍完好（表还在，连接没被占死）
        import aiosqlite
        async with aiosqlite.connect(tmp_path / "campus.db") as db:
            cur = await db.execute("SELECT COUNT(*) FROM students")
            assert (await cur.fetchone())[0] == 2
