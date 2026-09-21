import aiosqlite

from app.auth.students import (
    SEED_STUDENTS, Student, build_student_repository, seed_students,
)
from app.db.migrations import init_sqlite


async def test_seed_灌三个账号且可查回(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")

    assert await seed_students(db) == 3

    repo = build_student_repository(db)
    student = await repo.get("20230001")
    assert student is not None and student.name == "周晓楠"
    assert student.major == "计算机科学与技术"
    assert await repo.get_password_hash("20230001") is not None


async def test_不存在的学号返回None(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    await seed_students(db)

    assert await build_student_repository(db).get("20990001") is None


async def test_seed幂等_重复调用不重复插入(tmp_path):
    path = tmp_path / "campus.db"
    db = await init_sqlite(path)
    await seed_students(db)
    await seed_students(db)

    async with aiosqlite.connect(path) as conn:
        n = await (await conn.execute("SELECT COUNT(*) FROM students")).fetchone()
    assert n[0] == 3


async def test_密码不以明文入库(tmp_path):
    path = tmp_path / "campus.db"
    db = await init_sqlite(path)
    await seed_students(db)

    async with aiosqlite.connect(path) as conn:
        row = await (await conn.execute(
            "SELECT password_hash FROM students WHERE student_id='20230001'")).fetchone()
    assert row[0].startswith("pbkdf2_sha256$")
    assert "demo1234" not in row[0]


def test_seed常量形状():
    assert len(SEED_STUDENTS) == 3
    assert isinstance(SEED_STUDENTS[0][0], Student)
    assert {s.student_id for s, _ in SEED_STUDENTS} == {"20230001", "20230002", "20230007"}
