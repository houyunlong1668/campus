from typing import Any, AsyncIterator, Protocol

from pydantic import BaseModel

from ..tools.base import ToolSpec


class RouteDecision(BaseModel):
    intent: str
    tool_name: str | None
    tool_args: dict[str, Any]
    confidence: float


class LLMProvider(Protocol):
    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision: ...
    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        """Text-to-SQL：拿语义 schema 把自然语言翻成只读 SQL。
        生成的 SQL 必须只引用白名单视图、不得含身份列——guard 会兜底拒绝。"""
        ...
    def stream_answer(self, user_input: str, state: "AgentState") -> AsyncIterator[str]: ...
