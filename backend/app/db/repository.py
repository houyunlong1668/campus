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


class ConversationRepository(Protocol):
    async def record_exchange(self, *, student_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str]) -> int | None: ...


class DbConversationRepository:
    def __init__(self, db: Database):
        self._db = db

    async def record_exchange(self, *, student_id: str, user_text: str,
                              assistant_text: str,
                              tool_call: ToolCallRecord | None,
                              steps: list[str]) -> int | None:
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
                   (conversation_id, tool_name, args_json, ok, error, latency_ms, steps_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (conv_id, tool_call.tool_name, tool_call.args_json,
                 int(tool_call.ok), tool_call.error, tool_call.latency_ms,
                 json.dumps(steps, ensure_ascii=False)),
            )
        return conv_id


def build_repository(db: Database) -> ConversationRepository:
    return DbConversationRepository(db)
