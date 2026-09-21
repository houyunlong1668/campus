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
