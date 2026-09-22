import logging
import time

from mcp.server import MCPServer
from pydantic import BaseModel

import db as db_mod
from guard import validate
from rewriter import rewrite

logging.basicConfig(level=logging.INFO)  # stderr，严禁 print 到 stdout

server = MCPServer("academic")

# 中文列义只给模型看，帮助它写出贴合问题的 SQL；不含 student_id（spec 4.1）
SCHEMA: list[dict] = [
    {"name": "v_grades", "columns": ["course", "term", "credits", "score", "points", "teacher"],
     "description": "成绩视图：课程名、学期、学分、分数、绩点、教师"},
    {"name": "v_schedule", "columns": ["course", "weekday", "start_period", "end_period",
                                       "room", "teacher", "weeks"],
     "description": "课表视图：课程名、星期(1=周一)、起止节次、教室、教师、周次范围"},
    {"name": "v_makeup", "columns": ["course", "kind", "reason", "scheduled_at", "place",
                                     "status", "seats_left"],
     "description": "补考重修视图：课程名、类型(补考/重修)、原因、时间、地点、状态、剩余名额"},
    {"name": "v_loans", "columns": ["title", "call_no", "due_at", "days_left", "shelf"],
     "description": "在借图书视图：书名、索书号、应还日期、剩余天数、书架位置"},
]


class SchemaTable(BaseModel):
    name: str
    columns: list[str]
    description: str


class SqlResult(BaseModel):
    ok: bool
    columns: list[str] = []
    rows: list[list] = []
    scoped_sql: str = ""
    refused_code: str | None = None
    refused_message: str | None = None
    row_count: int = 0
    latency_ms: int = 0


@server.tool()
async def describe_schema() -> list[SchemaTable]:
    """返回可查询的语义视图与列含义，供模型写 SQL。不含任何身份列。"""
    return [SchemaTable(**t) for t in SCHEMA]


@server.tool()
async def run_sql(sql: str, student_id: str) -> SqlResult:
    """执行只读查询。student_id 由调用方服务端注入，不出现在给模型的 schema 中。"""
    start = time.perf_counter()

    dialect = db_mod._dialect()
    guard = validate(sql, dialect)
    if not guard.ok:
        return SqlResult(ok=False, refused_code=guard.code,
                         refused_message=guard.message,
                         latency_ms=int((time.perf_counter() - start) * 1000))

    scoped = rewrite(guard.tree)
    try:
        columns, rows = await db_mod.query(scoped, (student_id,))
    except Exception as exc:
        return SqlResult(ok=False, scoped_sql=scoped,
                         refused_code="db_unavailable",
                         refused_message=f"{type(exc).__name__}: {exc}",
                         latency_ms=int((time.perf_counter() - start) * 1000))
    return SqlResult(ok=True, columns=columns, rows=rows, scoped_sql=scoped,
                     row_count=len(rows),
                     latency_ms=int((time.perf_counter() - start) * 1000))


if __name__ == "__main__":
    server.run(transport="stdio")
