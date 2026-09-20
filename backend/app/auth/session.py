import secrets
import time
from dataclasses import dataclass

COOKIE_NAME = "sid"
SID_BYTES = 32


@dataclass
class Session:
    sid: str
    student_id: str
    expires_at: float

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


class SessionStore:
    """进程内会话。重启即全部失效——spec 第 1 节已确认可接受。"""

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, student_id: str) -> Session:
        session = Session(
            sid=secrets.token_urlsafe(SID_BYTES),
            student_id=student_id,
            expires_at=time.time() + self._ttl,
        )
        self._sessions[session.sid] = session
        return session

    def get(self, sid: str) -> Session | None:
        session = self._sessions.get(sid)
        if session is None:
            return None
        if session.is_expired(time.time()):
            self._sessions.pop(sid, None)
            return None
        return session

    def revoke(self, sid: str) -> bool:
        return self._sessions.pop(sid, None) is not None

    def count(self) -> int:
        return len(self._sessions)
