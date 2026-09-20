from langgraph.types import StreamWriter

from ...llm.base import LLMProvider


async def generator_node(state, provider: LLMProvider, writer: StreamWriter):
    answer_parts: list[str] = []
    async for chunk in provider.stream_answer(state["user_input"], state):
        answer_parts.append(chunk)
        writer(("token", {"text": chunk}))

    nav_card = None
    tool_result = state.get("tool_results", {}).get("resolve_page", {})
    if tool_result.get("ok") and isinstance(tool_result.get("data"), dict):
        page = tool_result["data"]
        nav_card = {"path": page["path"], "title": page["title"],
                    "reason": f"与「{state['intent']}」最匹配的页面"}
        writer(("nav_card", nav_card))

    return {"answer": "".join(answer_parts), "nav_card": nav_card, "steps": ["generator"]}
