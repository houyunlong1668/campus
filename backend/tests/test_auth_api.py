import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.auth.rate_limit import LoginGuard
from app.auth.session import SessionStore
from app.auth.students import build_student_repository, seed_students
from app.config import Settings
from app.db.migrations import init_sqlite


@pytest.fixture
def client(tmp_path):
    """最小 app：只挂 auth 路由，不启 MCP 子进程，避免把 lifespan 的重启动拉进单测。"""

    async def setup():
        db = await init_sqlite(tmp_path / "campus.db")
        await seed_students(db)
        return db

    db = asyncio.run(setup())

    app = FastAPI()
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.settings = Settings(cookie_secure=False)
    app.include_router(auth_router)
    with TestClient(app) as c:
        yield c


def test_正确凭据登录成功并下发Cookie(client):
    r = client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    assert r.status_code == 200
    assert r.json()["name"] == "周晓楠"
    assert r.json()["student_id"] == "20230001"

    cookie_header = r.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert len(r.cookies.get("sid")) >= 32


def test_密码错误返回统一文案(client):
    r = client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]["message"] == "学号或密码不正确"
    assert r.json()["detail"]["code"] == "bad_credentials"


def test_不存在的学号与密码错误响应一致(client):
    """两者同码同文案，否则等于送一个账号枚举接口。"""
    wrong_pw = client.post("/auth/login", json={"student_id": "20990001", "password": "wrong"})
    right_pw = client.post("/auth/login", json={"student_id": "20990001", "password": "demo1234"})

    assert wrong_pw.status_code == right_pw.status_code == 401
    assert wrong_pw.json() == right_pw.json()


def test_me需要会话(client):
    unauthed = client.get("/auth/me")
    assert unauthed.status_code == 401
    assert unauthed.json()["detail"]["code"] == "unauthenticated"

    client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["student_id"] == "20230001"


def test_登出后会话立即失效(client):
    client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    assert client.get("/auth/me").status_code == 200

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_连续失败五次后第六次被限流(client):
    for _ in range(5):
        client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    r = client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})

    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "too_many_attempts"


def test_登录成功清零失败计数(client):
    client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    assert client.post(
        "/auth/login", json={"student_id": "20230001", "password": "demo1234"}).status_code == 200

    # 已清零：再错 5 次才锁
    for _ in range(5):
        client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    assert client.post(
        "/auth/login", json={"student_id": "20230001", "password": "demo1234"}).status_code == 429


def test_登录请求体多余字段被拒(client):
    r = client.post("/auth/login", json={
        "student_id": "20230001", "password": "demo1234", "role": "admin"})
    assert r.status_code == 422


def test_空消息体字段被拒(client):
    assert client.post("/auth/login", json={"student_id": "", "password": "x"}).status_code == 422
