from typing import Any, Literal, Protocol, Sequence


def to_mysql_placeholders(sql: str) -> str:
    """引号外的 ? 换成 %s；字符串字面量里的 ? 原样保留。

    约束（写进 Global Constraints）：调用方 SQL 的字面量内不得含 ?。
    """
    out: list[str] = []
    in_string = False
    for ch in sql:
        if ch == "'":
            in_string = not in_string
            out.append(ch)
        elif ch == "?" and not in_string:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


class Database(Protocol):
    """双驱动最小协议。调用方一律写 ? 占位符，方言差异收敛在实现里。"""

    dialect: Literal["mysql", "sqlite"]

    async def fetch_all(self, sql: str, args: Sequence[Any] = ()) -> list[dict]: ...
    async def execute(self, sql: str, args: Sequence[Any] = ()) -> int: ...
    async def execute_script(self, sql: str) -> None: ...
