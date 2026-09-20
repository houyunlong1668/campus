import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ..tools.base import ToolSpec
from .base import RouteDecision

ROUTER_SYSTEM = (
    "你是校园助手的路由器。用户输入一句话，判断是否需要调用工具。"
    "需要时用工具调用表达，不要直接回答。可用工具只有系统提供的那些。"
)

ANSWER_SYSTEM = (
    "你是校园助手。基于工具返回结果用中文简短回答；若工具有 nav 信息，"
    "引导用户点击跳转卡片。不要编造工具里没有的数据。"
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
            call = msg.tool_calls[0]
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            return RouteDecision(intent=user_input[:20], tool_name=call.function.name,
                                 tool_args=args, confidence=1.0)
        return RouteDecision(intent=user_input[:20], tool_name=None,
                             tool_args={}, confidence=0.5)

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
