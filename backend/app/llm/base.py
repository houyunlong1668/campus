from typing import Any, AsyncIterator, Protocol

from pydantic import BaseModel

from ..agent.plan import PlanBundle
from ..agent.state import AgentState
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
    async def plan(self, user_input: str, route: str) -> PlanBundle:
        """编排二次判断：route 已定后，问「这句要不要条件分支/写确认」。
        默认实现返回空 PlanBundle（无编排）；命中触发词的 query/answer 才可能非空。"""
        ...
    async def judge(self, condition_text: str, evidence: dict) -> bool:
        """LLM 模式条件判断：evidence 含 columns/rows，只许回答布尔。"""
        ...
    def stream_answer(self, user_input: str, state: AgentState) -> AsyncIterator[str]: ...
