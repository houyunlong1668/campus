from pathlib import Path

from .base import Database
from .database import SqliteDatabase

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# schema_version 自身不能用迁移文件建（鸡生蛋），只能由迁移器按方言写死。
# 这是全局约束"代码里不许有方言分支"的唯一豁免点。
_VERSION_DDL = {
    "sqlite": ("CREATE TABLE IF NOT EXISTS schema_version ("
               "version INTEGER PRIMARY KEY,"
               " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"),
    "mysql": ("CREATE TABLE IF NOT EXISTS schema_version ("
              "version INTEGER PRIMARY KEY,"
              " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"),
}


async def run_migrations(db: Database) -> list[int]:
    """按序执行未应用的 <version>_<name>.sql；单文件全部语句成功后才记版本号。"""
    await db.execute(_VERSION_DDL[db.dialect])

    applied = {r["version"] for r in await db.fetch_all("SELECT version FROM schema_version")}
    newly: list[int] = []
    for f in sorted((MIGRATIONS_DIR / db.dialect).glob("*.sql")):
        version = int(f.name.split("_", 1)[0])
        if version in applied:
            continue
        await db.execute_script(f.read_text(encoding="utf-8"))
        await db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        newly.append(version)
    return newly


async def init_sqlite(path: Path) -> Database:
    """测试与 sqlite 模式启动共用：建父目录 + 建库 + 跑迁移。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = SqliteDatabase(path)
    await run_migrations(db)
    return db


class LegacySchemaError(RuntimeError):
    """库里躺着 S2 之前的 conversations 形状：必须人工清库，应用不自作主张删数据。"""


async def assert_current_schema(db: Database) -> None:
    """迁移后探测"遗留形状"，只许在 conversations 无 session_id 时通过。

    0001_init.sql 用的是 CREATE TABLE IF NOT EXISTS——它对已存在的旧表既不改
    也不报错，schema_version 照样记 1，于是 pre-S2 的库（backend/data/campus.db
    或旧 MySQL 卷）里 session_id NOT NULL 还在，/chat 运行期逐条 500 而 /health
    全绿。这里反过来探测：探针语句只在遗留表上成功；新形状下两个驱动都会抛
    （SQLite: no such column: session_id；MySQL: 1054），捕获即视为通过。
    故意不用 PRAGMA/information_schema 查列——那是计划禁止的方言分支。
    """
    try:
        await db.fetch_all("SELECT COUNT(session_id) FROM conversations")
    except Exception:
        return
    raise LegacySchemaError(
        "检测到 S2 之前的遗留数据库：conversations 仍含 session_id 列，"
        "POST /chat 会在运行期持续失败。修复（二选一，按后端）："
        "SQLite 删除 backend/data/campus.db；MySQL 删除数据卷"
        "（docker compose -f deploy/docker-compose.yml down -v && up -d，"
        "随后重新执行 deploy/mysql/lockdown_agent_ro.sql）。然后重启应用。")
