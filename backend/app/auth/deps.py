from fastapi import HTTPException, Request

from .session import COOKIE_NAME
from .students import Student


async def require_student(request: Request) -> Student:
    """身份唯一来源：Cookie 里的会话。查不到就 401，不看任何请求体字段。"""
    sid = request.cookies.get(COOKIE_NAME)
    session = request.app.state.sessions.get(sid) if sid else None
    if session is None:
        raise HTTPException(status_code=401, detail={
            "code": "unauthenticated", "message": "请先登录"})

    student = await request.app.state.students.get(session.student_id)
    if student is None:
        # 会话有效但账号已不在库里：同样按未登录处理，不给半截身份
        raise HTTPException(status_code=401, detail={
            "code": "unauthenticated", "message": "请先登录"})
    return student
