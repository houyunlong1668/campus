from langgraph.types import StreamWriter

from ...llm.base import LLMProvider


async def generator_node(state, provider: LLMProvider, writer: StreamWriter):
    # 先算 nav_card：流式前就要确定，并随 state 传给 provider，
    # 保证首条 token 话术与随后发出的 nav_card 语义一致
    nav_card = None
    tool_result = state.get("tool_results", {}).get("resolve_page", {})
    if tool_result.get("ok") and isinstance(tool_result.get("data"), dict):
        page = tool_result["data"]
        nav_card = {"path": page["path"], "title": page["title"],
                    "reason": f"与「{state['intent']}」最匹配的页面"}

    stream_state = {**state, "nav_card": nav_card}

    if state.get("needs_clarification") and state.get("clarification"):
        clarify = state["clarification"]
        writer(("clarify", clarify))
        # spec 7.3 规则 3：澄清轮若同时命中跳转（sql_executor 补跑了
        # resolve_page），卡片照出——"只出 clarify、不出 token"约束的是 token。
        if nav_card is not None:
            writer(("nav_card", nav_card))
        # 只出选项条，不出 token：同一句话既打字又给按钮是重复信号
        return {"answer": clarify["question"], "nav_card": nav_card,
                "steps": ["generator"]}

    answer_parts: list[str] = []
    async for chunk in provider.stream_answer(state["user_input"], stream_state):
        answer_parts.append(chunk)
        writer(("token", {"text": chunk}))

    if nav_card is not None:
        writer(("nav_card", nav_card))

    return {"answer": "".join(answer_parts), "nav_card": nav_card, "steps": ["generator"]}
