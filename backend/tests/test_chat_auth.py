import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.auth.rate_limit import LoginGuard
from app.auth.session import SessionStore
from app.auth.students import build_student_repository, seed_students
from app.config import Settings
from app.db.migrations import init_sqlite
from app.db.repository import build_repository
from app.llm.fake import FakeProvider
from app.tools.inmemory import InMemoryRegistry


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "campus.db"

    async def setup():
        db = await init_sqlite(path)
        await seed_students(db)
        return db

    db = asyncio.run(setup())

    async def fake_resolve(intent: str, params: dict | None = None):
        return {"path": "/academic/grades", "title": "成绩查询", "capabilities": []}

    app = FastAPI()
    app.state.settings = Settings()
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.provider = FakeProvider()
    app.state.repository = build_repository(db)
    app.state.registry = InMemoryRegistry({
        "resolve_page": {
            "spec": {
                "name": "resolve_page", "description": "解析页面",
                "input_schema": {"type": "object",
                                 "properties": {"intent": {"type": "string"}},
                                 "required": ["intent"]},
            },
            "fn": fake_resolve,
        }
    })
    app.include_router(auth_router)
    app.include_router(chat_router)
    return app, path


def login(client):
    client.post("/auth/login", json={"student_id": "20230002", "password": "demo1234"})


def test_未登录打chat返回401(env):
    app, _ = env
    with TestClient(app) as c:
        assert c.post("/chat", json={"message": "查成绩"}).status_code == 401


def test_登录后带session_id被422拒绝(env):
    """会话标识不再由客户端提供：多一个字段就整个请求拒掉，而不是忽略它继续跑。"""
    app, _ = env
    with TestClient(app) as c:
        login(c)
        assert c.post("/chat", json={"message": "查成绩"}).status_code == 200
        assert c.post(
            "/chat", json={"message": "查成绩", "session_id": "s1"}).status_code == 422
        assert c.post(
            "/chat", json={"message": "查成绩", "student_id": "20230001"}).status_code == 422


def test_schema层只接受message():
    import pydantic

    from app.schemas import ChatRequest

    ChatRequest.model_validate({"message": "查成绩"})
    for extra in ({"session_id": "s1"}, {"student_id": "20230002"}, {"role": "admin"}):
        with pytest.raises(pydantic.ValidationError):
            ChatRequest.model_validate({"message": "查成绩", **extra})


def test_登录后对话落库带上该学号(env):
    app, path = env
    with TestClient(app) as c:
        login(c)
        r = c.post("/chat", json={"message": "查成绩"})
        assert r.status_code == 200
        assert "event: done" in r.text

    import aiosqlite

    async def read():
        async with aiosqlite.connect(path) as db:
            return await (await db.execute(
                "SELECT student_id FROM conversations ORDER BY id DESC LIMIT 1")).fetchone()

    assert asyncio.run(read())[0] == "20230002"


def test_done事件带出conversation_id(env):
    import json

    app, _ = env
    with TestClient(app) as c:
        login(c)
        text = c.post("/chat", json={"message": "查成绩"}).text

    done = next(ln for ln in text.splitlines()
                if ln.startswith("data:") and "conversation_id" in ln)
    payload = json.loads(done[len("data:"):].strip())
    assert isinstance(payload["conversation_id"], int)
    assert "session_id" not in payload


def test_不同账号的对话互相独立(env):
    """A 与 B 各问一次，落库应得到两条不同 student_id 的会话。"""
    app, path = env
    import aiosqlite

    with TestClient(app) as c:
        c.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
        c.post("/chat", json={"message": "查成绩"})
        c.post("/auth/logout")
        c.post("/auth/login", json={"student_id": "20230002", "password": "demo1234"})
        c.post("/chat", json={"message": "查成绩"})

    async def read():
        async with aiosqlite.connect(path) as db:
            rows = await (await db.execute(
                "SELECT student_id FROM conversations ORDER BY id")).fetchall()
        return [r[0] for r in rows]

    assert asyncio.run(read()) == ["20230001", "20230002"]


@pytest.fixture
def sql_env(tmp_path):
    """带 describe_schema/run_sql 的最小链路。
    这里用 InMemory 假 run_sql 而不是真子进程——本任务只断言
    "state['sql'] 被落库、拒绝时发 sql_refused 事件"这两条接线；
    真 academic 子进程的越权语义归 Task 10。"""
    path = tmp_path / "campus.db"

    async def setup():
        db = await init_sqlite(path)
        await seed_students(db)
        return db

    db = asyncio.run(setup())

    # student_id：TRUSTED_ARGS 让 call_tool 在校验后注入这一参（裁决 A），
    # 签名只写 sql 会被 timed_call 吞成 ok=False（同 test_graph 的 academic fixture）。
    async def fake_run_sql(sql: str, student_id: str | None = None):
        if "student_id='20230007'" in sql:
            return {"ok": False, "refused_code": "identity_column",
                    "refused_message": "无需指定身份，系统已按你的账号过滤",
                    "scoped_sql": "", "columns": [], "rows": [],
                    "row_count": 0, "latency_ms": 1}
        return {"ok": True, "refused_code": None, "refused_message": None,
                "scoped_sql": "SELECT course FROM (SELECT * FROM v_grades"
                              " WHERE student_id = ?) AS v_grades",
                "columns": ["course"], "rows": [["高等数学（上）"]],
                "row_count": 1, "latency_ms": 1}

    async def fake_describe():
        return [{"name": "v_grades", "columns": ["course", "term"],
                 "description": "成绩视图"}]

    app = FastAPI()
    app.state.settings = Settings()
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.provider = FakeProvider()
    app.state.repository = build_repository(db)
    app.state.registry = InMemoryRegistry({
        "describe_schema": {
            "spec": {"name": "describe_schema", "description": "d",
                     "input_schema": {"type": "object", "properties": {}}},
            "fn": fake_describe,
        },
        "run_sql": {
            "spec": {"name": "run_sql", "description": "d",
                     "input_schema": {"type": "object",
                                      "properties": {"sql": {"type": "string"}},
                                      "required": ["sql"]}},
            "fn": fake_run_sql,
        },
    })
    app.include_router(auth_router)
    app.include_router(chat_router)
    return app, path


def test_查数成功把scoped_sql落进sql_queries(sql_env):
    """A1 的落库半边：scoped 必须能看到 student_id = ?——
    这是"改写真的发生了"的证据，光看返回行数看不出来。"""
    import asyncio
    import json  # noqa: F401  （与本文件其它测试的局部 import 风格一致）

    import aiosqlite

    app, path = sql_env
    with TestClient(app) as c:
        login(c)
        text = c.post("/chat", json={"message": "我的高数成绩"}).text
    assert "event: sql_result" in text

    async def read():
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT sql_raw, sql_scoped, refused_code, row_count"
                " FROM sql_queries")
            return await cur.fetchall()

    rows = asyncio.run(read())
    assert len(rows) == 1
    sql_raw, sql_scoped, refused_code, row_count = rows[0]
    assert "v_grades" in sql_raw                    # 记的是模型原文
    assert "student_id = ?" in sql_scoped           # 记的是改写后文本
    assert refused_code is None
    assert row_count == 1


def test_拒绝时发sql_refused错误事件(sql_env):
    import json

    app, path = sql_env

    class RefusingProvider(FakeProvider):
        async def generate_sql(self, user_input: str, schema_json: str) -> str:
            return "SELECT * FROM v_grades WHERE student_id='20230007'"

    app.state.provider = RefusingProvider()
    with TestClient(app) as c:
        login(c)
        text = c.post("/chat", json={"message": "陈默的高数成绩"}).text

    # 把 SSE 的 event/data 成对解出来，别靠子串猜
    lines = [ln for ln in text.splitlines() if ln]
    events = []
    for i, ln in enumerate(lines):
        if ln.startswith("event: ") and i + 1 < len(lines) \
                and lines[i + 1].startswith("data: "):
            events.append((ln[7:], json.loads(lines[i + 1][6:])))
    assert [d["code"] for e, d in events if e == "error"] == ["sql_refused"]

    import asyncio

    import aiosqlite

    async def read():
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT refused_code FROM sql_queries")
            return await cur.fetchall()

    # 拒绝也留痕，否则 A3/A4/A5 无从复盘
    assert asyncio.run(read()) == [("identity_column",)]
