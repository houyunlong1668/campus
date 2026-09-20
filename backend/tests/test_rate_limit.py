import time

from app.auth.rate_limit import LoginGuard


def test_五次失败内仍允许():
    guard = LoginGuard(allowed_failures=5, lock_seconds=60)
    for _ in range(5):
        assert guard.check("20230001") is None
        guard.record_failure("20230001")
    assert guard.check("20230001") is not None


def test_锁定后返回剩余秒数():
    guard = LoginGuard(allowed_failures=1, lock_seconds=60)
    guard.record_failure("x")
    wait = guard.check("x")
    assert wait is not None and 0 < wait <= 60


def test_锁定窗口过后自动放行():
    guard = LoginGuard(allowed_failures=1, lock_seconds=0.01)
    guard.record_failure("x")
    time.sleep(0.02)
    assert guard.check("x") is None


def test_成功登录清零计数():
    guard = LoginGuard(allowed_failures=2, lock_seconds=60)
    guard.record_failure("x")
    guard.reset("x")
    assert guard.check("x") is None
    guard.record_failure("x")
    assert guard.check("x") is None


def test_不同学号互不影响():
    guard = LoginGuard(allowed_failures=1, lock_seconds=60)
    guard.record_failure("a")
    assert guard.check("a") is not None
    assert guard.check("b") is None
