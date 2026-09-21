# backend/tests/test_academic_api.py
import asyncio
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed_academic import seed_academic  # noqa: E402

from app.api.academic import router as academic_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.auth.rate_limit import LoginGuard  # noqa: E402
from app.auth.session import SessionStore  # noqa: E402
from app.auth.students import build_student_repository  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.migrations import init_sqlite  # noqa: E402

WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2} 周[一二三四五六日] \d{2}:\d{2}$")


@pytest.fixture
def client(tmp_path):
    db = asyncio.run(init_sqlite(tmp_path / "campus.db"))
    asyncio.run(seed_academic(db))

    app = FastAPI()
    app.state.settings = Settings()
    app.state.db = db
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.include_router(auth_router)
    app.include_router(academic_router)
    with TestClient(app) as c:
        yield c


def _login(c, sid):
    assert c.post("/auth/login", json={"student_id": sid, "password": "demo1234"}).status_code == 200


def test_四端点未登录一律401(client):
    for url in ("/api/grades", "/api/schedule", "/api/makeup", "/api/loans"):
        assert client.get(url).status_code == 401, url


def test_成绩含挂科行且只含本人(client):
    _login(client, "20230001")
    rows = client.get("/api/grades").json()["grades"]
    assert len(rows) == 13
    assert {r["name"] for r in rows} >= {"数据结构（暑期补习）", "大学物理（上）"}
    assert next(r for r in rows if r["name"] == "数据结构（暑期补习）")["score"] == 87
    assert next(r for r in rows if r["name"] == "大学物理（上）")["score"] == 56
    assert set(rows[0]) == {"name", "code", "credits", "score", "term"}


def test_课表形状periods与weeks(client):
    _login(client, "20230001")
    courses = client.get("/api/schedule").json()["courses"]
    assert len(courses) == 12
    first = next(c for c in courses if c["code"] == "MATH2041")
    assert first["day"] == 1 and first["periods"] == [1, 2]
    assert first["weeks"] == "1-16" and first["kind"] == "必修" and first["domain"] == "math"


def test_补考时间已格式化且名额有文案(client):
    _login(client, "20230001")
    items = client.get("/api/makeup").json()["items"]
    assert len(items) == 3
    assert all(WEEK_RE.match(i["when"]) for i in items if i["status"] != "报名中")
    opening = next(i for i in items if i["status"] == "报名中")
    assert opening["when"].startswith("报名截止 ")
    assert opening["seats"] == "剩 23 / 120"
    # 补考/重修没有名额列：seats 必须是 JSON null，而不是 ""或"剩  / "之类假文案
    assert next(i for i in items if i["course"] == "大学物理（上）")["seats"] is None


def test_借阅含逾期且daysLeft由服务端算(client):
    _login(client, "20230001")
    items = client.get("/api/loans").json()["items"]
    assert len(items) == 4
    # seed 把四本书放在运行日起算 +2 / -3 / +11 / +6 天：钉死具体值，_days_left 差一天就红
    assert {i["title"]: i["daysLeft"] for i in items} == {
        "算法导论（第三版）上册": 2,
        "深入理解计算机系统（第 3 版）": -3,
        "数据库系统概念（第 7 版）": 11,
        "人类简史：从动物到上帝": 6,
    }
    assert any(i["daysLeft"] < 0 for i in items)
    assert all(WEEK_RE.match(i["due"]) for i in items)
    assert set(items[0]) == {"title", "callNo", "due", "daysLeft", "place"}


def test_已归还的书不出现在借阅里(client):
    """returned_at IS NULL 这道过滤：库里确实有一条已还的，端点必须不返回它。"""
    rows = asyncio.run(
        client.app.state.db.fetch_all(
            "SELECT COUNT(*) AS n FROM library_loans"
            " WHERE student_id = '20230001' AND returned_at IS NOT NULL"))
    assert rows[0]["n"] == 1  # 靶子存在，否则下面的断言是空的
    _login(client, "20230001")
    titles = {i["title"] for i in client.get("/api/loans").json()["items"]}
    assert "编译原理（第 2 版）" not in titles
    assert len(titles) == 4


def test_陈默是建筑学数据与周晓楠无交集(client):
    _login(client, "20230002")
    mine = {g["code"] for g in client.get("/api/grades").json()["grades"]}
    assert len(client.get("/api/schedule").json()["courses"]) == 6
    assert client.get("/api/makeup").json()["items"] == []
    _login(client, "20230001")
    theirs = {g["code"] for g in client.get("/api/grades").json()["grades"]}
    assert mine.isdisjoint(theirs)


def test_同名课程分数按人隔离(client):
    _login(client, "20230007")
    lin = next(g for g in client.get("/api/grades").json()["grades"]
               if g["name"] == "数据结构（暑期补习）")
    assert lin["score"] == 93  # 周晓楠同门课是 87
