import pytest

from app.config import Settings
from app.db.base import to_mysql_placeholders
from app.db.database import MySQLDatabase, SqliteDatabase, build_database
from app.db.migrations import init_sqlite, run_migrations


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
