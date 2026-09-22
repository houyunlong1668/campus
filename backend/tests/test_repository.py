from app.db.migrations import init_sqlite
from app.db.repository import ToolCallRecord, build_repository


async def test_record_exchange_写入三表(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)

    conv_id = await repo.record_exchange(
        student_id="20230001", user_text="查成绩", assistant_text="已找到成绩查询页",
        tool_call=ToolCallRecord(tool_name="resolve_page", args_json='{"intent":"查成绩"}',
                                 ok=True, error=None, latency_ms=12),
        steps=["router", "tool_executor", "generator"],
    )

    convs = await db.fetch_all("SELECT id, student_id FROM conversations")
    msgs = await db.fetch_all("SELECT role, content FROM messages ORDER BY id")
    calls = await db.fetch_all(
        "SELECT conversation_id, tool_name, ok, latency_ms, steps_json FROM tool_calls")

    # conversations 只有 student_id 一列由仓储写入（S2 起不再有 session_id）
    assert [(c["id"], c["student_id"]) for c in convs] == [(conv_id, "20230001")]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "查成绩"), ("assistant", "已找到成绩查询页")]
    assert calls[0]["conversation_id"] == conv_id
    assert calls[0]["tool_name"] == "resolve_page"
    assert calls[0]["ok"] == 1
    assert calls[0]["steps_json"] == '["router", "tool_executor", "generator"]'


async def test_无工具轮次不落_tool_calls(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")

    await build_repository(db).record_exchange(
        student_id="20230002", user_text="今天天气怎么样", assistant_text="我还不会回答这类问题。",
        tool_call=None, steps=["router", "generator"],
    )

    n = await db.fetch_all("SELECT COUNT(*) AS n FROM tool_calls")
    msgs = await db.fetch_all("SELECT role FROM messages ORDER BY id")

    assert n[0]["n"] == 0
    assert [m["role"] for m in msgs] == ["user", "assistant"]
