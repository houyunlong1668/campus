from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth.deps import require_student
from ..auth.students import Student

router = APIRouter(prefix="/api")

_WEEKDAYS = "一二三四五六日"


def _as_dt(raw: Any) -> datetime:
    """MySQL 驱动给 datetime 对象，SQLite 给字符串——两侧都要能格式化。"""
    if isinstance(raw, datetime):
        return raw
    return datetime.strptime(str(raw)[:16], "%Y-%m-%d %H:%M")


def _stamp(raw: Any) -> str:
    """教务系统式日期串：2026-09-28 周一 09:00"""
    d = _as_dt(raw)
    return f"{d:%Y-%m-%d} 周{_WEEKDAYS[d.weekday()]} {d:%H:%M}"


def _md(raw: Any) -> str:
    return _as_dt(raw).strftime("%m-%d")


def _days_left(raw: Any) -> int:
    """今天 0 点起算的剩余天数，负数为已逾期（不落冗余列，查询时算）。

    astimezone() 给 0 点挂上进程真实时区：进程 tz 与会话 tz 不一致时
    （Docker/WSL/UTC CI）裸的 datetime.now() 会整体飘一天。库里存的是
    本地挂钟 naive 时间，按同一 tzinfo 解释后相减。
    """
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    due = _as_dt(raw)
    if due.tzinfo is None:
        due = due.replace(tzinfo=today.tzinfo)
    return (due - today).days


@router.get("/grades")
async def grades(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT course_name, course_code, credits, score, term FROM enrollments"
        # 只按 ASCII 列排：course_name 是中文，SQLite 比 UTF-8 字节而 MySQL 比
        # utf8mb4_0900_ai_ci，同分并列时两边顺序可能不同，双后端"逐字段一致"
        # 就会变成巧合。course_code 在同一学期内唯一，排序是全序。
        # （term 值形如 '2025 秋'，前四位数字已决定先后，中文后缀不参与比较。）
        " WHERE student_id = ? ORDER BY term, course_code",
        (student.student_id,))
    return {"grades": [{"name": r["course_name"], "code": r["course_code"],
                        "credits": r["credits"], "score": r["score"],
                        "term": r["term"]} for r in rows]}


@router.get("/schedule")
async def schedule(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT s.course_name, s.course_code, s.teacher, s.room, s.weekday,"
        " s.start_period, s.end_period, s.weeks_from, s.weeks_to,"
        " c.credits, c.kind, c.domain"
        " FROM course_sections s JOIN courses c ON c.course_code = s.course_code"
        " WHERE s.student_id = ? ORDER BY s.weekday, s.start_period",
        (student.student_id,))
    return {"courses": [
        {"name": r["course_name"], "code": r["course_code"], "teacher": r["teacher"],
         "room": r["room"], "day": r["weekday"],
         "periods": list(range(r["start_period"], r["end_period"] + 1)),
         "credits": r["credits"], "weeks": f"{r['weeks_from']}-{r['weeks_to']}",
         "kind": r["kind"], "domain": r["domain"]} for r in rows]}


@router.get("/makeup")
async def makeup(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT course_name, course_code, kind, reason, scheduled_at, place, status,"
        " seats_left, seats_total FROM makeup_items WHERE student_id = ?"
        " ORDER BY scheduled_at", (student.student_id,))
    items = []
    for r in rows:
        items.append({
            "course": r["course_name"], "code": r["course_code"], "type": r["kind"],
            "reason": r["reason"],
            "when": (f"报名截止 {_md(r['scheduled_at'])} 17:00"
                     if r["status"] == "报名中" else _stamp(r["scheduled_at"])),
            "place": r["place"], "status": r["status"],
            "seats": (f"剩 {r['seats_left']} / {r['seats_total']}"
                      if r["seats_left"] is not None else None),
        })
    return {"items": items}


@router.get("/loans")
async def loans(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT title, call_no, due_at, shelf FROM library_loans"
        " WHERE student_id = ? AND returned_at IS NULL ORDER BY due_at",
        (student.student_id,))
    return {"items": [
        {"title": r["title"], "callNo": r["call_no"], "due": _stamp(r["due_at"]),
         "daysLeft": _days_left(r["due_at"]), "place": r["shelf"]} for r in rows]}
