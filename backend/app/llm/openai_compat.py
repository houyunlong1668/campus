import json
from typing import AsyncIterator

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from ..agent.plan import OrchestrationPlan, PlanBundle, WriteIntent
from ..agent.state import AgentState
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

PLAN_SYSTEM = (
    "你是编排规划器。判断这句用户输入是否需要：a) 条件分支（先查数，满足条件再追加一个取数问题）；"
    "b) 写操作确认（补考/重修报名）。只输出 JSON："
    '{"orchestration": {"condition": {"mode": "threshold", "column": "score", "op": "lt", "value": 60}'
    ' | {"mode": "llm", "condition_text": "..."}, "followup_user_input": "..."} | null, '
    '"write": {"course_code": "...", "course_name": "...", "summary": "..."} | null}。'
    "没有把握就全 null。阈值条件只用于分数类列。"
)

JUDGE_SYSTEM = "你是条件判定器。只回答 true 或 false，不要任何其他字符。"


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
            # tool_calls 是 Function|Custom 联合（按 type 判别）：Custom 型没有
            # .function，必须先收窄再取 name（类型检查与真实 API 两层保险）
            actionable = [c for c in msg.tool_calls
                          if c.type == "function"
                          and c.function.name not in _EXPLORE_TOOLS]
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

    async def plan(self, user_input: str, route: str) -> PlanBundle:
        if route not in ("query", "answer"):
            return PlanBundle()
        if not any(h in user_input for h in ("不及格", "低于", "如果", "报名", "重修", "补考")):
            return PlanBundle()   # 触发词闸：无关消息零额外调用
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": PLAN_SYSTEM},
                      {"role": "user", "content": user_input}],
            response_format={"type": "json_object"},
        )
        try:
            data = json.loads(resp.choices[0].message.content or "{}")
            return PlanBundle(
                orchestration=OrchestrationPlan(**data["orchestration"])
                if data.get("orchestration") else None,
                write=WriteIntent(**data["write"]) if data.get("write") else None)
        except (json.JSONDecodeError, KeyError, ValueError):
            return PlanBundle()   # 计划坏了就当没有：降级为单轮，不阻断对话

    async def judge(self, condition_text: str, evidence: dict) -> bool:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": JUDGE_SYSTEM},
                      {"role": "user", "content": f"条件：{condition_text}\n"
                        f"数据：{json.dumps(evidence, ensure_ascii=False)}"}],
        )
        return (resp.choices[0].message.content or "").strip().lower().startswith("true")

    async def stream_answer(self, user_input: str, state: AgentState) -> AsyncIterator[str]:
        tool_note = ""
        for name, result in (state.get("tool_results") or {}).items():
            tool_note += f"\n工具 {name} 返回: {json.dumps(result.get('data'), ensure_ascii=False)}"
        # 查数结果在 state["sql_history"]（编排两轮时第一轮分数不能丢）、
        # 兜底 state["sql"]，都不在 tool_results——不给模型看行数据，
        # 它按 ANSWER_SYSTEM「不要编造」就没法回答澄清第二轮（历史里只有
        # 问句没有分数），只能拒绝作答或瞎编。
        sql = state.get("sql")
        history = state.get("sql_history") or ([sql] if sql else [])
        for i, s in enumerate(history):
            if s.get("columns"):
                tool_note += (f"\n查询结果#{i + 1}"
                              + json.dumps({"columns": s.get("columns"),
                                            "rows": s.get("rows") or [],
                                            "row_count": s.get("row_count")},
                                           ensure_ascii=False))
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": ANSWER_SYSTEM}]
        for h in (state.get("history") or []):
            role, content = h.get("role"), h.get("content")
            # 分支收窄到精确字面量 role，字典才能匹配 ChatCompletionMessageParam 联合
            if content and role in ("user", "assistant"):
                if role == "user":
                    messages.append({"role": "user", "content": content})
                else:
                    messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user",
                         "content": f"用户问: {user_input}{tool_note}"})
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
