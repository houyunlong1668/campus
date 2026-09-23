import operator
from typing import Annotated, Any, Literal, TypedDict


class AgentState(TypedDict):
    user_input: str
    student_id: str                 # 只从会话来（原 session_id 装的就是学号，改名归位）
    history: list[dict[str, str]]   # 服务端回读，前端只发当前这句
    intent: str | None              # 用户原话片段，generator 拿它拼 nav_card 文案
    route: Literal["navigate", "query", "answer"] | None   # spec 7.3 三态
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_results: dict[str, Any]
    answer: str
    nav_card: dict[str, Any] | None
    needs_clarification: bool
    clarification: dict[str, Any] | None
    sql: dict[str, Any] | None      # {raw, scoped, columns, rows, row_count, refused_code}
    steps: Annotated[list[str], operator.add]
    error: str | None
