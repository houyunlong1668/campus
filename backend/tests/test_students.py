import aiosqlite

from app.auth.students import (
    SEED_STUDENTS, Student, build_student_repository, seed_students,
)
from app.db.engine import init_db


async def test_seed_灌三个账号且可查回(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)

    assert await seed_students(path) == 3

    repo = build_student_repository(path)
    student = await repo.get("20230001")
    assert student is not None and student.name == "周晓楠"
    assert student.major == "计算机科学与技术"
    assert await repo.get_password_hash("20230001") is not None


async def test_不存在的学号返回None(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    await seed_students(path)

    assert await build_student_repository(path).get("20990001") is None


async def test_seed幂等_重复调用不重复插入(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    await seed_students(path)
    await seed_students(path)

    async with aiosqlite.connect(path) as db:
        n = await (await db.execute("SELECT COUNT(*) FROM students")).fetchone()
    assert n[0] == 3


async def test_密码不以明文入库(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    await seed_students(path)

    async with aiosqlite.connect(path) as db:
        row = await (await db.execute(
            "SELECT password_hash FROM students WHERE student_id='20230001'")).fetchone()
    assert row[0].startswith("pbkdf2_sha256$")
    assert "demo1234" not in row[0]


async def test_老库缺列时init_db自动补上(tmp_path):
    """已存在的 conversations 表没有 student_id 列，CREATE IF NOT EXISTS 不会补，靠 _ensure_column。"""
    path = tmp_path / "campus.db"
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """CREATE TABLE conversations (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 session_id TEXT NOT NULL,
                 created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        await db.commit()

    await init_db(path)

    async with aiosqlite.connect(path) as db:
        cols = {r[1] for r in await (await db.execute("PRAGMA table_info(conversations)")).fetchall()}
    assert "student_id" in cols


def test_seed常量形状():
    assert len(SEED_STUDENTS) == 3
    assert isinstance(SEED_STUDENTS[0][0], Student)
    assert {s.student_id for s, _ in SEED_STUDENTS} == {"20230001", "20230002", "20230007"}
