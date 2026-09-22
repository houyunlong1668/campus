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
