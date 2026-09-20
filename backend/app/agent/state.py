import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict):
    user_input: str
    session_id: str
    intent: str | None
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_results: dict[str, Any]
    answer: str
    nav_card: dict[str, Any] | None
    steps: Annotated[list[str], operator.add]
    error: str | None
