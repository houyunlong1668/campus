import json
import logging
import re

from langgraph.types import StreamWriter

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.sql_executor")

_BARE_TERM_RE = re.compile(r"^\s*20\d{2}\s*(?:春|秋|夏|冬)\s*$")


def _sql_input(state) -> str:
    """裸学期词要拼回最近一条用户原话再交给 generate_sql。

    ClarifyBar 点选项只 send(label)（Task 9 实现、spec 7.2 约定），第二轮
    user_input 是纯「2025 秋」——不拼上下文，课程过滤就丢了：用户问的是
    数据结构，回来的是整学期全表。spec 7.3 的叙事「history 里上一句就是
    问句」落点在此，provider 签名不动（fake 与真模型两侧同时受益）。
    """
    user_input = state["user_input"]
    if not _BARE_TERM_RE.match(user_input):
        return user_input
    last_user = next(
        (m.get("content", "") for m in reversed(state.get("history") or [])
         if m.get("role") == "user"), "")
    return f"{last_user} {user_input}".strip() if last_user else user_input


async def _emit(writer: StreamWriter, result) -> None:
    writer(("tool_call", {"name": result.get("_name", "run_sql"),
                          "args": {}, "ok": True, "error": None,
                          "latency_ms": 0}))


async def sql_executor_node(state, registry: ToolRegistry,
                            provider: LLMProvider, writer: StreamWriter):
    """spec 7.3：describe_schema → 模型写 SQL → run_sql → 澄清判定。
    规则 3（query 与 navigate 并存）在这里先补跑 resolve_page，
    让 tool_results 就位，generator 的 nav_card 逻辑一行都不用改。
    """
    tool_results: dict = dict(state.get("tool_results") or {})

    if state.get("tool_name") == "resolve_page":
        nav = await registry.call_tool("resolve_page", state["tool_args"],
                                       student_id=state["student_id"])
        # stdio MCP 恒返 JSON 字符串、InMemory 给 dict——与 tool_executor 同款
        # 判别：str 才 loads；解析失败照它打成"工具返回非 JSON"，卡片自然不出。
        if nav.ok and isinstance(nav.data, str):
            try:
                nav = nav.model_copy(update={"data": json.loads(nav.data)})
            except json.JSONDecodeError:
                nav = nav.model_copy(update={"ok": False, "error": "工具返回非 JSON"})
        tool_results["resolve_page"] = nav.model_dump()
        writer(("tool_call", {"name": "resolve_page", "args": state["tool_args"],
                              "ok": nav.ok, "error": nav.error,
                              "latency_ms": nav.latency_ms}))

    schema_res = await registry.call_tool("describe_schema", {})
    # 同一套判别：MCP 给 str 就 loads 成 list/dict（否则下面 json.dumps 是
    # 双重编码，真模型拿到一段 JSON 字符串而非结构）；失败照 tool_executor
    # 打成工具失败，走本行既有的 [] 降级。
    if schema_res.ok and isinstance(schema_res.data, str):
        try:
            schema_res = schema_res.model_copy(update={"data": json.loads(schema_res.data)})
        except json.JSONDecodeError:
            schema_res = schema_res.model_copy(update={"ok": False, "error": "工具返回非 JSON"})
    schema = schema_res.data if schema_res.ok else []

    raw_sql = await provider.generate_sql(_sql_input(state),
                                          json.dumps(schema, ensure_ascii=False))
    result = await registry.call_tool("run_sql", {"sql": raw_sql},
                                      student_id=state["student_id"])
    payload = result.data if isinstance(result.data, dict) else {}
    if isinstance(result.data, str):
        payload = json.loads(result.data)

    writer(("tool_call", {"name": "run_sql", "args": {"sql": raw_sql},
                          "ok": bool(payload.get("ok")),
                          "error": payload.get("refused_message"),
                          "latency_ms": result.latency_ms}))

    scoped = payload.get("scoped_sql", "")
    sql_state = {"raw": raw_sql, "scoped": scoped,
                 "columns": payload.get("columns", []),
                 "rows": payload.get("rows", []),
                 "row_count": payload.get("row_count", 0),
                 "refused_code": payload.get("refused_code")}

    error = None
    if not payload.get("ok"):
        error = payload.get("refused_message") or payload.get("refused_code") or "查询未执行"
    else:
        writer(("sql_result", {"sql": scoped,
                               "columns": sql_state["columns"],
                               "rows": sql_state["rows"],
                               "row_count": sql_state["row_count"],
                               "truncated": False}))
        clarify = _maybe_clarify(payload, state["user_input"])
        if clarify:
            return {"tool_results": tool_results, "sql": sql_state,
                    "needs_clarification": True, "clarification": clarify,
                    "error": None, "steps": ["sql_executor"]}

    return {"tool_results": tool_results, "sql": sql_state,
            "needs_clarification": False, "clarification": None,
            "error": error, "steps": ["sql_executor"]}


def _maybe_clarify(payload: dict, user_input: str) -> dict | None:
    """结果跨多个学期且用户没指定 → 要求澄清（spec 7.3）。"""
    columns = payload.get("columns") or []
    if "term" not in columns:
        return None
    idx = columns.index("term")
    terms = sorted({row[idx] for row in (payload.get("rows") or []) if row[idx]})
    if len(terms) <= 1:
        return None
    if any(t in user_input for t in terms):   # 用户已指定，无需再问
        return None
    return {"question": "你要查哪个学期？",
            "options": [{"label": t} for t in terms]}
