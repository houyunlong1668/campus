"""方言无关的"先查后写"。

为什么不用 upsert 语法糖：
- ``ON CONFLICT ... DO UPDATE SET ... excluded.*`` 是 SQLite/PostgreSQL 写法，MySQL 8.4 完全不认；
- ``REPLACE INTO`` 看着像 MySQL 版 upsert，但它是 DELETE + INSERT，被外键 RESTRICT 引用主键的
  子表（enrollments / course_sections / makeup_items / library_loans 引用 students、courses）
  在第二次幂等运行时会直接报外键错。
所以这里只用最普通的 SELECT / UPDATE / INSERT 三种语句——两个方言都支持，且代码里没有任何方言分支。

全局约束里"调用方 SQL 一律写 ? 占位符"在这里同样成立：值全部走占位符，只有表名与列名是拼进
SQL 的字符串，故对它们做标识符白名单校验（列名/表名只许来自代码里的常量，不许来自入参）。
"""

import re
from typing import Any, Mapping, Sequence

from .base import Database

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _checked(name: str) -> str:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"非法的表名/列名，拒绝拼进 SQL: {name!r}")
    return name


async def save_row(db: Database, table: str, key: Mapping[str, Any],
                   values: Mapping[str, Any]) -> None:
    """按键列 ``key`` 定位一行：存在就只更新 ``values`` 里的非键列，不存在就整行插入。

    ``key`` 与 ``values`` 的列名不得重叠，``key`` 至少一列；``values`` 为空时命中即什么都不做。
    重复调用不会产生新行（幂等），也不会像 REPLACE INTO 那样删掉再建。
    """
    _checked(table)
    key_cols = [_checked(c) for c in key]
    value_cols = [_checked(c) for c in values]
    if not key_cols:
        raise ValueError("key 至少要有一列，否则无法定位行")
    overlap = set(key_cols) & set(value_cols)
    if overlap:
        raise ValueError(f"key 与 values 列名重叠: {sorted(overlap)}")

    where = " AND ".join(f"{c} = ?" for c in key_cols)
    key_args = tuple(key[c] for c in key_cols)
    rows = await db.fetch_all(f"SELECT {key_cols[0]} FROM {table} WHERE {where}", key_args)

    if rows:
        if not value_cols:
            return
        assignments = ", ".join(f"{c} = ?" for c in value_cols)
        await db.execute(
            f"UPDATE {table} SET {assignments} WHERE {where}",
            tuple(values[c] for c in value_cols) + key_args,
        )
        return

    insert_cols: Sequence[str] = key_cols + value_cols
    marks = ", ".join("?" for _ in insert_cols)
    await db.execute(
        f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES ({marks})",
        key_args + tuple(values[c] for c in value_cols),
    )
