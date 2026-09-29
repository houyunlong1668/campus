import time

from langgraph.types import StreamWriter

from ...write_ops import PendingActionStore


async def confirm_preparer_node(state, store: PendingActionStore,
                                writer: StreamWriter):
    """写意图 → 待确认动作 + confirm_card 事件。本节点不执行任何写——
    执行只发生在 POST /confirm（spec §4「用户点确认才继续」）。"""
    start = time.perf_counter()
    intent = state["write"]
    action_id = store.create(state["student_id"], intent.action,
                             {"course_code": intent.course_code})
    card = {"action_id": action_id, "action": intent.action,
            "title": "确认报名",
            "summary": intent.summary
            or f"为「{intent.course_name or intent.course_code}」提交补考/重修报名"}
    writer(("confirm_card", card))
    return {"confirm_card": card, "steps": ["confirm_preparer"],
            "step_details": [{"node": "confirm_preparer",
                              "latency_ms": int((time.perf_counter() - start) * 1000),
                              "detail": {"action": intent.action,
                                         "course_code": intent.course_code}}]}
