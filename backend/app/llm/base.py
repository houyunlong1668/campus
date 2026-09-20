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
    def stream_answer(self, user_input: str, state: "AgentState") -> AsyncIterator[str]: ...
