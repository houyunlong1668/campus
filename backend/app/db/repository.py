import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ToolCallRecord(BaseModel):
    tool_name: str
    args_json: str
    ok: bool
    error: str | None
    latency_ms: int


class ConversationRepository(Protocol):
    async def record_exchange(self, *, student_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str]) -> int | None: ...


class SqliteConversationRepository:
    def __init__(self, path: Path):
        self._path = path

    async def record_exchange(self, *, student_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str]) -> int | None:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            # session_id 列暂与 student_id 同值写入：老库里它是 NOT NULL 且
            # SQLite 无法就地放宽约束，S2 的 MySQL schema 不再保留这一列。
            cur = await db.execute(
                "INSERT INTO conversations(student_id, session_id) VALUES (?,?)",
                (student_id, student_id))
            conv_id = cur.lastrowid
            await db.executemany(
                "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
                [(conv_id, "user", user_text), (conv_id, "assistant", assistant_text)],
            )
            if tool_call is not None:
                await db.execute(
                    """INSERT INTO tool_calls
                       (conversation_id, tool_name, args_json, ok, error, latency_ms, steps_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (conv_id, tool_call.tool_name, tool_call.args_json,
                     int(tool_call.ok), tool_call.error, tool_call.latency_ms,
                     json.dumps(steps, ensure_ascii=False)),
                )
            await db.commit()
            return conv_id


def build_repository(path: Path) -> ConversationRepository:
    return SqliteConversationRepository(path)
