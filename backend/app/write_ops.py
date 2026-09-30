"""写操作与待确认动作。写一律先经 PendingActionStore 确认（spec §4 /confirm 语义）。"""
import time
import uuid
from dataclasses import dataclass, field

from .db.base import Database


class WriteOpError(Exception):
    """写操作业务失败（如无对应课程、状态不允许），映射 HTTP 400。"""


async def register_makeup(db: Database, student_id: str, course_code: str) -> dict:
    """补考/重修报名：报名中→已报名；已有登记行或条目已是已报名→already（不重复登记，
    状态 already 的路径不插登记行——没通过 App 注册过就不该留登记痕迹）；
    其余状态（如待缴费）只登记不翻转。幂等靠先查后写（UNIQUE(student_id, course_code)
    语义），单用户演示无并发写者；不堆方言分支。"""
    rows = await db.fetch_all(
        "SELECT course_name, kind, status FROM makeup_items"
        " WHERE student_id = ? AND course_code = ?", (student_id, course_code))
    if not rows:
        raise WriteOpError(f"没有课程 {course_code} 的补考或重修条目")
    item = rows[0]
    existing = await db.fetch_all(
        "SELECT id FROM makeup_registrations WHERE student_id = ? AND course_code = ?",
        (student_id, course_code))
    if existing or item["status"] == "已报名":
        return {"status": "already", "course": item["course_name"], "kind": item["kind"]}
    await db.execute(
        "INSERT INTO makeup_registrations (student_id, course_code, course_name, kind)"
        " VALUES (?,?,?,?)",
        (student_id, course_code, item["course_name"], item["kind"]))
    if item["status"] == "报名中":
        await db.execute(
            "UPDATE makeup_items SET status = '已报名'"
            " WHERE student_id = ? AND course_code = ? AND status = '报名中'",
            (student_id, course_code))
    return {"status": "registered", "course": item["course_name"], "kind": item["kind"]}


@dataclass
class PendingAction:
    action_id: str
    student_id: str
    action: str
    params: dict
    expires_at: float


@dataclass
class PendingActionStore:
    """内存待确认动作：TTL 默认 600s，pop 一次性（确认即焚），
    属主校验（student_id 不匹配返回 None）。重启即清空——确认卡随之失效，
    与 SessionStore 同为内存语义（spec2 §1 已确认可接受）。"""

    ttl_seconds: int = 600
    _items: dict = field(default_factory=dict)

    def create(self, student_id: str, action: str, params: dict) -> str:
        self._sweep()
        action_id = uuid.uuid4().hex
        self._items[action_id] = PendingAction(
            action_id, student_id, action, params,
            time.monotonic() + self.ttl_seconds)
        return action_id

    def pop(self, action_id: str, student_id: str) -> PendingAction | None:
        self._sweep()
        item = self._items.pop(action_id, None)  # 无论成败先 pop：一次性语义
        if item is None or item.student_id != student_id:
            return None
        return item

    def _sweep(self) -> None:
        now = time.monotonic()
        dead = [k for k, v in self._items.items() if v.expires_at < now]
        for k in dead:
            del self._items[k]
