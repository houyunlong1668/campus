from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.deps import require_student
from ..auth.students import Student

router = APIRouter()


@router.post("/replay")
async def replay(req: Request, student: Student = Depends(require_student)):
    """回放展示（裁决 2：不重执行节点——写操作双写与 /confirm 一次性语义冲突）。
    返回最近一次执行的节点序列、每步参数/耗时，与 tool_calls.steps_json 同源。"""
    trace = await req.app.state.repository.latest_trace(student_id=student.student_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="还没有可回放的执行记录")
    return trace
