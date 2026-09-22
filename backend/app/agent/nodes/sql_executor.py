import json
import logging

from langgraph.types import StreamWriter

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.sql_executor")


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
        tool_results["resolve_page"] = nav.model_dump()
        writer(("tool_call", {"name": "resolve_page", "args": state["tool_args"],
                              "ok": nav.ok, "error": nav.error,
                              "latency_ms": nav.latency_ms}))

    schema_res = await registry.call_tool("describe_schema", {})
    schema = schema_res.data if schema_res.ok else []

    raw_sql = await provider.generate_sql(state["user_input"], json.dumps(schema, ensure_ascii=False))
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
