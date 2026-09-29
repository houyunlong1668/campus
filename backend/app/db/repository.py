import json
from typing import Protocol

from pydantic import BaseModel

from .base import Database


class ToolCallRecord(BaseModel):
    tool_name: str
    args_json: str
    ok: bool
    error: str | None
    latency_ms: int


class SqlQueryRecord(BaseModel):
    sql_raw: str
    sql_scoped: str = ""
    refused_code: str | None = None
    row_count: int = 0
    latency_ms: int = 0


class ConversationRepository(Protocol):
    async def record_exchange(self, *, student_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str],
                              sql: SqlQueryRecord | None = None,
                              step_details: list[dict] | None = None) -> int | None: ...

    async def recent_history(self, *, student_id: str,
                             limit: int) -> list[dict[str, str]]: ...

    async def latest_trace(self, *, student_id: str) -> dict | None: ...


class DbConversationRepository:
    def __init__(self, db: Database):
        self._db = db

    async def record_exchange(self, *, student_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str],
                              sql: SqlQueryRecord | None = None,
                              step_details: list[dict] | None = None) -> int | None:
        conv_id = await self._db.execute(
            "INSERT INTO conversations(student_id) VALUES (?)", (student_id,))
        await self._db.execute(
            "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
            (conv_id, "user", user_text),
        )
        await self._db.execute(
            "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
            (conv_id, "assistant", assistant_text),
        )
        if tool_call is not None:
            await self._db.execute(
                """INSERT INTO tool_calls
                   (conversation_id, tool_name, args_json, ok, error, latency_ms, steps_json, step_details_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (conv_id, tool_call.tool_name, tool_call.args_json,
                 int(tool_call.ok), tool_call.error, tool_call.latency_ms,
                 json.dumps(steps, ensure_ascii=False),
                 json.dumps(step_details or [], ensure_ascii=False)),
            )
        if sql is not None:
            await self._db.execute(
                """INSERT INTO sql_queries
                   (conversation_id, student_id, sql_raw, sql_scoped,
                    refused_code, row_count, latency_ms)
                   VALUES (?,?,?,?,?,?,?)""",
                (conv_id, student_id, sql.sql_raw, sql.sql_scoped,
                 sql.refused_code, int(sql.row_count), int(sql.latency_ms)))
        return conv_id

    async def recent_history(self, *, student_id: str,
                             limit: int) -> list[dict[str, str]]:
        """读该学生最近 limit 条消息（跨会话），按时间升序，每条截 200 字。

        不看客户端传来的任何会话 id——历史回读的身份只来自会话（spec 5.1 要点）。
        record_exchange 每次 INSERT 新 conversation 行，一次对话=一个 conversation，
        所以按"最近一条会话"过滤只会剩上一轮 2 条，spec 12 的 6 轮上限用不上；
        必须跨会话取本人最近 limit 条。
        """
        rows = await self._db.fetch_all(
            "SELECT m.role, m.content FROM messages m"
            " JOIN conversations c ON c.id = m.conversation_id"
            " WHERE c.student_id = ?"
            " ORDER BY m.id DESC LIMIT ?", (student_id, limit))
        rows.reverse()   # 取的是最近 limit 条，要翻回时间升序给模型读
        return [{"role": r["role"], "content": str(r["content"])[:200]} for r in rows]

    async def latest_trace(self, *, student_id: str) -> dict | None:
        """该学生最近一次落库的执行轨迹（tool_calls 行），供 /replay 回放展示。

        身份只来自会话传入的 student_id——按本人过滤且只取最新一条（LIMIT 1），
        别人的记录永远查不到（会话隔离）。steps/step_details 与 /chat 的 done.steps
        同源（同一次 record_exchange 落的 steps_json/step_details_json）。
        """
        rows = await self._db.fetch_all(
            "SELECT t.tool_name, t.args_json, t.ok, t.latency_ms,"
            " t.steps_json, t.step_details_json, t.created_at"
            " FROM tool_calls t JOIN conversations c ON c.id = t.conversation_id"
            " WHERE c.student_id = ? ORDER BY t.id DESC LIMIT 1", (student_id,))
        if not rows:
            return None
        r = rows[0]
        return {"steps": json.loads(r["steps_json"]),
                "step_details": json.loads(r["step_details_json"] or "[]"),
                "tool_name": r["tool_name"],
                "args": json.loads(r["args_json"]),
                "ok": bool(r["ok"]),
                "latency_ms": int(r["latency_ms"]),
                "created_at": str(r["created_at"])}


def build_repository(db: Database) -> ConversationRepository:
    return DbConversationRepository(db)
