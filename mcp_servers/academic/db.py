"""最薄执行层：只负责"跑一条只读 SQL 并取回列与行"。

与 backend/app/db/database.py 的分工：那边服务应用全生命周期（连接池、
迁移、脚本），这边只服务 run_sql 一个调用点。占位符转换算法两边必须一致。
"""
import os
from pathlib import Path
from typing import Any

from rewriter import to_mysql_placeholders


def _dialect() -> str:
    return os.environ.get("DB_BACKEND", "sqlite")


async def query(sql: str, args: tuple[Any, ...] = ()) -> tuple[list[str], list[list[Any]]]:
    if _dialect() == "sqlite":
        import aiosqlite
        path = Path(os.environ.get("SQLITE_PATH", "../backend/data/campus.db"))
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(sql, args)
            rows = await cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
            return columns, [list(r) for r in rows]

    import aiomysql
    pool = await aiomysql.create_pool(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        db=os.environ.get("MYSQL_DATABASE", "campus"),
        minsize=1, maxsize=2, autocommit=True, pool_recycle=600)
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # args 为 None 时 pymysql 才跳过 % 格式化（同 backend 的坑）
                await cur.execute(to_mysql_placeholders(sql), args or None)
                rows = await cur.fetchall()
                columns = [d[0] for d in cur.description] if cur.description else []
                return columns, [list(r) for r in rows]
    finally:
        pool.close()
        await pool.wait_closed()
