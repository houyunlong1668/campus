from pathlib import Path
from typing import Any, Sequence

from .base import Database, to_mysql_placeholders


class SqliteDatabase:
    dialect = "sqlite"

    def __init__(self, path: Path):
        self._path = path

    async def fetch_all(self, sql: str, args: Sequence[Any] = ()) -> list[dict]:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, args)
            return [dict(r) for r in await cur.fetchall()]

    async def execute(self, sql: str, args: Sequence[Any] = ()) -> int:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(sql, args)
            await db.commit()
            return cur.lastrowid or 0

    async def execute_script(self, sql: str) -> None:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            await db.executescript(sql)
            await db.commit()


class MySQLDatabase:
    dialect = "mysql"

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host, self.port, self.user, self.password, self.database = (
            host, port, user, password, database)
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            import aiomysql

            self._pool = await aiomysql.create_pool(
                host=self.host, port=self.port, user=self.user,
                password=self.password, db=self.database,
                minsize=1, maxsize=5, autocommit=True, pool_recycle=600,
            )
        return self._pool

    async def fetch_all(self, sql: str, args: Sequence[Any] = ()) -> list[dict]:
        import aiomysql

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(to_mysql_placeholders(sql), args)
                return list(await cur.fetchall())

    async def execute(self, sql: str, args: Sequence[Any] = ()) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(to_mysql_placeholders(sql), args)
                return cur.lastrowid or 0

    async def execute_script(self, sql: str) -> None:
        # 迁移 DDL 不含存储过程/函数，按分号切分即可（spec 6.3 的单文件一事务
        # 由迁移器在脚本外包裹保证：脚本内每条自动提交，失败即抛出让本文件版本不入账）。
        for stmt in (s.strip() for s in sql.split(";")):
            if stmt:
                await self.execute(stmt)


def build_database(settings) -> Database:
    if settings.db_backend == "sqlite":
        return SqliteDatabase(settings.sqlite_path)
    if settings.db_backend == "mysql":
        return MySQLDatabase(
            host=settings.mysql_host, port=settings.mysql_port,
            user=settings.mysql_user, password=settings.mysql_password,
            database=settings.mysql_database,
        )
    raise ValueError(f"未知 DB_BACKEND: {settings.db_backend}")
