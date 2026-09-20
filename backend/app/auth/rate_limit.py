import time


class LoginGuard:
    """同一学号连续失败若干次后锁一段时间。进程内计数，重启即清零。"""

    def __init__(self, allowed_failures: int = 5, lock_seconds: float = 60):
        self._allowed = allowed_failures
        self._lock = lock_seconds
        self._failures: dict[str, list[float]] = {}

    def check(self, key: str) -> float | None:
        """可尝试返回 None；被锁则返回还需等待的秒数。"""
        stamps = [t for t in self._failures.get(key, []) if time.time() - t < self._lock]
        self._failures[key] = stamps
        if len(stamps) < self._allowed:
            return None
        return self._lock - (time.time() - stamps[0])

    def record_failure(self, key: str) -> None:
        self._failures.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
