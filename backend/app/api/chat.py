import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError

from ..agent.graph import build_graph
from ..auth.deps import require_student
from ..auth.students import Student
from ..db.repository import ToolCallRecord
from ..schemas import ChatRequest

logger = logging.getLogger("campus-agent.chat")
router = APIRouter()


def sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_record(state: dict[str, Any]) -> ToolCallRecord | None:
    """tool_results 的值里没有工具名，tool_name 只能取 state 上那个。"""
    first = next(iter(state.get("tool_results", {}).values()), None)
    tool_name = state.get("tool_name")
    if not first or not tool_name:
        return None
    return ToolCallRecord(
        tool_name=tool_name,
        args_json=json.dumps(state.get("tool_args", {}), ensure_ascii=False),
        ok=bool(first.get("ok")),
        error=first.get("error"),
        latency_ms=int(first.get("latency_ms") or 0),
    )


@router.post("/chat")
async def chat(request: ChatRequest, req: Request,
               student: Student = Depends(require_student)):
    registry = req.app.state.registry
    provider = req.app.state.provider
    repository = req.app.state.repository
    graph = build_graph(provider, registry)
    request_id = uuid.uuid4().hex[:12]
    message_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    # 裁决 B 落地点：history 变量必须在 initial_state 使用之前定义（顺序不能反）。
    # 在落库之前读——本轮消息还没进库，读到的天然只有上一轮及更早。
    settings = req.app.state.settings
    history = await repository.recent_history(
        student_id=student.student_id, limit=settings.history_limit)

    initial_state = {
        "user_input": request.message,
        # 图内的"会话"即学号：节点不需要知道身份从哪来
        "student_id": student.student_id,
        "history": history,
        "intent": None, "route": None, "tool_name": None, "tool_args": {},
        "tool_results": {}, "answer": "", "nav_card": None,
        "needs_clarification": False, "clarification": None, "sql": None,
        "steps": [], "error": None,
    }

    async def stream():
        first_token_at: float | None = None
        final_state: dict | None = None
        persisted = False
        conversation_id: int | None = None

        async def persist():
            # 异常轮次同样要落库——失败样本才是行为测试最需要看的
            nonlocal persisted, conversation_id
            if persisted:
                return
            persisted = True
            state = final_state or {}
            try:
                conversation_id = await repository.record_exchange(
                    student_id=student.student_id,
                    user_text=request.message,
                    assistant_text=state.get("answer", ""),
                    tool_call=build_record(state),
                    steps=state.get("steps", []),
                )
            except Exception:
                logger.exception("request_id=%s 落库失败（不中断对话流）", request_id)

        try:
            async for mode, payload in graph.astream(
                initial_state, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    event, data = payload
                    if event == "token" and first_token_at is None:
                        first_token_at = time.perf_counter()
                        logger.info("request_id=%s 首token延迟=%.0fms",
                                    request_id, (first_token_at - start) * 1000)
                    yield sse_frame(event, data)
                else:
                    final_state = payload  # values 模式最后一条即合并后的最终 state
            await persist()
            yield sse_frame("done", {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "steps": (final_state or {}).get("steps", []),
            })
        except GraphRecursionError:
            logger.error("request_id=%s 触发 recursion_limit", request_id)
            await persist()
            yield sse_frame("error", {"code": "recursion_limit", "message": "执行步数超限，请重试"})
        except Exception:  # 兜底：任何异常都以 error 事件收尾，不裸断流
            logger.exception("request_id=%s 链路异常", request_id)
            await persist()
            # 异常原文只进日志，不外发：客户端拿到的是 request_id，可据此回查
            yield sse_frame("error", {"code": "internal",
                                      "message": f"服务处理异常，请重试（request_id={request_id}）"})
        logger.info("request_id=%s 总耗时=%.0fms", request_id, (time.perf_counter() - start) * 1000)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
