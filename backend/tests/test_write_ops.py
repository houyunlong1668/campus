"""写操作服务与 /confirm 端点：幂等、属主校验、鉴权；Task 6 端到端确认链路。"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed_academic import seed_academic  # noqa: E402

from app.api.academic import router as academic_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402
from app.api.confirm import router as confirm_router  # noqa: E402
from app.auth.rate_limit import LoginGuard  # noqa: E402
from app.auth.session import SessionStore  # noqa: E402
from app.auth.students import build_student_repository  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.migrations import init_sqlite  # noqa: E402
from app.db.repository import build_repository  # noqa: E402
from app.llm.fake import FakeProvider  # noqa: E402
from app.tools.inmemory import InMemoryRegistry  # noqa: E402
from app.write_ops import PendingActionStore, register_makeup  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """照抄 test_academic_api 的 client 构造，另挂本任务的 pending_actions 与 confirm 路由。"""
    db = asyncio.run(init_sqlite(tmp_path / "campus.db"))
    asyncio.run(seed_academic(db))

    app = FastAPI()
    app.state.settings = Settings()
    app.state.db = db
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.pending_actions = PendingActionStore()

    # /chat 四件套（注 2）：照 test_chat_auth 的 env fixture 补——
    # 缺任一件端到端直接 404/500；加组件不改行为，既有 6 条不受影响。
    async def fake_resolve(intent: str, params: dict | None = None):
        return {"path": "/academic/grades", "title": "成绩查询", "capabilities": []}

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
    app.include_router(academic_router)
    app.include_router(confirm_router)
    app.include_router(chat_router)
    with TestClient(app) as c:
        yield c


def login(client, sid):
    """照抄 test_chat_auth.login 的写法，只把学号参数化（本文件要在两个账号间切换）。"""
    assert client.post("/auth/login",
                       json={"student_id": sid, "password": "demo1234"}).status_code == 200


def _chat_events(client, message):
    """同步发 /chat 读全文，按 event:/data: 成对解成 [{event, data}]。
    解析逻辑照 test_chat_auth 既有写法；同步形态与本文件既有 6 条测试一致
    （helper 与调用处都不带 await，见简报注 4）。"""
    r = client.post("/chat", json={"message": message})
    assert r.status_code == 200
    lines = [ln for ln in r.text.splitlines() if ln]
    events = []
    for i, ln in enumerate(lines):
        if ln.startswith("event: ") and i + 1 < len(lines) \
                and lines[i + 1].startswith("data: "):
            events.append({"event": ln[7:],
                           "data": json.loads(lines[i + 1][6:])})
    return events


def _confirm(client, course_code, student_id="20230001"):
    """直接走 store 造合法 action_id 再 POST——写意图链路是 Task 6 的事，本任务不依赖图。"""
    action_id = client.app.state.pending_actions.create(
        student_id, "makeup_register", {"course_code": course_code})
    return client.post("/confirm", json={"action_id": action_id})


def test_报名中课程可注册并翻转状态(client):
    # 20230001 的 MATH2041 seed 为「报名中」：/confirm 必须登记并把它翻成「已报名」
    login(client, "20230001")
    r = _confirm(client, "MATH2041")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"] == {"status": "registered",
                              "course": "高等数学（下）", "kind": "补考"}
    item = next(i for i in client.get("/api/makeup").json()["items"]
                if i["code"] == "MATH2041")
    assert item["status"] == "已报名"


def test_重复确认幂等返回already(client):
    """幂等指 register_makeup 直接调两次：第二次 already 且 registrations 不叠行。

    （确认后动作已 pop、再确认 404 是一次性语义，见 404 用例，不是这里的幂等场景。）
    """
    db = client.app.state.db
    first = asyncio.run(register_makeup(db, "20230001", "MATH2041"))
    second = asyncio.run(register_makeup(db, "20230001", "MATH2041"))
    assert first["status"] == "registered"
    assert second["status"] == "already"
    assert second["course"] == "高等数学（下）"
    assert second["kind"] == "补考"
    rows = asyncio.run(db.fetch_all(
        "SELECT COUNT(*) AS n FROM makeup_registrations"
        " WHERE student_id = ? AND course_code = ?",
        ("20230001", "MATH2041")))
    assert rows[0]["n"] == 1  # 先查后写的幂等必须保证不产生重复行


def test_已报名课程再报返回already(client):
    """状态 already 场景（与上一条的行幂等互补）：PHY1031 seed 已是「已报名」，
    首调 /confirm 就必须 already（否则前端会把已报名的课显示成"报名成功"），
    且不插登记行——没通过 App 注册过就不该留登记痕迹。"""
    login(client, "20230001")
    r = _confirm(client, "PHY1031")
    assert r.status_code == 200
    assert r.json()["result"] == {"status": "already",
                                  "course": "大学物理（上）", "kind": "补考"}
    item = next(i for i in client.get("/api/makeup").json()["items"]
                if i["code"] == "PHY1031")
    assert item["status"] == "已报名"  # 状态保持，不翻转
    rows = asyncio.run(client.app.state.db.fetch_all(
        "SELECT COUNT(*) AS n FROM makeup_registrations"
        " WHERE student_id = ? AND course_code = ?", ("20230001", "PHY1031")))
    assert rows[0]["n"] == 0  # already 路径不插行


def test_无此课程返回400(client):
    login(client, "20230001")
    r = _confirm(client, "NOPE9999")
    assert r.status_code == 400
    assert "NOPE9999" in r.json()["detail"]  # WriteOpError → HTTP 400


def test_无Cookie打confirm返回401(client):
    r = client.post("/confirm", json={"action_id": "irrelevant"})
    assert r.status_code == 401


def test_动作不存在或属主不符返回404(client):
    store = client.app.state.pending_actions
    action_id = store.create("20230001", "makeup_register", {"course_code": "MATH2041"})
    # 登录 20230002 去 pop 20230001 的动作 → 404；「不存在/过期/别人的」不作区分
    login(client, "20230002")
    assert client.post("/confirm", json={"action_id": action_id}).status_code == 404
    assert client.post("/confirm", json={"action_id": "no-such-action"}).status_code == 404
    # pop 一次性语义：属主不符也已把动作销毁，原属主再确认同样 404
    login(client, "20230001")
    assert client.post("/confirm", json={"action_id": action_id}).status_code == 404
    # 别人的失败确认没产生任何写入：MATH2041 仍是「报名中」
    item = next(i for i in client.get("/api/makeup").json()["items"]
                if i["code"] == "MATH2041")
    assert item["status"] == "报名中"
    # 会话是身份唯一来源：请求体塞 student_id 整包 422（extra="forbid"）
    assert client.post("/confirm", json={"action_id": "x",
                                         "student_id": "20230001"}).status_code == 422


class Test确认链路端到端:
    """Task 6 验收 2 全链路：聊天 → confirm_card →（不点确认则不写）→
    POST /confirm → 状态翻转。三条都要先 login（注 3）：/chat 与 /api/makeup
    都依赖会话。"""

    def test_写意图出确认卡且未执行(self, client):
        login(client, "20230001")
        events = _chat_events(client, "帮我报名大学物理（上）的补考")
        card = next((e["data"] for e in events if e["event"] == "confirm_card"), None)
        assert card is not None and card["action"] == "makeup_register"
        # 未点确认：库里状态没变
        items = client.get("/api/makeup").json()["items"]
        assert next(i for i in items if i["code"] == "PHY1031")["status"] == "已报名"  # seed 本来就是已报名
        # 换报名中的课程再验「未执行」：MATH2041 出卡但不确认，状态必须仍是「报名中」
        events2 = _chat_events(client, "帮我报名高等数学（下）的补考")
        card2 = next(e["data"] for e in events2 if e["event"] == "confirm_card")
        assert card2["action"] == "makeup_register"
        items = client.get("/api/makeup").json()["items"]
        assert next(i for i in items if i["code"] == "MATH2041")["status"] == "报名中"

    def test_点确认后执行并翻转(self, client):
        login(client, "20230001")
        events = _chat_events(client, "帮我报名高等数学（下）的补考")
        card = next(e["data"] for e in events if e["event"] == "confirm_card")
        r = client.post("/confirm", json={"action_id": card["action_id"]})
        assert r.status_code == 200 and r.json()["result"]["status"] == "registered"
        items = client.get("/api/makeup").json()["items"]
        assert next(i for i in items if i["code"] == "MATH2041")["status"] == "已报名"

    def test_重复点同一卡第二次404(self, client):
        login(client, "20230001")
        events = _chat_events(client, "帮我报名高等数学（下）的补考")
        card = next(e["data"] for e in events if e["event"] == "confirm_card")
        assert client.post("/confirm", json={"action_id": card["action_id"]}).status_code == 200
        # 一次性语义：pop 已焚，第二次 404，状态不叠行（registrations 仍 1 行）
        assert client.post("/confirm", json={"action_id": card["action_id"]}).status_code == 404
        rows = asyncio.run(client.app.state.db.fetch_all(
            "SELECT COUNT(*) AS n FROM makeup_registrations"
            " WHERE student_id = '20230001' AND course_code = 'MATH2041'"))
        assert rows[0]["n"] == 1
