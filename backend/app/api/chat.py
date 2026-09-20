import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError

from ..agent.graph import build_graph
from ..llm.fake import FakeProvider
from ..schemas import ChatRequest

logger = logging.getLogger("campus-agent.chat")
router = APIRouter()


def sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest, req: Request):
    registry = req.app.state.registry
    provider = FakeProvider()  # M6 换成 config 选择器
    graph = build_graph(provider, registry)
    request_id = uuid.uuid4().hex[:12]
    message_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    initial_state = {
        "user_input": request.message,
        "session_id": request.session_id,
        "intent": None, "tool_name": None, "tool_args": {},
        "tool_results": {}, "answer": "", "nav_card": None,
        "steps": [], "error": None,
    }

    async def stream():
        first_token_at: float | None = None
        final_state: dict | None = None
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
            yield sse_frame("done", {
                "message_id": message_id,
                "steps": (final_state or {}).get("steps", []),
                "session_id": request.session_id,
            })
        except GraphRecursionError:
            logger.error("request_id=%s 触发 recursion_limit", request_id)
            yield sse_frame("error", {"code": "recursion_limit", "message": "执行步数超限，请重试"})
        except Exception as exc:  # 兜底：任何异常都以 error 事件收尾，不裸断流
            logger.exception("request_id=%s 链路异常", request_id)
            yield sse_frame("error", {"code": "internal", "message": str(exc)})
        logger.info("request_id=%s 总耗时=%.0fms", request_id, (time.perf_counter() - start) * 1000)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
