from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth.deps import require_student
from ..auth.passwords import verify_password
from ..auth.session import COOKIE_NAME
from ..auth.students import Student
from ..schemas import LoginRequest

router = APIRouter(prefix="/auth")


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    students = request.app.state.students
    guard = request.app.state.login_guard

    wait = guard.check(body.student_id)
    if wait is not None:
        raise HTTPException(status_code=429, detail={
            "code": "too_many_attempts",
            "message": f"尝试次数过多，请 {int(wait) + 1} 秒后再试",
        })

    # 账号不存在与密码错误走同一分支、同一句文案，不给出可枚举信号
    stored_hash = await students.get_password_hash(body.student_id)
    if stored_hash is None or not verify_password(body.password, stored_hash):
        guard.record_failure(body.student_id)
        raise HTTPException(status_code=401, detail={
            "code": "bad_credentials", "message": "学号或密码不正确"})

    guard.reset(body.student_id)
    session = request.app.state.sessions.create(body.student_id)
    settings = request.app.state.settings
    response.set_cookie(
        key=COOKIE_NAME, value=session.sid, max_age=settings.session_ttl_seconds,
        httponly=True, samesite="lax", secure=settings.cookie_secure, path="/",
    )
    student = await students.get(body.student_id)
    return student.model_dump()


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        request.app.state.sessions.revoke(sid)
    # 改注入的 response 而不是 return 一个新 Response：
    # 后者会让 delete_cookie 写进的那个 Set-Cookie 被丢掉，客户端 Cookie 清不掉
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.get("/me")
async def me(student: Student = Depends(require_student)):
    return student.model_dump()
