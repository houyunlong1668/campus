import time

from app.auth.session import COOKIE_NAME, SessionStore


def test_create后可查回():
    store = SessionStore(ttl_seconds=43200)
    session = store.create("20230001")

    assert session.student_id == "20230001"
    assert store.get(session.sid) is not None
    assert store.count() == 1


def test_sid足够长且每次不同():
    store = SessionStore(ttl_seconds=43200)
    a, b = store.create("x"), store.create("x")
    assert a.sid != b.sid and len(a.sid) >= 32


def test_过期会话查不到并被清掉():
    store = SessionStore(ttl_seconds=1)
    session = store.create("20230001")
    session.expires_at = time.time() - 1

    assert store.get(session.sid) is None
    assert store.count() == 0


def test_revoke后查不到():
    store = SessionStore(ttl_seconds=43200)
    session = store.create("20230001")

    assert store.revoke(session.sid) is True
    assert store.get(session.sid) is None
    assert store.revoke("不存在") is False


def test_未知sid返回None不抛异常():
    assert SessionStore(ttl_seconds=60).get("random") is None


def test_cookie名固定为sid():
    assert COOKIE_NAME == "sid"
