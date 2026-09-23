import os

import pytest

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("SQLITE_PATH", "/tmp/s3-academic-test.db")


async def _seed_db() -> None:
    """建一个最小库，让 run_sql 有真行可查。"""
    import aiosqlite
    os.makedirs(os.path.dirname(os.environ["SQLITE_PATH"]), exist_ok=True)
    async with aiosqlite.connect(os.environ["SQLITE_PATH"]) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS enrollments (
                student_id TEXT, course_name TEXT, term TEXT, credits REAL,
                score REAL, grade_points REAL, teacher TEXT);
            CREATE VIEW IF NOT EXISTS v_grades AS
                SELECT student_id, course_name AS course, term, credits, score,
                       grade_points AS points, teacher FROM enrollments;
            DELETE FROM enrollments;
        """)
        await db.executemany(
            "INSERT INTO enrollments VALUES (?,?,?,?,?,?,?)",
            [("20230001", "高等数学（上）", "2025 秋", 5, 91, 4.1, "王建国"),
             ("20230007", "数据结构", "2026 春", 4, 93, 4.3, "李慧")])
        await db.commit()


async def test_describe_schema_任何地方都不出现student_id():
    await _seed_db()
    from server import describe_schema
    tables = await describe_schema()
    dumped = repr(tables)
    assert "student_id" not in dumped
    grades = next(t for t in tables if t.name == "v_grades")
    assert "course" in grades.columns and "score" in grades.columns


async def test_run_sql_只返回本人的行_A2场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT course, score FROM v_grades ORDER BY course",
                        student_id="20230001")
    assert res.ok is True
    assert [r[0] for r in res.rows] == ["高等数学（上）"]   # 林知远的行不出现
    assert "student_id = ?" in res.scoped_sql
    assert res.refused_code is None


async def test_run_sql_身份列拒绝且不执行_A3场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT * FROM v_grades WHERE student_id='20230007'",
                        student_id="20230001")
    assert res.ok is False
    assert res.refused_code == "identity_column"
    assert res.rows == []
    assert res.scoped_sql == ""          # 拒绝即不改写、不执行


async def test_run_sql_基表拒绝_A4场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT * FROM enrollments", student_id="20230001")
    assert res.ok is False and res.refused_code == "relation_not_whitelisted"


async def test_run_sql_多语句拒绝_A5场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT 1; DROP TABLE enrollments",
                        student_id="20230001")
    assert res.ok is False and res.refused_code == "multi_statement"


async def test_run_sql_耗时函数拒绝_A6场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT SLEEP(30)", student_id="20230001")
    assert res.ok is False and res.refused_code == "cost_function"
