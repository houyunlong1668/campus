import logging
import operator
import time

from langgraph.types import StreamWriter

from ...llm.base import LLMProvider

logger = logging.getLogger("campus-agent.grader")

_OPS = {"lt": operator.lt, "le": operator.le, "gt": operator.gt,
        "ge": operator.ge, "eq": operator.eq, "ne": operator.ne}


async def grader_node(state, provider: LLMProvider, writer: StreamWriter):
    """spec §4 条件分支：阈值/LLM 双模式；工具失败走 degraded，已成功结果不丢
    （它们在 sql_history / tool_results 里，generator 照常读）。"""
    start = time.perf_counter()
    plan = state["orchestration"]
    latest = state.get("sql") or {}

    branch, detail = "else", {"mode": plan.condition.mode}
    if state.get("error"):
        branch = "degraded"
        detail["reason"] = state["error"]
    elif plan.condition.mode == "threshold":
        cond = plan.condition
        columns = latest.get("columns") or []
        if cond.column in columns:
            idx = columns.index(cond.column)
            vals = [r[idx] for r in latest.get("rows") or []
                    if idx < len(r) and isinstance(r[idx], (int, float))]
            hit = bool(vals) and any(_OPS[cond.op](v, cond.value) for v in vals)
        else:
            hit = False   # 列不在结果里：判不出 → 走 else，不瞎猜 then
            vals = []
        branch = "then" if hit else "else"
        detail.update({"column": cond.column,
                       "hit_rows": len(vals) if cond.column in columns else 0})
    else:  # llm
        hit = await provider.judge(plan.condition.condition_text,
                                   {"columns": latest.get("columns"),
                                    "rows": latest.get("rows")})
        branch = "then" if hit else "else"

    writer(("grader", {"branch": branch}))
    logger.info("grader branch=%s detail=%s", branch, detail)

    out = {"branch": branch, "steps": ["grader"],
           "step_details": [{"node": "grader",
                             "latency_ms": int((time.perf_counter() - start) * 1000),
                             "detail": detail}]}
    # 循环守卫：phase 标记保证 grader 全图只放行一次 followup，
    # 结构上不存在第二次回到 grader 的边（验收 5「死循环被截断」的图级防线；
    # recursion_limit=10 只是兜底，正常路径根本到不了）
    if branch == "then" and plan.followup_user_input \
            and not state.get("orchestration_phase"):
        out["orchestration_phase"] = "followup"
        out["next_query"] = plan.followup_user_input
    return out
