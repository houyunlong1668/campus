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

    assert await run_migrations(db) == [1]      # 首次：应用 0001
    assert await run_migrations(db) == []       # 再次：幂等，无新应用

    # 九张业务表 + schema_version 都在
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    assert {
        "students", "courses", "enrollments", "course_sections", "makeup_items",
        "library_loans", "conversations", "messages", "tool_calls", "schema_version",
    } <= names

    # 迁移在 schema_version 留了痕
    versions = await db.fetch_all("SELECT version FROM schema_version ORDER BY version")
    assert [v["version"] for v in versions] == [1]


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
