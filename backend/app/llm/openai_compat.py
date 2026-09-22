import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ..tools.base import ToolSpec
from .base import RouteDecision

ROUTER_SYSTEM = (
    "你是校园助手的路由器。用户输入一句话，判断是否需要调用工具。"
    "需要时用工具调用表达，不要直接回答。可用工具只有系统提供的那些。"
    "要定位页面时直接调 resolve_page（把用户原话填进 intent），不要调 list_pages——"
    "页面清单已包含在工具说明里，探路调用会被丢弃。"
)

# 探路型工具：模型爱先调它们"看看有什么"，但本链路每轮只执行一个工具，
# 取第一个调用时必须跳过这类，否则真正的 resolve_page 会被丢掉（跳转卡片不出现）
_EXPLORE_TOOLS = frozenset({"list_pages"})

ANSWER_SYSTEM = (
    "你是校园助手。基于工具返回结果用中文简短回答；若工具有 nav 信息，"
    "引导用户点击跳转卡片。不要编造工具里没有的数据。"
)

SQL_SYSTEM = (
    "你是 SQL 生成器。只许 SELECT，只许引用 v_grades/v_schedule/v_makeup/v_loans "
    "四个视图，绝不出现 student_id 列，绝不写多条语句。"
    "输出只含 SQL 文本本身，不要解释、不要 markdown 代码块。"
)


class OpenAICompatProvider:
    """一份代码服务通义千问 compatible-mode 与 DeepSeek，差异全在三个环境变量。"""

    def __init__(self, base_url: str, model: str, api_key: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
        self.model = model

    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": user_input},
            ],
            tools=[
                {"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.input_schema}}
                for t in tools
            ],
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            actionable = [c for c in msg.tool_calls
                          if c.function.name not in _EXPLORE_TOOLS]
            call = actionable[0] if actionable else None
            if call is not None:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                return RouteDecision(intent=user_input[:20], tool_name=call.function.name,
                                     tool_args=args, confidence=1.0)
        return RouteDecision(intent=user_input[:20], tool_name=None,
                             tool_args={}, confidence=0.5)

    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": SQL_SYSTEM},
                      {"role": "user", "content": f"语义视图结构：{schema_json}\n\n用户问题：{user_input}"}],
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("sql"):
                text = text[3:]
        return text.strip()

    async def stream_answer(self, user_input: str, state: dict[str, Any]) -> AsyncIterator[str]:
        tool_note = ""
        for name, result in (state.get("tool_results") or {}).items():
            tool_note += f"\n工具 {name} 返回: {json.dumps(result.get('data'), ensure_ascii=False)}"
        messages = [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"用户问: {user_input}{tool_note}"},
        ]
        if state.get("error"):
            messages.append({"role": "user",
                             "content": f"工具调用失败({state['error']})，请给出降级说明。"})
        stream = await self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
