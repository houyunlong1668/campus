import operator
from typing import Annotated, Any, Literal, TypedDict

from .plan import OrchestrationPlan, WriteIntent


def _merge_results(a: dict | None, b: dict | None) -> dict:
    """tool_results 跨节点累加：同 key 后者覆盖（同工具重跑），异 key 并集。"""
    return {**(a or {}), **(b or {})}


class AgentState(TypedDict):
    user_input: str
    student_id: str                 # 只从会话来（原 session_id 装的就是学号，改名归位）
    history: list[dict[str, str]]   # 服务端回读，前端只发当前这句
    intent: str | None              # 用户原话片段，generator 拿它拼 nav_card 文案
    route: Literal["navigate", "query", "answer", "write"] | None  # spec 7.3 三态 + Task 6 write
    orchestration: OrchestrationPlan | None     # grader 的判定计划（Task 5 消费）
    write: WriteIntent | None                   # 待确认的写意图（Task 6 消费）
    orchestration_phase: Literal["followup"] | None  # grader 已放行 followup 的标记
    branch: str | None                          # grader 结果：then/else/degraded
    next_query: str | None                      # followup 问句，sql_executor 优先于 user_input
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_results: Annotated[dict[str, Any], _merge_results]
    answer: str
    nav_card: dict[str, Any] | None
    needs_clarification: bool
    clarification: dict[str, Any] | None
    sql: dict[str, Any] | None      # {raw, scoped, columns, rows, row_count, refused_code}
    sql_history: Annotated[list[dict], operator.add]   # 每一轮查数的 sql_state 快照
    confirm_card: dict[str, Any] | None                # 待用户点击的确认卡
    step_details: Annotated[list[dict], operator.add]  # 每步 {node, latency_ms, detail}
    steps: Annotated[list[str], operator.add]
    error: str | None
