from app.db.migrations import init_sqlite
from app.db.repository import build_repository


async def _seed_conversations(db, repo):
    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230001','周晓楠','x')")
    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230002','陈默','x')")
    # 本人第一条会话（两轮）
    await repo.record_exchange(student_id="20230001", user_text="第一问",
                               assistant_text="第一答", tool_call=None, steps=[])
    # 别人的会话（不得被读到）
    await repo.record_exchange(student_id="20230002", user_text="别人的问",
                               assistant_text="别人的答", tool_call=None, steps=[])
    # 本人最新一条会话（三轮）
    for i in range(2, 5):
        await repo.record_exchange(student_id="20230001",
                                   user_text=f"第{i}问", assistant_text=f"第{i}答",
                                   tool_call=None, steps=[])


async def test_history_取本人最近limit条消息_跨会话且排除他人(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)
    await _seed_conversations(db, repo)

    history = await repo.recent_history(student_id="20230001", limit=6)
    contents = [h["content"] for h in history]
    assert "别人的问" not in contents            # 跨用户隔离
    assert "第一问" not in contents              # 本人更早的消息被 limit 截掉
    assert contents == ["第2问", "第2答", "第3问", "第3答", "第4问", "第4答"]
    assert all(h["role"] in ("user", "assistant") for h in history)


async def test_history_不超limit且每条截到200字(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)
    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230001','周晓楠','x')")
    for i in range(8):
        await repo.record_exchange(student_id="20230001",
                                   user_text=f"{i}问" + "长" * 500,
                                   assistant_text=f"{i}答" + "长" * 500,
                                   tool_call=None, steps=[])

    history = await repo.recent_history(student_id="20230001", limit=6)
    assert len(history) == 6                       # 6 条消息（3 轮）封顶
    assert all(len(h["content"]) <= 200 for h in history)
    # 最新的在末尾
    assert history[-1]["content"].startswith("7答")


async def test_history_无人对话时返回空(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)
    assert await repo.recent_history(student_id="20230001", limit=6) == []
