from app.db.engine import init_db
from app.db.repository import ToolCallRecord, build_repository


async def test_record_exchange_写入三表(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    repo = build_repository(path)

    await repo.record_exchange(
        student_id="20230001", user_text="查成绩", assistant_text="已找到成绩查询页",
        tool_call=ToolCallRecord(tool_name="resolve_page", args_json='{"intent":"查成绩"}',
                                 ok=True, error=None, latency_ms=12),
        steps=["router", "tool_executor", "generator"],
    )

    import aiosqlite

    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        convs = await (await db.execute("SELECT student_id FROM conversations")).fetchall()
        msgs = await (await db.execute("SELECT role, content FROM messages ORDER BY id")).fetchall()
        calls = await (await db.execute(
            "SELECT tool_name, ok, latency_ms, steps_json FROM tool_calls")).fetchall()

    assert [c["student_id"] for c in convs] == ["20230001"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "查成绩"), ("assistant", "已找到成绩查询页")]
    assert calls[0]["tool_name"] == "resolve_page"
    assert calls[0]["ok"] == 1
    assert calls[0]["steps_json"] == '["router", "tool_executor", "generator"]'


async def test_无工具轮次不落_tool_calls(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)

    await build_repository(path).record_exchange(
        student_id="20230002", user_text="今天天气怎么样", assistant_text="我还不会回答这类问题。",
        tool_call=None, steps=["router", "generator"],
    )

    import aiosqlite

    async with aiosqlite.connect(path) as db:
        n = await (await db.execute("SELECT COUNT(*) FROM tool_calls")).fetchone()
        msgs = await (await db.execute("SELECT role FROM messages")).fetchall()

    assert n[0] == 0
    assert [m[0] for m in msgs] == ["user", "assistant"]
