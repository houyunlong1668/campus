from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth.deps import require_student
from ..auth.students import Student
from ..write_ops import WriteOpError, PendingActionStore, register_makeup

router = APIRouter()


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=64)


@router.post("/confirm")
async def confirm(request: ConfirmRequest, req: Request,
                  student: Student = Depends(require_student)):
    store: PendingActionStore = req.app.state.pending_actions
    action = store.pop(request.action_id, student.student_id)
    if action is None:
        # 不区分「不存在」「过期」「别人的」：三种都不该告诉请求者细节
        raise HTTPException(status_code=404, detail="确认请求不存在或已过期")
    if action.action == "makeup_register":
        try:
            result = await register_makeup(req.app.state.db, student.student_id,
                                           action.params["course_code"])
        except WriteOpError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "result": result}
    raise HTTPException(status_code=400, detail=f"未知动作: {action.action}")
