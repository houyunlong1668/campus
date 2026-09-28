import pytest

from app.config import Settings
from app.db.base import to_mysql_placeholders
from app.db.database import MySQLDatabase, SqliteDatabase, build_database
from app.db.migrations import (
    LegacySchemaError, assert_current_schema, init_sqlite, run_migrations,
)
from app.db.upsert import save_row


def test_占位符转换只动引号外的问号():
    sql = "SELECT * FROM t WHERE name = 'a?b' AND id = ? AND note = 'x'"
    assert to_mysql_placeholders(sql) == "SELECT * FROM t WHERE name = 'a?b' AND id = %s AND note = 'x'"


def test_占位符转换无问号时原样返回():
    sql = "SELECT 1"
    assert to_mysql_placeholders(sql) == sql


async def test_sqlite_增删查(tmp_path):
    db = SqliteDatabase(tmp_path / "t.db")
    await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    rowid = await db.execute("INSERT INTO t (name) VALUES (?)", ("周晓楠",))
    assert rowid == 1
    rows = await db.fetch_all("SELECT id, name FROM t WHERE name = ?", ("周晓楠",))
    assert rows == [{"id": 1, "name": "周晓楠"}]


async def test_sqlite_execute_script_多语句(tmp_path):
    db = SqliteDatabase(tmp_path / "t.db")
    await db.execute_script("CREATE TABLE a (id INTEGER);\nCREATE TABLE b (id INTEGER);")
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('a','b')")
    assert {r["name"] for r in rows} == {"a", "b"}


async def test_迁移按序应用且幂等(tmp_path):
    path = tmp_path / "campus.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = SqliteDatabase(path)

    assert await run_migrations(db) == [1, 2, 3, 4]  # 首次：应用 0001–0004
    assert await run_migrations(db) == []       # 再次：幂等，无新应用

    # 九张业务表 + schema_version 都在
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    assert {
        "students", "courses", "enrollments", "course_sections", "makeup_items",
        "library_loans", "conversations", "messages", "tool_calls", "schema_version",
        "makeup_registrations",
    } <= names

    # 迁移在 schema_version 留了痕
    versions = await db.fetch_all("SELECT version FROM schema_version ORDER BY version")
    assert [v["version"] for v in versions] == [1, 2, 3, 4]


def test_build_database_按配置选实现():
    s = Settings(db_backend="sqlite")
    assert build_database(s).dialect == "sqlite"
    s = Settings(db_backend="mysql", mysql_password="x")
    assert isinstance(build_database(s), MySQLDatabase)
    with pytest.raises(ValueError):
        build_database(Settings(db_backend="oracle"))


def test_MySQLDatabase_构造即记录方言与连接参数_不真正连接():
    db = MySQLDatabase(host="127.0.0.1", port=3306, user="root",
                       password="pw", database="campus")
    assert db.dialect == "mysql"
    assert db.host == "127.0.0.1" and db.database == "campus"


def test_build_database_sqlite模式自动建运行态目录(tmp_path):
    """全新 clone 没有 backend/data/（gitignored），旧 lifespan 因此在首启就炸
    `unable to open database file`；建目录是 build_database 的责任。"""
    path = tmp_path / "data" / "nested" / "campus.db"
    assert not path.parent.exists()

    db = build_database(Settings(db_backend="sqlite", sqlite_path=path))

    assert db.dialect == "sqlite"
    assert path.parent.is_dir()


async def test_save_row_插入分支与更新分支(tmp_path):
    db = SqliteDatabase(tmp_path / "t.db")
    await db.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT, note TEXT)")

    await save_row(db, "t", {"id": "a"}, {"name": "甲", "note": "只写一次"})
    assert await db.fetch_all("SELECT id, name, note FROM t") == [
        {"id": "a", "name": "甲", "note": "只写一次"}]

    # 主键命中 → 走 UPDATE，只改给出的非键列，未给出的列保持原值
    await save_row(db, "t", {"id": "a"}, {"name": "乙"})
    assert await db.fetch_all("SELECT id, name, note FROM t ORDER BY id") == [
        {"id": "a", "name": "乙", "note": "只写一次"}]

    await save_row(db, "t", {"id": "b"}, {"name": "丙", "note": "n"})
    assert len(await db.fetch_all("SELECT id FROM t")) == 2


async def test_save_row_拒绝拼得出注入的标识符(tmp_path):
    db = SqliteDatabase(tmp_path / "t.db")
    await db.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT)")

    with pytest.raises(ValueError):
        await save_row(db, "t", {"id": "a"}, {"name, note": "甲"})
    with pytest.raises(ValueError):
        await save_row(db, "t; DROP TABLE t", {"id": "a"}, {"name": "甲"})


async def test_遗留形状库被探针拒绝启动(tmp_path):
    """S1 时代的库：conversations 带 session_id NOT NULL。0001 的
    CREATE TABLE IF NOT EXISTS 既不改也不报错、schema_version 照样记 1，
    于是 /chat 运行期逐条失败而 /health 全绿——必须启动期就拒绝。"""
    path = tmp_path / "campus.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = SqliteDatabase(path)
    await db.execute_script(
        "CREATE TABLE conversations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " student_id TEXT NOT NULL DEFAULT '',"
        " session_id TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')));")
    await run_migrations(db)

    with pytest.raises(LegacySchemaError) as err:
        await assert_current_schema(db)
    assert "backend/data/campus.db" in str(err.value)   # 报错必须给出可执行的修法


async def test_新形状库通过探针(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")

    await assert_current_schema(db)   # 不抛即通过


async def test_0002语义视图可查且首列是student_id(tmp_path):
    """视图必须存在，且 student_id 作为第一列留着给改写器用（spec 4.1），
    但列集刻意收窄成口语化命名。"""
    db = await init_sqlite(tmp_path / "campus.db")
    for view in ("v_grades", "v_schedule", "v_makeup", "v_loans"):
        await db.fetch_all(f"SELECT * FROM {view} LIMIT 1")
    rows = await db.fetch_all("PRAGMA table_info(v_grades)")
    assert [c["name"] for c in rows][0] == "student_id"
    assert [c["name"] for c in rows][1:] == [
        "course", "term", "credits", "score", "points", "teacher"]


async def test_0003_sql_queries表存在(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    await db.execute(
        "INSERT INTO sql_queries (conversation_id, student_id, sql_raw,"
        " sql_scoped, refused_code, row_count, latency_ms)"
        " VALUES (?,?,?,?,?,?,?)",
        (1, "20230001", "SELECT 1", "SELECT 1", "identity_column", 0, 3))
    rows = await db.fetch_all("SELECT refused_code FROM sql_queries")
    assert rows == [{"refused_code": "identity_column"}]


async def test_0004_step_details列与补考报名表(tmp_path):
    """step_details_json 列存在且有 SQLite 侧 DDL 默认值 '[]'；makeup_registrations
    带 UNIQUE(student_id, course_code)，重复报名被挡（/confirm 幂等的地基）。"""
    db = await init_sqlite(tmp_path / "campus.db")

    rows = await db.fetch_all("PRAGMA table_info(tool_calls)")
    col = next(c for c in rows if c["name"] == "step_details_json")
    assert col["notnull"] == 1 and col["dflt_value"] == "'[]'"

    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230001', '周晓楠', 'x')")
    await db.execute(
        "INSERT INTO makeup_registrations (student_id, course_code, course_name)"
        " VALUES ('20230001', 'MATH2041', '高等数学（下）')")
    rows = await db.fetch_all(
        "SELECT student_id, course_code, course_name, kind FROM makeup_registrations")
    assert rows == [{"student_id": "20230001", "course_code": "MATH2041",
                     "course_name": "高等数学（下）", "kind": "补考"}]

    with pytest.raises(Exception):  # UNIQUE(student_id, course_code) 挡重复报名
        await db.execute(
            "INSERT INTO makeup_registrations (student_id, course_code, course_name)"
            " VALUES ('20230001', 'MATH2041', '高等数学（下）')")
