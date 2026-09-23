# S3 查数能力（受约束 Text-to-SQL）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让助手从"只给跳转卡片"升级为"自己判断该跳转还是该查数"——模型写 SQL，后端先校验再改写成只含本人行的子查询执行，跨学期歧义出 `clarify` 选项条，实际执行的 SQL 外显给用户看。

**Architecture:** 新增语义视图（`v_grades`/`v_schedule`/`v_makeup`/`v_loans`）与 `mcp_servers/academic`（stdio，与 navigation 同构）。安全模型是**先校验后改写**：校验拒掉身份列/越界关系/多语句，改写把每个白名单关系替换成 `WHERE student_id = ?` 的内联子查询——模型没有不守规矩的能力，而不是靠提示词嘱咐。backend 侧 `TRUSTED_ARGS` 一面丢弃模型塞的身份参数、一面服务端强制注入。图从两节点扩到三态（navigate/query/answer）。

**Tech Stack:** FastAPI + langgraph、`mcp` 2.x stdio、`sqlglot`（AST 解析与改写，academic server 独立依赖）、aiosqlite/aiomysql、Vue 3 + vitest。

**Spec:** `docs/superpowers/specs/2026-09-20-campus-auth-text2sql-mysql-design.md`（§3 架构、§4 安全模型、§7.2/7.3/7.4 契约、§9.1 越权用例、§10 里程碑 S3 行）；路线与欠账承接见 `docs/superpowers/specs/2026-09-22-campus-roadmap-s4-s7-design.md` §3.1。

## Global Constraints

- 调用方 SQL 一律写 `?` 占位符；`%s` 只许出现在**驱动转换函数**里（backend 是 `database.py`，academic server 是它自己的 `db.py`），两处实现同一份引号感知算法。
- DDL 方言差异只许出现在 `backend/app/db/migrations/{mysql,sqlite}/` 文件里，代码里不许有方言分支（`build_database` 与 academic `db.py` 选驱动除外）。
- 迁移文件名集合双方言必须一致（契约脚本已有断言）。
- **执行顺序固定为先校验（spec 4.3）再改写（spec 4.2）**，不得颠倒——改写后校验会误伤自己注入的 `student_id`。
- `student_id` 永不出现在请求体、查询串、给模型看的 schema 里；只从会话取、由 `call_tool` 服务端注入。
- 拒绝时**不执行任何 SQL**，拒绝理由与原始模型输出写进 `sql_queries` 表。
- `describe_schema` 返回值任何位置不得出现字符串 `student_id`。
- 测试全跑 SQLite（`DB_BACKEND=sqlite`）；MySQL 方言差异由迁移文件集合契约 + 真库冒烟覆盖。
- **视图自带会话过滤（`CONNECTION_ID()`）明令不采用**：spec 4.5 已否决，理由是依赖未验证的 MySQL 限制且连接池会让"连接级身份"与"请求级身份"错配。实现隔离**只能**靠 SQL 改写层，不许顺手改架构。
- `validate_args` 的 `extra="forbid"` 已在 S1 落地（`backend/app/tools/base.py:58`），本计划**不重做**，只依赖它作为"模型塞未知字段即拒"的底线。
- `demo1234` 是本地仿真密码，不入库、不上公网（spec 455 告警）。
- 每个任务结束时提交一次。
- `mcp_servers/academic` 是独立 uv 项目，依赖不许从 `backend/pyproject.toml` 借。

## 与 spec 的两处显式偏离（先记账，评审按此判定）

1. **`intent` 字段语义**：spec 7.3 写 `intent: Literal["navigate","query","answer"]`，但 MVP 已把 `AgentState.intent` 用作**用户原话片段**（`generator` 拿它拼 nav_card 文案"与「…」最匹配的页面"）。直接改语义会把卡片文案变成"与「navigate」最匹配"。本计划**保留 `intent` 为原话片段**，另增 `route` 字段承载三态，语义与 spec 7.3 的分流规则完全一致。同时把已无语义的 `session_id` 改名为 `student_id`（它装的本来就是学号）。
2. **`sql_refused` 错误码的用法**：spec 4.3 要"拒绝原因回给 generator 转成人话"，spec 7.2 又把 `sql_refused` 加进错误码表。二者不矛盾：**generator 出人话解释 + chat 同时发一条 `error{code:"sql_refused"}`** 供前端标红，两句话都满足。

---

## File Structure

**新建：**

| 文件 | 单一职责 |
|---|---|
| `backend/app/db/migrations/{mysql,sqlite}/0002_semantic_views.sql` | 四个语义视图，双方言同名 |
| `backend/app/db/migrations/{mysql,sqlite}/0003_sql_queries.sql` | 拒绝/执行审计表 |
| `deploy/mysql/grant_agent_ro_views.sql` | 给 `agent_ro` 授四个视图的 SELECT（一次性运维脚本，非迁移：SQLite 无权限概念） |
| `mcp_servers/academic/{pyproject.toml,uv.lock}` | 独立 uv 项目，声明 `sqlglot` + 双驱动 |
| `mcp_servers/academic/guard.py` | 校验清单 10 条，纯函数，不碰 IO |
| `mcp_servers/academic/rewriter.py` | 关系替换为带过滤子查询，纯函数，不碰 IO |
| `mcp_servers/academic/db.py` | 最薄执行层：`query(sql) -> (columns, rows)`，按 env 选驱动 |
| `mcp_servers/academic/server.py` | MCP 工具 `describe_schema` / `run_sql`，串起 guard→rewrite→db |
| `mcp_servers/academic/tests/{test_guard,test_rewrite,test_server}.py` | 上面三件的单测 |
| `backend/app/tools/composite.py` | `CompositeRegistry`：多 MCP 子进程按工具名分派 |
| `backend/app/agent/nodes/sql_executor.py` | 查数节点：describe_schema → 模型写 SQL → run_sql → 澄清判定 |
| `backend/tests/test_sql_authz.py` | A1–A6 真路径越权用例 |
| `backend/tests/test_history.py` | history 回读只取本会话且不超 6 轮 |
| `frontend/src/components/chat/ClarifyBar.vue` | 澄清选项条 |
| `frontend/src/components/chat/SqlResultTable.vue` | 数据表 + `<details>` 折叠 SQL |

**修改：** `backend/app/db/repository.py`（`recent_history` + `record_exchange(sql=…)`）、`backend/app/config.py`（`academic_server_dir`/`history_limit`）、`backend/app/tools/base.py`（`TRUSTED_ARGS`、协议加 `student_id`、schema 剔除）、`backend/app/tools/{stdio_mcp,inmemory}.py`、`backend/app/agent/state.py`、`backend/app/agent/graph.py`、`backend/app/agent/nodes/{router,generator}.py`、`backend/app/llm/{base,fake,openai_compat}.py`、`backend/app/main.py`（双 registry + env 透传）、`backend/app/schemas.py` 之外的 `chat.py`（history 注入、拒绝事件）、`frontend/src/types.ts`、`frontend/src/composables/useChatStream.ts`、`frontend/src/components/chat/{MessageBubble,MessageList}.vue`、`frontend/tests/useChatStream.test.ts`。

---

## Task 1: 语义视图与 `sql_queries` 表（双方言迁移 + 视图授权）

**Files:**
- Create: `backend/app/db/migrations/mysql/0002_semantic_views.sql`
- Create: `backend/app/db/migrations/sqlite/0002_semantic_views.sql`
- Create: `backend/app/db/migrations/mysql/0003_sql_queries.sql`
- Create: `backend/app/db/migrations/sqlite/0003_sql_queries.sql`
- Create: `deploy/mysql/grant_agent_ro_views.sql`
- Test: `backend/tests/test_database.py`（追加）

**Interfaces:**
- Consumes: 既有 `run_migrations(db)`、`init_sqlite(path)`、`Database.fetch_all`（签名见 `backend/app/db/migrations.py`）
- Produces: 四个可 `SELECT` 的视图 `v_grades`/`v_schedule`/`v_makeup`/`v_loans`；表 `sql_queries(id, conversation_id, student_id, sql_raw, sql_scoped, refused_code, row_count, latency_ms, created_at)`。Task 4 的 academic server 按名引用视图；Task 8 的 repository 写 `sql_queries`。

- [ ] **Step 1: 写失败测试（视图与新表存在且可查）**

追加到 `backend/tests/test_database.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_database.py -v -k "0002 or 0003"`
Expected: FAIL — `no such table: v_grades`

- [ ] **Step 3: 写双方言视图迁移**

`backend/app/db/migrations/sqlite/0002_semantic_views.sql`：

```sql
-- 语义层（spec 4.1）：模型只见这四个视图，列刻意收窄、命名口语化。
-- student_id 是第一列但不进 schema 提示——改写器需要它，模型不需要知道它存在。
-- SQLite 方言：`||` 代替 CONCAT，julianday 相减代替 DATEDIFF。
CREATE VIEW IF NOT EXISTS v_grades (student_id, course, term, credits, score, points, teacher) AS
  SELECT student_id, course_name, term, credits, score, grade_points, teacher
  FROM enrollments;

CREATE VIEW IF NOT EXISTS v_schedule (student_id, course, weekday, start_period, end_period, room, teacher, weeks) AS
  SELECT student_id, course_name, weekday, start_period, end_period, room, teacher,
         weeks_from || '-' || weeks_to
  FROM course_sections;

CREATE VIEW IF NOT EXISTS v_makeup (student_id, course, kind, reason, scheduled_at, place, status, seats_left) AS
  SELECT student_id, course_name, kind, reason, scheduled_at, place, status, seats_left
  FROM makeup_items;

CREATE VIEW IF NOT EXISTS v_loans (student_id, title, call_no, due_at, days_left, shelf) AS
  SELECT student_id, title, call_no, due_at,
         -- Ruling C 回填：两侧都先 date() 取纯日期差，julianday 带时间会差出 1 天
         CAST(julianday(date(due_at)) - julianday(date('now', 'localtime')) AS INTEGER),
         shelf
  FROM library_loans
  WHERE returned_at IS NULL;
```

`backend/app/db/migrations/mysql/0002_semantic_views.sql`：

```sql
-- MySQL 没有 CREATE VIEW IF NOT EXISTS，用 CREATE OR REPLACE 保证本文件可重入
-- （迁移器只跑一次，但半途失败重跑时不能卡在"view already exists"）。
CREATE OR REPLACE VIEW v_grades (student_id, course, term, credits, score, points, teacher) AS
  SELECT student_id, course_name, term, credits, score, grade_points, teacher
  FROM enrollments;

CREATE OR REPLACE VIEW v_schedule (student_id, course, weekday, start_period, end_period, room, teacher, weeks) AS
  SELECT student_id, course_name, weekday, start_period, end_period, room, teacher,
         CONCAT(weeks_from, '-', weeks_to)
  FROM course_sections;

CREATE OR REPLACE VIEW v_makeup (student_id, course, kind, reason, scheduled_at, place, status, seats_left) AS
  SELECT student_id, course_name, kind, reason, scheduled_at, place, status, seats_left
  FROM makeup_items;

CREATE OR REPLACE VIEW v_loans (student_id, title, call_no, due_at, days_left, shelf) AS
  SELECT student_id, title, call_no, due_at, DATEDIFF(due_at, CURDATE()), shelf
  FROM library_loans
  WHERE returned_at IS NULL;
```

- [ ] **Step 4: 写 `sql_queries` 迁移（双方言）**

`backend/app/db/migrations/sqlite/0003_sql_queries.sql`：

```sql
CREATE TABLE IF NOT EXISTS sql_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    student_id TEXT NOT NULL REFERENCES students(student_id),
    sql_raw TEXT NOT NULL,
    sql_scoped TEXT NOT NULL DEFAULT '',
    refused_code TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`backend/app/db/migrations/mysql/0003_sql_queries.sql`：

```sql
CREATE TABLE IF NOT EXISTS sql_queries (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    student_id VARCHAR(32) NOT NULL,
    sql_raw TEXT NOT NULL,
    sql_scoped TEXT NOT NULL,
    refused_code VARCHAR(32) NULL,
    row_count INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sq_conv (conversation_id),
    INDEX idx_sq_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_database.py -v`
Expected: 全绿（含既有 `test_迁移按序应用且幂等`，它会看到 `[1, 2, 3]` 而非 `[1]`——若该断言写死了 `[1]`，一并改成 `[1, 2, 3]`，并在同一次提交里注明迁移数变了）

- [ ] **Step 6: 契约脚本自动覆盖双方言同名**

Run: `backend/.venv/Scripts/python.exe scripts/check_routes_contract.py`
Expected: `OK: 迁移文件双方言同名 3 个`，exit 0。**若这里是 1 个**，说明只建了单方言文件——契约已经替你拦住了。

- [ ] **Step 7: 写视图授权脚本**

`deploy/mysql/grant_agent_ro_views.sql`（不是迁移文件：SQLite 无用户权限概念，放迁移会破坏"双方言同名"契约，与既有 `lockdown_agent_ro.sql` 同理）：

```sql
-- S3 起 agent_ro 只能读这四个语义视图，对 enrollments 等基表仍无权限（spec 4.4 纵深）。
GRANT SELECT ON campus.v_grades TO 'agent_ro'@'%';
GRANT SELECT ON campus.v_schedule TO 'agent_ro'@'%';
GRANT SELECT ON campus.v_makeup  TO 'agent_ro'@'%';
GRANT SELECT ON campus.v_loans    TO 'agent_ro'@'%';
FLUSH PRIVILEGES;
```

- [ ] **Step 8: 全量回归 + 提交**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: 全绿。**唯一会红的是 `test_迁移按序应用且幂等`**——它断言版本序列，新增 0002/0003 后必须改成 `[1, 2, 3]`（Step 5 已提示，属本任务范围内的正当修改，改断言时在 commit message 里点明迁移数变了）。其余 79 条一条都不许动。

```bash
git add backend/app/db/migrations deploy/mysql/grant_agent_ro_views.sql backend/tests/test_database.py
git commit -m "feat(db): 0002 语义视图与 0003 sql_queries，双方言同名 + agent_ro 视图授权"
```

---

## Task 2: academic server 校验清单（spec 4.3 的 10 条）

**Files:**
- Create: `mcp_servers/academic/pyproject.toml`
- Create: `mcp_servers/academic/guard.py`
- Test: `mcp_servers/academic/tests/test_guard.py`

**Interfaces:**
- Consumes: `sqlglot`（本任务引入）
- Produces: `guard.validate(sql: str, dialect: str) -> GuardResult`，其中 `GuardResult(ok: bool, code: str | None, message: str | None, tree: sqlglot.exp.Expression | None)`；拒绝码取值：`parse_error`/`multi_statement`/`not_query`/`relation_not_whitelisted`/`identity_column`/`variable`/`dangerous_clause`/`cost_function`/`forbidden_schema`。`WHITELIST = {"v_grades","v_schedule","v_makeup","v_loans"}`。Task 3 的 rewriter 消费 `GuardResult.tree`；Task 4 的 `run_sql` 消费 `code` 写进 `sql_queries.refused_code`。

- [ ] **Step 1: 建独立 uv 项目**

`mcp_servers/academic/pyproject.toml`（照 `mcp_servers/navigation/pyproject.toml` 的形状，加 `sqlglot` 与双驱动）：

```toml
[project]
name = "campus-mcp-academic"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.2,<3",
    "pydantic>=2.7",
    "sqlglot>=25",
    "aiosqlite>=0.20",
    "aiomysql>=0.2",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]

[tool.uv]
package = false
```

Run: `cd mcp_servers/academic && uv sync`
Expected: 生成 `uv.lock`，`uv run python -c "import sqlglot; print(sqlglot.__version__)"` 无报错

- [ ] **Step 2: 写失败测试（10 条逐条）**

`mcp_servers/academic/tests/test_guard.py`：

```python
import pytest

from guard import WHITELIST, validate

DIALECT = "sqlite"


def code_of(sql: str) -> str | None:
    r = validate(sql, DIALECT)
    return r.code if not r.ok else None


class Test规则1到3:
    def test_规则1_多语句拒绝(self):
        assert code_of("SELECT 1; DROP TABLE students") == "multi_statement"

    def test_规则2_非查询拒绝(self):
        assert code_of("DELETE FROM v_grades") == "not_query"
        assert code_of("DROP TABLE students") == "not_query"

    def test_规则2_允许查询族_UNION与CTE也算(self):
        # spec 4.2 把 UNION/子查询/CTE 列为必须能改写的形态，
        # 故规则 2 的"SELECT"按"查询语句族"读，不字面拒绝 UNION。
        assert validate("SELECT 1 UNION SELECT 2", DIALECT).ok
        assert validate("WITH t AS (SELECT 1 AS a) SELECT a FROM t", DIALECT).ok

    def test_规则3_白名单外关系拒绝(self):
        assert code_of("SELECT * FROM enrollments") == "relation_not_whitelisted"
        assert code_of("SELECT * FROM v_grades g JOIN students s ON 1=1") == \
            "relation_not_whitelisted"


class Test规则4到8:
    def test_规则4_身份列拒绝(self):
        assert code_of("SELECT * FROM v_grades WHERE student_id='20230007'") == \
            "identity_column"

    def test_规则4_别名下身份列同样拒绝(self):
        assert code_of("SELECT g.student_id FROM v_grades AS g") == "identity_column"

    def test_规则5_变量与系统函数拒绝(self):
        assert code_of("SELECT @x") == "variable"
        assert code_of("SELECT DATABASE()") == "variable"
        assert code_of("SELECT CONNECTION_ID()") == "variable"

    def test_规则6_危险子句拒绝(self):
        assert code_of("SELECT * FROM v_grades INTO OUTFILE '/tmp/x'") == "dangerous_clause"
        assert code_of("SELECT * FROM v_grades FOR UPDATE") == "dangerous_clause"
        assert code_of("SELECT LOAD_FILE('/etc/passwd')") == "dangerous_clause"

    def test_规则7_耗时函数拒绝(self):
        assert code_of("SELECT SLEEP(30)") == "cost_function"
        assert code_of("SELECT BENCHMARK(1,1)") == "cost_function"
        assert code_of("SELECT GET_LOCK('a',1)") == "cost_function"

    def test_规则8_系统库拒绝(self):
        assert code_of("SELECT * FROM information_schema.tables") == "forbidden_schema"
        assert code_of("SELECT * FROM mysql.user") == "forbidden_schema"


class Test规则9到10:
    def test_规则9_无LIMIT补50_有LIMIT收窄到200(self):
        r = validate("SELECT * FROM v_grades", DIALECT)
        assert r.ok and r.tree is not None
        assert r.tree.args.get("limit") is not None
        assert str(r.tree.args["limit"].expression.this) == "50"

        r = validate("SELECT * FROM v_grades LIMIT 5000", DIALECT)
        assert str(r.tree.args["limit"].expression.this) == "200"

    def test_规则9_已有小LIMIT原样保留(self):
        r = validate("SELECT * FROM v_grades LIMIT 10", DIALECT)
        assert str(r.tree.args["limit"].expression.this) == "10"

    def test_规则10_解析失败拒绝且不降级(self):
        assert code_of("SELECT FROM WHERE") == "parse_error"


def test_白名单就是四个语义视图():
    assert WHITELIST == {"v_grades", "v_schedule", "v_makeup", "v_loans"}
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd mcp_servers/academic && uv run pytest tests/test_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'guard'`

- [ ] **Step 4: 写实现**

`mcp_servers/academic/guard.py`：

```python
"""spec 4.3 校验清单：任一不过即拒绝，拒绝时不执行任何 SQL。

顺序固定：解析（含多语句、语句类型）→ 结构检查（关系白名单、身份列）→
正则检查（变量/危险子句/耗时函数/系统库）→ LIMIT 归一。
结构检查用 AST 是因为别名、大小写、嵌套只有解析才看得清；
正则检查用原文是为绕开方言解析差异（反引号、函数名变体），
两条路径各司其职，谁也别代替谁。
"""
import re
import sqlglot
from dataclasses import dataclass
from sqlglot import exp

WHITELIST = {"v_grades", "v_schedule", "v_makeup", "v_loans"}
IDENTITY_COLUMNS = {"student_id"}
FORBIDDEN_SCHEMAS = {"information_schema", "mysql", "performance_schema", "sys"}
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# spec 4.2 把 UNION/子查询/CTE 列为必须能改写的形态，故"语句类型必须是 SELECT"
# 按查询语句族读；DML/DDL 一律拒。
_QUERY_TYPES = (exp.Select, exp.Union, exp.Subquery, exp.Intersect, exp.Except)

_RE_VARIABLE = re.compile(
    r"@\w+|CONNECTION_ID\s*\(|DATABASE\s*\(|SCHEMA\s*\(|VERSION\s*\(|"
    r"USER\s*\(|CURRENT_USER|SESSION_ID\s*\(|@@", re.I)
_RE_DANGEROUS = re.compile(
    r"INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE\s*\(|FOR\s+UPDATE|"
    r"LOCK\s+IN\s+SHARE\s+MODE|INTO\s+OUTFILE", re.I)
_RE_COST = re.compile(r"\b(SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK)\s*\(", re.I)


@dataclass
class GuardResult:
    ok: bool
    code: str | None = None
    message: str | None = None
    tree: exp.Expression | None = None


def _refuse(code: str, message: str) -> GuardResult:
    return GuardResult(ok=False, code=code, message=message)


def validate(sql: str, dialect: str) -> GuardResult:
    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except Exception:
        return _refuse("parse_error", "查询语句无法解析")

    if len(statements) != 1 or statements[0] is None:
        return _refuse("multi_statement", "一次只允许一条查询")
    tree = statements[0]

    if not isinstance(tree, _QUERY_TYPES):
        return _refuse("not_query", "只能查询，不能修改数据")

    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        db = (table.db or "").lower()
        if db in FORBIDDEN_SCHEMAS or name in FORBIDDEN_SCHEMAS:
            return _refuse("forbidden_schema", "该数据不在可查询范围")
        if name not in WHITELIST:
            return _refuse("relation_not_whitelisted", "该数据不在可查询范围")

    for col in tree.find_all(exp.Column):
        if col.name.lower() in IDENTITY_COLUMNS:
            return _refuse("identity_column", "无需指定身份，系统已按你的账号过滤")

    if _RE_VARIABLE.search(sql):
        return _refuse("variable", "不支持变量")
    if _RE_DANGEROUS.search(sql):
        return _refuse("dangerous_clause", "不支持")
    if _RE_COST.search(sql):
        return _refuse("cost_function", "不支持")

    _normalize_limit(tree)
    return GuardResult(ok=True, tree=tree)


def _normalize_limit(tree: exp.Expression) -> None:
    """规则 9：无 LIMIT 补 50，有则收窄到 min(n, 200)。"""
    limit = tree.args.get("limit")
    if limit is None:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_LIMIT)))
        return
    try:
        current = int(limit.expression.this)
    except (ValueError, TypeError):
        tree.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_LIMIT)))
        return
    if current > MAX_LIMIT:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(MAX_LIMIT)))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd mcp_servers/academic && uv run pytest tests/test_guard.py -v`
Expected: 全绿（约 18 条）
- [ ] **Step 6: 提交**

```bash
git add mcp_servers/academic/pyproject.toml mcp_servers/academic/uv.lock mcp_servers/academic/guard.py mcp_servers/academic/tests/test_guard.py
git commit -m "feat(mcp-academic): spec 4.3 十条校验清单，先解析后正则分层拒绝"
```

---

## Task 3: 改写器——把白名单关系换成只含本人行的子查询

**Files:**
- Create: `mcp_servers/academic/rewriter.py`
- Test: `mcp_servers/academic/tests/test_rewrite.py`

**Interfaces:**
- Consumes: `GuardResult.tree`（Task 2）、`WHITELIST`
- Produces: `rewrite(tree: sqlglot.exp.Expression) -> str`，返回带 `?` 占位符的可执行 SQL 文本（**不含** `%s`）；`to_mysql_placeholders(sql: str) -> str`（引号外 `?`→`%s`，与 backend 同一算法，只在驱动边界调用）。Task 4 的 `run_sql` 串接两者。

- [ ] **Step 1: 写失败测试（spec 4.2 的八种形态 + 占位符不被污染）**

`mcp_servers/academic/tests/test_rewrite.py`：

```python
import sqlglot

from guard import validate
from rewriter import rewrite, to_mysql_placeholders


def scope(sql: str) -> str:
    r = validate(sql, "sqlite")
    assert r.ok, r.message
    assert r.tree is not None
    return rewrite(r.tree)


def test_单表_替换为带过滤子查询():
    out = scope("SELECT course, score FROM v_grades WHERE course LIKE '%高等数学%' ORDER BY term")
    assert "(SELECT * FROM v_grades WHERE student_id = ?)" in out
    assert out.count("student_id = ?") == 1          # 只注入一次
    assert "FROM v_grades WHERE" not in out.replace(
        "(SELECT * FROM v_grades WHERE student_id = ?)", "")  # 原引用点已消失


def test_别名遮蔽_别名保持可引用():
    out = scope("SELECT g.course FROM v_grades AS g JOIN v_grades AS h ON 1=1")
    # 两处引用都换成子查询，别名各自保留，h.* 不会套住 g 的过滤
    assert out.count("WHERE student_id = ?") == 2
    assert "AS g" in out and "AS h" in out


def test_子查询_内外层都被替换():
    out = scope("SELECT * FROM v_grades WHERE score > "
                "(SELECT AVG(score) FROM v_grades)")
    assert out.count("WHERE student_id = ?") == 2


def test_CTE_引用点同样替换():
    out = scope("WITH t AS (SELECT course FROM v_grades) SELECT * FROM t")
    assert "WHERE student_id = ?" in out
    assert "FROM t" in out  # CTE 名 t 不是白名单关系，原样保留


def test_UNION_两侧都替换():
    out = scope("SELECT course FROM v_grades UNION SELECT course FROM v_schedule")
    assert out.count("WHERE student_id = ?") == 2


def test_JOIN_多表_每个引用点各一次():
    out = scope("SELECT a.course, b.course FROM v_grades a JOIN v_schedule b ON a.student_id=b.student_id"
                .replace("a.student_id=b.student_id", "1=1"))
    assert out.count("WHERE student_id = ?") == 2


def test_反引号与大小写混排_仍被识别():
    out = scope("SELECT `Course` FROM V_GRADES")
    assert "WHERE student_id = ?" in out


def test_占位符在改写后仍是问号_不是百分号s():
    """sqlglot 无方言生成必须保持 ?；若某版本把它规范化成 %s，
    这条会红——那正是必须先修的接缝，不许把断言放宽来让它绿。"""
    out = scope("SELECT course FROM v_grades WHERE score > ?")
    assert "?" in out
    assert "%s" not in out


def test_表名在字符串字面量里不算引用():
    out = scope("SELECT course FROM v_grades WHERE course LIKE '%v_schedule%'")
    assert out.count("WHERE student_id = ?") == 1


def test_to_mysql_placeholders_只动引号外的问号():
    sql = "SELECT * FROM t WHERE name = 'a?b' AND id = ? AND note = 'x'"
    assert to_mysql_placeholders(sql) == \
        "SELECT * FROM t WHERE name = 'a?b' AND id = %s AND note = 'x'"


def test_to_mysql_placeholders_无问号原样返回():
    assert to_mysql_placeholders("SELECT 1") == "SELECT 1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd mcp_servers/academic && uv run pytest tests/test_rewrite.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rewriter'`

- [ ] **Step 3: 写实现**

`mcp_servers/academic/rewriter.py`：

```python
"""spec 4.2 关系替换：把每个白名单关系的引用点换成"已按当前学号过滤"的内联子查询。

为什么替换关系而不是在外层追加 WHERE：外层追加对 UNION、子查询、CTE、JOIN
全部无效，模型只要写出一条复合语句就漏了。替换发生在每个引用点上，
结构再复杂也绕不过去。顺序上必须先过 guard.validate 再调本模块——
改写会注入 student_id，之后再校验会误伤自己（spec 4.2 明令禁止颠倒）。
"""
import sqlglot
from sqlglot import exp

from guard import WHITELIST


def rewrite(tree: exp.Expression) -> str:
    """就地替换并返回文本。调用方拿到的永远是 `?` 占位符版本。"""
    for table in list(tree.find_all(exp.Table)):
        if table.name.lower() not in WHITELIST:
            continue
        if table.find_ancestor(exp.Table):  # 已在我们造的子查询里，别套娃
            continue
        alias = table.alias or table.name
        inner = sqlglot.parse_one(
            f"SELECT * FROM {table.name} WHERE student_id = ?")
        subquery = exp.Subquery(this=inner, alias=alias)
        table.replace(subquery)
    return tree.sql()


def to_mysql_placeholders(sql: str) -> str:
    """引号外的 ? 换成 %s；与 backend/app/db/base.py 同一算法，只在驱动边界调用。

    两处必须一致：调用方一律写 ?，%s 只许出现在驱动转换函数里（全局约束）。
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd mcp_servers/academic && uv run pytest -v`
Expected: Task 2 + Task 3 全绿

- [ ] **Step 5: 用真实 seed 数据验证隔离效果（结构性验收，不是单测）**

```bash
cd backend && rm -f data/campus.db && DB_BACKEND=sqlite .venv/Scripts/python.exe ../scripts/seed_academic.py
```

在 `mcp_servers/academic` 下用 uv 跑一段临时核验（不入库，用完即弃）：

```bash
cd mcp_servers/academic && uv run python -c "
from guard import validate
from rewriter import rewrite
r = validate('SELECT course, term, score FROM v_grades ORDER BY term', 'sqlite')
print(rewrite(r.tree))"
```

Expected: 输出含 `(SELECT * FROM v_grades WHERE student_id = ?) AS v_grades`

- [ ] **Step 6: 提交**

```bash
git add mcp_servers/academic/rewriter.py mcp_servers/academic/tests/test_rewrite.py
git commit -m "feat(mcp-academic): 关系替换为带学号过滤的子查询，覆盖八种引用形态"
```

---

## Task 4: `run_sql` / `describe_schema` 与 MCP 挂载

**Files:**
- Create: `mcp_servers/academic/db.py`
- Create: `mcp_servers/academic/server.py`
- Create: `mcp_servers/academic/tests/test_server.py`
- Create: `backend/app/tools/composite.py`
- Modify: `backend/app/config.py`（加 `academic_server_dir`）
- Modify: `backend/app/tools/stdio_mcp.py`（`stdio_registry` 加 `env`）
- Modify: `backend/app/main.py`（双 registry 合并）
- Test: `backend/tests/test_tools.py`（追加 composite 用例）

**Interfaces:**
- Consumes: `validate`/`rewrite`/`to_mysql_placeholders`（Task 2/3）、既有 `stdio_registry(server_dir)`、`ToolRegistry` 协议
- Produces:
  - MCP 工具 `describe_schema() -> list[SchemaTable]`、`run_sql(sql: str, student_id: str) -> SqlResult`
  - `SqlResult = {ok, columns, rows, scoped_sql, refused_code, row_count, latency_ms}`（拒绝时 `ok=False` 且 `refused_code` 非空，**不抛异常**——抛异常会被 MCP 包成 `isError`，拿不到结构化拒绝码）
  - `stdio_registry(server_dir: Path, env: dict[str, str] | None = None)`
  - `CompositeRegistry(registries: list[ToolRegistry])`
  - Task 5 的 `list_tools()` 要看到含 `describe_schema`/`run_sql` 且 `run_sql.input_schema.properties` **含** `student_id`（剔除发生在 Task 5，别在本任务提前做）

- [ ] **Step 1: 写失败测试（执行与 schema 剔除的 server 侧事实）**

`mcp_servers/academic/tests/test_server.py`：

```python
import os

import pytest

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("SQLITE_PATH", "/tmp/s3-academic-test.db")


async def _seed_db() -> None:
    """建一个最小库，让 run_sql 有真行可查。"""
    import aiosqlite
    os.makedirs(os.path.dirname(os.environ["SQLITE_PATH"]), exist_ok=True)
    async with aiosqlite.connect(os.environ["SQLITE_PATH"]) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS enrollments (
                student_id TEXT, course_name TEXT, term TEXT, credits REAL,
                score REAL, grade_points REAL, teacher TEXT);
            CREATE VIEW IF NOT EXISTS v_grades AS
                SELECT student_id, course_name AS course, term, credits, score,
                       grade_points AS points, teacher FROM enrollments;
            DELETE FROM enrollments;
        """)
        await db.executemany(
            "INSERT INTO enrollments VALUES (?,?,?,?,?,?,?)",
            [("20230001", "高等数学（上）", "2025 秋", 5, 91, 4.1, "王建国"),
             ("20230007", "数据结构", "2026 春", 4, 93, 4.3, "李慧")])
        await db.commit()


async def test_describe_schema_任何地方都不出现student_id():
    await _seed_db()
    from server import describe_schema
    tables = await describe_schema()
    dumped = repr(tables)
    assert "student_id" not in dumped
    grades = next(t for t in tables if t.name == "v_grades")
    assert "course" in grades.columns and "score" in grades.columns


async def test_run_sql_只返回本人的行_A2场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT course, score FROM v_grades ORDER BY course",
                        student_id="20230001")
    assert res.ok is True
    assert [r[0] for r in res.rows] == ["高等数学（上）"]   # 林知远的行不出现
    assert "student_id = ?" in res.scoped_sql
    assert res.refused_code is None


async def test_run_sql_身份列拒绝且不执行_A3场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT * FROM v_grades WHERE student_id='20230007'",
                        student_id="20230001")
    assert res.ok is False
    assert res.refused_code == "identity_column"
    assert res.rows == []
    assert res.scoped_sql == ""          # 拒绝即不改写、不执行


async def test_run_sql_基表拒绝_A4场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT * FROM enrollments", student_id="20230001")
    assert res.ok is False and res.refused_code == "relation_not_whitelisted"


async def test_run_sql_多语句拒绝_A5场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT 1; DROP TABLE enrollments",
                        student_id="20230001")
    assert res.ok is False and res.refused_code == "multi_statement"


async def test_run_sql_耗时函数拒绝_A6场景():
    await _seed_db()
    from server import run_sql
    res = await run_sql(sql="SELECT SLEEP(30)", student_id="20230001")
    assert res.ok is False and res.refused_code == "cost_function"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd mcp_servers/academic && uv run pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: 写 db 执行层**

`mcp_servers/academic/db.py`：

```python
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
```

- [ ] **Step 4: 写 MCP server**

`mcp_servers/academic/server.py`：

```python
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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd mcp_servers/academic && uv run pytest -v`
Expected: Task 2 + 3 + 4 全绿

- [ ] **Step 6: 让子进程拿到数据库配置（关键接缝）**

`mcp_servers/navigation/pyproject.toml` 之外，**`stdio_registry` 传 `env=None` 时 MCP 只透传白名单环境变量**，`DB_BACKEND`/`SQLITE_PATH`/`MYSQL_*` 与 `.env` 里那些都进不去。改 `backend/app/tools/stdio_mcp.py`：

```python
@asynccontextmanager
async def stdio_registry(server_dir: Path, env: dict[str, str] | None = None):
    """lifespan 用：拉起 MCP 子进程，退出时随 AsyncExitStack 关闭。

    env 必须显式传给 academic：MCP 的 StdioServerParameters 在 env=None 时
    走白名单环境（只留 PATH/HOME 之类），DB_BACKEND 之类自定义变量传不进去。
    navigation 不连库，仍用默认。
    """
    async with AsyncExitStack() as stack:
        params = StdioServerParameters(
            command=sys.executable,
            args=["server.py"],
            cwd=str(server_dir.resolve()),
            env=env,
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        registry = StdioMcpRegistry(session)
        await registry.initialize()
        yield registry
```

`backend/app/config.py` 在 `navigation_server_dir` 行后加：

```python
    academic_server_dir: Path = Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "academic"
```

- [ ] **Step 7: 写 CompositeRegistry 并在 lifespan 挂两个 server**

`backend/app/tools/composite.py`：

```python
from typing import Any

from .base import ToolRegistry, ToolResult, ToolSpec


class CompositeRegistry(ToolRegistry):
    """多个 MCP 子进程按工具名分派。spec 的接入点写的是"server 清单加一条"，
    而每个 server 各是一个 session，所以这里做的是聚合而不是合并 session。
    """

    def __init__(self, registries: list[ToolRegistry]):
        self._regs = list(registries)

    async def list_tools(self) -> list[ToolSpec]:
        out: list[ToolSpec] = []
        for reg in self._regs:
            out.extend(await reg.list_tools())
        return out

    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult:
        for reg in self._regs:
            specs = await reg.list_tools()
            if any(s.name == name for s in specs):
                return await reg.call_tool(name, args, student_id=student_id)
        return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
```

`backend/app/main.py` 的 lifespan 把单 registry 换成两个（`stdio_registry` 的 `yield registry` 段）：

```python
    async with stdio_registry(settings.navigation_server_dir) as nav_reg, \
               stdio_registry(settings.academic_server_dir, env=_academic_env(settings)) as academic_reg:
        registry = CompositeRegistry([nav_reg, academic_reg])
        app.state.registry = registry
        logger.info("MCP tools ready: %s", [t.name for t in await registry.list_tools()])
        yield
```

在 `lifespan` 上方加（import 时补 `import os` 与 `from .tools.composite import CompositeRegistry`）：

```python
def _academic_env(settings) -> dict[str, str]:
    """显式传库配置给 academic 子进程——env=None 时 MCP 只透传白名单变量。"""
    return {
        **os.environ,
        "DB_BACKEND": settings.db_backend,
        "SQLITE_PATH": str(settings.sqlite_path),
        "MYSQL_HOST": settings.mysql_host,
        "MYSQL_PORT": str(settings.mysql_port),
        "MYSQL_USER": settings.mysql_user,
        "MYSQL_PASSWORD": settings.mysql_password,
        "MYSQL_DATABASE": settings.mysql_database,
    }
```

- [ ] **Step 8: 写 CompositeRegistry 单测**

追加到 `backend/tests/test_tools.py`：

```python
def test_CompositeRegistry_按工具名分派():
    import asyncio

    from app.tools.composite import CompositeRegistry
    from app.tools.inmemory import InMemoryRegistry

    nav = InMemoryRegistry({"resolve_page": {"spec": {
        "name": "resolve_page", "description": "d",
        "input_schema": {"type": "object", "properties": {"intent": {"type": "string"}},
                         "required": ["intent"]}},
        "fn": lambda intent: {"path": "/x"}}})
    acad = InMemoryRegistry({"run_sql": {"spec": {
        "name": "run_sql", "description": "d",
        "input_schema": {"type": "object",
                         "properties": {"sql": {"type": "string"}},
                         "required": ["sql"]}},
        "fn": lambda sql: {"rows": []}}})

    reg = CompositeRegistry([nav, acad])
    names = asyncio.run(reg.list_tools())
    assert {s.name for s in names} == {"resolve_page", "run_sql"}

    res = asyncio.run(reg.call_tool("run_sql", {"sql": "SELECT 1"}))
    assert res.ok and res.data == {"rows": []}
    unknown = asyncio.run(reg.call_tool("nope", {}))
    assert unknown.ok is False and "未知工具" in unknown.error


async def test_academic子进程真能被拉起并列出工具():
    """端到端：确认 env 透传与独立 uv 项目都对。跑不通说明 Task 4 Step 6 没做实。"""
    import os
    from pathlib import Path

    from app.config import Settings
    from app.tools.stdio_mcp import stdio_registry

    s = Settings(db_backend="sqlite")
    env = {**os.environ, "DB_BACKEND": "sqlite",
           "SQLITE_PATH": str(s.sqlite_path)}
    async with stdio_registry(Path("mcp_servers/academic"), env=env) as reg:
        names = {t.name for t in await reg.list_tools()}
    assert {"describe_schema", "run_sql"} <= names
```

- [ ] **Step 9: 跑测试确认通过并提交**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_tools.py -v`
Expected: 全绿（含新增 composite 与真子进程两条）

```bash
git add mcp_servers/academic/db.py mcp_servers/academic/server.py mcp_servers/academic/tests/test_server.py \
        backend/app/tools/composite.py backend/app/tools/stdio_mcp.py backend/app/config.py \
        backend/app/main.py backend/tests/test_tools.py
git commit -m "feat(mcp-academic): run_sql/describe_schema 上线，双 server 经 CompositeRegistry 挂载"
```

---

## Task 5: `TRUSTED_ARGS` —— 丢弃模型塞的，服务端注入真的

**Files:**
- Modify: `backend/app/tools/base.py`
- Modify: `backend/app/tools/stdio_mcp.py`（`call_tool` 签名 + schema 剔除）
- Modify: `backend/app/tools/inmemory.py`（同上）
- Modify: `backend/app/agent/nodes/tool_executor.py`（调用点传 `student_id`）
- Test: `backend/tests/test_tools.py`（追加）

**Interfaces:**
- Consumes: 既有 `ToolRegistry` 协议、`StdioMcpRegistry._specs`、`state["student_id"]`（Task 6 才建，本任务先用 `session_id` 的现值，见 Step 5）
- Produces:
  - `TRUSTED_ARGS: dict[str, set[str]] = {"run_sql": {"student_id"}}`
  - `with_trusted_args(name, args, student_id) -> dict`：剔除受信键后按 `student_id` 回填
  - `strip_trusted(name, schema) -> dict`：从 `input_schema` 删掉受信属性与 `required` 项
  - 协议变更为 `async def call_tool(self, name: str, args: dict[str, Any], student_id: str | None = None) -> ToolResult`（**三个实现 + 所有调用点同步改**）
  - 效果：`list_tools()` 给模型的 `run_sql` schema **不含** `student_id`；模型即便硬塞，`with_trusted_args` 先丢弃、再写入会话学号

- [ ] **Step 1: 写失败测试（一面丢弃、一面拒绝、一面剔除）**

追加到 `backend/tests/test_tools.py`：

```python
def test_TRUSTED_ARGS_丢弃模型塞的并注入会话学号():
    from app.tools.base import TRUSTED_ARGS, with_trusted_args

    assert TRUSTED_ARGS == {"run_sql": {"student_id"}}
    out = with_trusted_args("run_sql",
                            {"sql": "SELECT 1", "student_id": "20230007"},
                            student_id="20230001")
    assert out == {"sql": "SELECT 1", "student_id": "20230001"}  # 塞的被丢弃


def test_TRUSTED_ARGS_无student_id会话时不注入_让必填校验去拦():
    from app.tools.base import with_trusted_args

    out = with_trusted_args("run_sql", {"sql": "SELECT 1"}, student_id=None)
    assert out == {"sql": "SELECT 1"}
    assert "student_id" not in out


def test_TRUSTED_ARGS_非受信工具原样透传():
    from app.tools.base import with_trusted_args

    args = {"intent": "查成绩"}
    assert with_trusted_args("resolve_page", args, student_id="20230001") is args


def test_strip_trusted_从schema里删掉student_id与required项():
    from app.tools.base import strip_trusted

    schema = {
        "type": "object",
        "properties": {"sql": {"type": "string"},
                       "student_id": {"type": "string"}},
        "required": ["sql", "student_id"],
    }
    out = strip_trusted("run_sql", schema)
    assert "student_id" not in out["properties"]
    assert out["required"] == ["sql"]
    assert "student_id" not in str(out)


def test_strip_trusted_不动非受信工具的schema():
    from app.tools.base import strip_trusted

    schema = {"type": "object", "properties": {"intent": {"type": "string"}},
              "required": ["intent"]}
    assert strip_trusted("resolve_page", schema) == schema


async def test_stdio_registry_给模型的run_sql_schema里没有student_id():
    """spec 7.4：描述里留着这列与模型看得见这列是两件事，后者会教模型拿它过滤。"""
    from pathlib import Path

    from app.config import Settings
    from app.tools.stdio_mcp import stdio_registry

    s = Settings(db_backend="sqlite")
    import os
    env = {**os.environ, "DB_BACKEND": "sqlite", "SQLITE_PATH": str(s.sqlite_path)}
    async with stdio_registry(Path("mcp_servers/academic"), env=env) as reg:
        spec = next(t for t in await reg.list_tools() if t.name == "run_sql")
    assert "student_id" not in str(spec.input_schema)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'with_trusted_args'`

- [ ] **Step 3: 实现 base 层的三件工具函数并改协议**

`backend/app/tools/base.py` 在 `validate_args` 上方加，并把 `ToolRegistry` 协议的第二个方法改签名：

```python
TRUSTED_ARGS: dict[str, set[str]] = {"run_sql": {"student_id"}}


def with_trusted_args(name: str, args: dict[str, Any],
                      student_id: str | None) -> dict[str, Any]:
    """一面丢弃、一面注入（spec 7.4）：模型塞的同名字段先被剔掉，
    再由服务端按会话写入。两面缺一个就有洞。"""
    trusted = TRUSTED_ARGS.get(name)
    if not trusted:
        return args
    out = {k: v for k, v in args.items() if k not in trusted}
    if student_id is not None:
        out["student_id"] = student_id
    return out


def strip_trusted(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """给模型看的 schema 必须剔除受信列，否则等于教它"这里有身份列"。"""
    trusted = TRUSTED_ARGS.get(name)
    props = schema.get("properties")
    if not trusted or not props:
        return schema
    out = dict(schema)
    out["properties"] = {k: v for k, v in props.items() if k not in trusted}
    if "required" in out:
        out["required"] = [r for r in out["required"] if r not in trusted]
    return out


class ToolRegistry(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult: ...
```

- [ ] **Step 4: 三个实现与调用点同步改签名**

`backend/app/tools/stdio_mcp.py`：`initialize()` 里建 spec 时套 `strip_trusted`，`call_tool` 加参数与注入：

```python
    async def initialize(self) -> None:
        await self._session.initialize()
        listed = await self._session.list_tools()
        self._specs = [
            ToolSpec(name=t.name, description=t.description or "",
                     input_schema=strip_trusted(t.name, t.input_schema or {}))
            for t in listed.tools
        ]

    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult:
        spec = next((s for s in self._specs if s.name == name), None)
        if spec is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", latency_ms=0)
        args = with_trusted_args(name, args, student_id)   # 先丢弃后注入
        ok, err = validate_args(spec.input_schema, args)
        if not ok:
            return ToolResult(ok=False, error=err, latency_ms=0)
        # …… 以下 invoke 部分原样不动
```

（`from .base import ...` 那行补 `strip_trusted, with_trusted_args`。）

`backend/app/tools/inmemory.py` 的 `call_tool` 同样加 `student_id: str | None = None` 与 `args = with_trusted_args(name, args, student_id)` 一行，import 同步补。

`backend/app/tools/composite.py` 的 `call_tool` 已在 Task 4 Step 7 写成带 `student_id`，无需改。

`backend/app/agent/nodes/tool_executor.py` 调用点传学号：

```python
    result = await registry.call_tool(name, state["tool_args"],
                                      student_id=state["session_id"])
```

（Task 6 会把 `session_id` 改名 `student_id`，届时这行跟着改成 `state["student_id"]`——**本任务先按现有字段名写，别在两个任务里同时改两个名字**。）

- [ ] **Step 5: 全量回归确认签名改动没漏调用点**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: 全绿。若出现 `call_tool() got an unexpected keyword argument 'student_id'`，说明某个实现或测试 fixture 漏改签名——按报错逐个补，不许改断言迁就。

- [ ] **Step 6: 提交**

```bash
git add backend/app/tools backend/app/agent/nodes/tool_executor.py backend/tests/test_tools.py
git commit -m "feat(tools): TRUSTED_ARGS 丢弃+注入两面防线，schema 向模型隐藏身份列"
```

---

## Task 6: 图三态分流与 `sql_executor` 节点

**Files:**
- Modify: `backend/app/agent/state.py`
- Modify: `backend/app/agent/nodes/router.py`
- Create: `backend/app/agent/nodes/sql_executor.py`
- Modify: `backend/app/agent/graph.py`
- Modify: `backend/app/llm/base.py`、`backend/app/llm/fake.py`、`backend/app/llm/openai_compat.py`（加 `generate_sql`）
- Modify: `backend/app/api/chat.py`（initial_state 字段名）
- Test: `backend/tests/test_graph.py`（改名 + 三态新增）

**Interfaces:**
- Consumes: `TRUSTED_ARGS`/`call_tool(student_id=…)`（Task 5）、`CompositeRegistry` 里的 `describe_schema`/`run_sql`（Task 4）
- Produces:
  - `AgentState`：删 `session_id`、加 `student_id: str`、加 `history: list[dict[str,str]]`、加 `route: Literal["navigate","query","answer"] | None`、`needs_clarification: bool`、`clarification: dict | None`、`sql: dict | None`；**`intent` 保留为用户原话片段**（见计划开头偏离 1）
  - `LLMProvider.generate_sql(user_input: str, schema_json: str) -> str`
  - 图边：`router --route--> {navigate: tool_executor, query: sql_executor, answer: generator}`
  - `sql_executor_node(state, registry, provider, writer)`；spec 7.3 规则 3（query 且同时也命中跳转）在**本节点内先补跑 `resolve_page`**，让 `tool_results["resolve_page"]` 就位，generator 的 nav_card 逻辑一字不改

- [ ] **Step 1: 改 state 与改名（先做机械改动）**

`backend/app/agent/state.py` 整文件替换：

```python
import operator
from typing import Annotated, Any, Literal, TypedDict


class AgentState(TypedDict):
    user_input: str
    student_id: str                 # 只从会话来（原 session_id 装的就是学号，改名归位）
    history: list[dict[str, str]]   # 服务端回读，前端只发当前这句
    intent: str | None              # 用户原话片段，generator 拿它拼 nav_card 文案
    route: Literal["navigate", "query", "answer"] | None   # spec 7.3 三态
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_results: dict[str, Any]
    answer: str
    nav_card: dict[str, Any] | None
    needs_clarification: bool
    clarification: dict[str, Any] | None
    sql: dict[str, Any] | None      # {raw, scoped, columns, rows, row_count, refused_code}
    steps: Annotated[list[str], operator.add]
    error: str | None
```

同步改名的调用点（三处，一次改完）：`backend/app/api/chat.py` 的 `initial_state` 里 `"session_id": student.student_id` → `"student_id": student.student_id`，并补 `"history": history`、`"route": None`、`"needs_clarification": False`、`"clarification": None`、`"sql": None`；`backend/tests/test_graph.py` 的 `run_graph` 里 `"session_id": "s-test"` → `"student_id": "20230001"` 并补同样五个键；`backend/app/agent/nodes/tool_executor.py` 里 `state["session_id"]` → `state["student_id"]`。

- [ ] **Step 2: 写失败测试（三态 + sql_executor + 澄清）**

追加到 `backend/tests/test_graph.py`：

```python
ACADEMIC_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}


@pytest.fixture
def academic_registry():
    async def fake_run_sql(sql: str):
        if "student_id=" in sql.replace(" ", ""):
            return {"ok": False, "refused_code": "identity_column",
                    "scoped_sql": "", "rows": [], "columns": [], "row_count": 0}
        # 跨两个学期 → 触发澄清；若 SQL 里已被限定学期，则只剩该学期的行
        rows = [["高等数学（上）", "2025 秋"], ["数据结构", "2026 春"]]
        for term in ("2025 秋", "2026 春"):
            if f"term = '{term}'" in sql:
                rows = [r for r in rows if r[1] == term]
        return {"ok": True, "scoped_sql": sql, "columns": ["course", "term"],
                "rows": rows, "row_count": len(rows), "refused_code": None}

    return InMemoryRegistry({
        "resolve_page": {"spec": {"name": "resolve_page", "description": "d",
                                  "input_schema": RESOLVE_SCHEMA},
                         "fn": lambda intent: {"path": "/academic/grades",
                                               "title": "成绩查询",
                                               "capabilities": ["查成绩"]}},
        "describe_schema": {"spec": {"name": "describe_schema", "description": "d",
                                     "input_schema": {"type": "object", "properties": {}}},
                            "fn": lambda: [{"name": "v_grades", "columns": ["course", "term"]}]},
        "run_sql": {"spec": {"name": "run_sql", "description": "d",
                             "input_schema": ACADEMIC_SCHEMA},
                    "fn": fake_run_sql},
    })


class Test三态分流:
    async def test_取数意图走query出数据而非跳转卡(self, academic_registry):
        graph = build_graph(FakeProvider(), academic_registry)
        collected, final = await run_graph(graph, "我这学期的高数成绩是多少")
        assert final["route"] == "query"
        assert final["steps"] == ["router", "sql_executor", "generator"]
        assert collected["nav_card"] is None          # 没跑 resolve_page
        assert final["sql"] and final["sql"]["row_count"] == 2

    async def test_纯跳转意图仍走navigate(self, registry):
        graph = build_graph(FakeProvider(), registry)
        _, final = await run_graph(graph, "这学期上什么课")
        assert final["route"] == "navigate"
        assert final["steps"] == ["router", "tool_executor", "generator"]

    async def test_两者都像_query优先且跳转卡仍出(self, academic_registry):
        """spec 7.3 规则 3：query 胜出，但两个 executor 结果可共存。"""
        graph = build_graph(FakeProvider(), academic_registry)
        collected, final = await run_graph(graph, "我成绩怎么样，顺便去成绩页看看")
        assert final["route"] == "query"
        assert final["tool_results"].get("resolve_page")   # sql_executor 先补跑了
        assert collected["nav_card"]["path"] == "/academic/grades"

    async def test_都不像走answer(self, registry):
        graph = build_graph(FakeProvider(), registry)
        _, final = await run_graph(graph, "今天天气怎么样")
        assert final["route"] == "answer"
        assert final["steps"] == ["router", "generator"]


class Test澄清:
    async def test_跨学期且未指定学期_出clarify选项(self, academic_registry):
        graph = build_graph(FakeProvider(), academic_registry)
        collected, final = await run_graph(graph, "我的数据结构成绩")
        assert final["needs_clarification"] is True
        assert [o["label"] for o in final["clarification"]["options"]] == ["2025 秋", "2026 春"]
        clarify_events = [c for c in collected["custom"] if c[0] == "clarify"]
        assert clarify_events and clarify_events[0][1]["question"]

    async def test_点选项后第二轮收敛不再追问_spec9_2两轮闭环(self, academic_registry):
        """spec 9.2 集成测点名要的"澄清两轮闭环"：
        第一轮跨学期 → 出选项；用户点"2025 秋"后第二轮只剩该学期，不再追问。
        任何一轮 needs_clarification 仍为 True 都算没收敛。"""
        graph = build_graph(FakeProvider(), academic_registry)
        _, first = await run_graph(graph, "我的数据结构成绩")
        assert first["needs_clarification"] is True
        labels = [o["label"] for o in first["clarification"]["options"]]

        _, second = await run_graph(graph, f"{labels[0]} 我的数据结构成绩")
        assert second["needs_clarification"] is False
        assert second["clarification"] is None
        assert [r[1] for r in second["sql"]["rows"]] == ["2025 秋"]   # 只剩该学期
        assert second["error"] is None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_graph.py -v`
Expected: FAIL — `KeyError: 'route'`（或 import 失败，因为 `sql_executor_node` 还不存在）

- [ ] **Step 4: 给 provider 加 `generate_sql`**

`backend/app/llm/base.py` 的 `LLMProvider` 加一行：

```python
    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        """Text-to-SQL：拿语义 schema 把自然语言翻成只读 SQL。
        生成的 SQL 必须只引用白名单视图、不得含身份列——guard 会兜底拒绝。"""
        ...
```

`backend/app/llm/fake.py` 加（规则只写"取数"一类最小判定，spec 12 的告警就是防它膨胀成第二套假 NLU）：

```python
_SQL_KEYWORDS = {"高数": "高等数学", "高等数学": "高等数学", "数据结构": "数据结构"}
_TERMS = ("2025 秋", "2026 春")   # 只这一条判定：用户点选项后文本里带学期 → 收窄


    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        """规则只写"取数"这一类最小判定（spec 12 警告过别膨胀成第二套假 NLU）。
        学期那一句是澄清闭环的必需品：没有它，第二轮仍返回跨学期结果，
        澄清会无限追问——spec 9.2 的"两轮收敛"测的就是这里。"""
        kw = next((v for k, v in _SQL_KEYWORDS.items() if k in user_input), None)
        term = next((t for t in _TERMS if t in user_input), None)
        sql = "SELECT course, term, score FROM v_grades WHERE 1=1"
        if kw:
            sql += f" AND course LIKE '%{kw}%'"
        if term:
            sql += f" AND term = '{term}'"
        return sql + " ORDER BY term"
```

`backend/app/llm/openai_compat.py` 加：

```python
SQL_SYSTEM = (
    "你是 SQL 生成器。只许 SELECT，只许引用 v_grades/v_schedule/v_makeup/v_loans "
    "四个视图，绝不出现 student_id 列，绝不写多条语句。"
    "输出只含 SQL 文本本身，不要解释、不要 markdown 代码块。"
)


    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": SQL_SYSTEM},
                      {"role": "user", "content": f"语义视图结构：{schema_json}\n\n用户问题：{user_input}"}],
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("sql"):
                text = text[3:]
        return text.strip()
```

- [ ] **Step 5: 写 `sql_executor` 节点**

`backend/app/agent/nodes/sql_executor.py`：

```python
import json
import logging

from langgraph.types import StreamWriter

from ...llm.base import LLMProvider
from ...tools.base import ToolRegistry

logger = logging.getLogger("campus-agent.sql_executor")


async def _emit(writer: StreamWriter, result) -> None:
    writer(("tool_call", {"name": result.get("_name", "run_sql"),
                          "args": {}, "ok": True, "error": None,
                          "latency_ms": 0}))


async def sql_executor_node(state, registry: ToolRegistry,
                            provider: LLMProvider, writer: StreamWriter):
    """spec 7.3：describe_schema → 模型写 SQL → run_sql → 澄清判定。
    规则 3（query 与 navigate 并存）在这里先补跑 resolve_page，
    让 tool_results 就位，generator 的 nav_card 逻辑一行都不用改。
    """
    tool_results: dict = dict(state.get("tool_results") or {})

    if state.get("tool_name") == "resolve_page":
        nav = await registry.call_tool("resolve_page", state["tool_args"],
                                       student_id=state["student_id"])
        tool_results["resolve_page"] = nav.model_dump()
        writer(("tool_call", {"name": "resolve_page", "args": state["tool_args"],
                              "ok": nav.ok, "error": nav.error,
                              "latency_ms": nav.latency_ms}))

    schema_res = await registry.call_tool("describe_schema", {})
    schema = schema_res.data if schema_res.ok else []

    raw_sql = await provider.generate_sql(state["user_input"], json.dumps(schema, ensure_ascii=False))
    result = await registry.call_tool("run_sql", {"sql": raw_sql},
                                      student_id=state["student_id"])
    payload = result.data if isinstance(result.data, dict) else {}
    if isinstance(result.data, str):
        payload = json.loads(result.data)

    writer(("tool_call", {"name": "run_sql", "args": {"sql": raw_sql},
                          "ok": bool(payload.get("ok")),
                          "error": payload.get("refused_message"),
                          "latency_ms": result.latency_ms}))

    scoped = payload.get("scoped_sql", "")
    sql_state = {"raw": raw_sql, "scoped": scoped,
                 "columns": payload.get("columns", []),
                 "rows": payload.get("rows", []),
                 "row_count": payload.get("row_count", 0),
                 "refused_code": payload.get("refused_code")}

    error = None
    if not payload.get("ok"):
        error = payload.get("refused_message") or payload.get("refused_code") or "查询未执行"
    else:
        writer(("sql_result", {"sql": scoped,
                               "columns": sql_state["columns"],
                               "rows": sql_state["rows"],
                               "row_count": sql_state["row_count"],
                               "truncated": False}))
        clarify = _maybe_clarify(payload, state["user_input"])
        if clarify:
            return {"tool_results": tool_results, "sql": sql_state,
                    "needs_clarification": True, "clarification": clarify,
                    "error": None, "steps": ["sql_executor"]}

    return {"tool_results": tool_results, "sql": sql_state,
            "needs_clarification": False, "clarification": None,
            "error": error, "steps": ["sql_executor"]}


def _maybe_clarify(payload: dict, user_input: str) -> dict | None:
    """结果跨多个学期且用户没指定 → 要求澄清（spec 7.3）。"""
    columns = payload.get("columns") or []
    if "term" not in columns:
        return None
    idx = columns.index("term")
    terms = sorted({row[idx] for row in (payload.get("rows") or []) if row[idx]})
    if len(terms) <= 1:
        return None
    if any(t in user_input for t in terms):   # 用户已指定，无需再问
        return None
    return {"question": "你要查哪个学期？",
            "options": [{"label": t} for t in terms]}
```

- [ ] **Step 6: 改 router 三态与 graph 边**

`backend/app/agent/nodes/router.py` 在 `return` 前加三态判定（保留原有未知工具拦截）：

```python
_QUERY_HINTS = ("成绩", "分数", "绩点", "课表", "上课", "在借", "借书",
                "还书", "补考", "重修", "多少", "平均")


def _route_of(user_input: str, tool_name: str | None) -> str:
    """spec 7.3：取数优先于跳转（规则 3），都不像才 answer。"""
    if any(h in user_input for h in _QUERY_HINTS):
        return "query"
    if tool_name == "resolve_page":
        return "navigate"
    return "answer"
```

router 的两个 return 各加一行 `"route": _route_of(state["user_input"], <tool_name>)`（未知工具那支传 `None` 以走 answer/fallback——实际传 `decision.tool_name` 即可，被拦下后仍会因不在 `known` 里而走 error 分支）。

`backend/app/agent/graph.py` 整文件替换：

```python
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from ..llm.base import LLMProvider
from ..tools.base import ToolRegistry
from .nodes.generator import generator_node
from .nodes.router import router_node
from .nodes.sql_executor import sql_executor_node
from .nodes.tool_executor import tool_executor_node
from .state import AgentState


def build_graph(provider: LLMProvider, registry: ToolRegistry):
    async def router(state: AgentState):
        return await router_node(state, provider, registry)

    async def tool_executor(state: AgentState, writer: StreamWriter):
        return await tool_executor_node(state, registry, writer)

    async def sql_executor(state: AgentState, writer: StreamWriter):
        return await sql_executor_node(state, registry, provider, writer)

    async def generator(state: AgentState, writer: StreamWriter):
        return await generator_node(state, provider, writer)

    workflow = StateGraph(AgentState)
    workflow.add_node("router", router)
    workflow.add_node("tool_executor", tool_executor)
    workflow.add_node("sql_executor", sql_executor)
    workflow.add_node("generator", generator)
    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {"navigate": "tool_executor", "query": "sql_executor",
         "answer": "generator", None: "generator"},
    )
    workflow.add_edge("tool_executor", "generator")
    workflow.add_edge("sql_executor", "generator")
    workflow.add_edge("generator", END)
    return workflow.compile().with_config(recursion_limit=8)
```

- [ ] **Step 7: generator 出澄清话（spec 7.3：只出 clarify、不出 token）**

`backend/app/agent/nodes/generator.py` 在 `stream_state = {**state, "nav_card": nav_card}` 之后插入：

```python
    if state.get("needs_clarification") and state.get("clarification"):
        clarify = state["clarification"]
        writer(("clarify", clarify))
        # 只出选项条，不出 token：同一句话既打字又给按钮是重复信号
        return {"answer": clarify["question"], "nav_card": nav_card,
                "steps": ["generator"]}
```

- [ ] **Step 8: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_graph.py -v`
Expected: 三态 4 条 + 澄清 1 条 + 既有 happy path / guards / SSE 全绿

- [ ] **Step 9: 全量回归 + 提交**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: 全绿（既有 `test_chat_auth`/`test_openai_compat_router` 若因 `generate_sql` 新方法失败，是 Protocol 突变——补上实现或改用 `FakeProvider` 子类，**不许删断言**）

```bash
git add backend/app/agent backend/app/llm backend/app/api/chat.py backend/tests/test_graph.py
git commit -m "feat(agent): router 三态分流 + sql_executor 查数节点与跨学期澄清"
```

---

## Task 7: `history` 服务端回读

**Files:**
- Modify: `backend/app/config.py`（加 `history_limit`）
- Modify: `backend/app/db/repository.py`（加 `SqlQueryRecord`、`recent_history`、`record_exchange(sql=…)`）
- Modify: `backend/app/api/chat.py`（注入 `history`）
- Test: `backend/tests/test_history.py`

**Interfaces:**
- Consumes: 既有 `conversations`/`messages` 表与 `DbConversationRepository`
- Produces:
  - `Settings.history_limit: int = 6`（spec 12：6 轮上限 + 每条截 200 字，防 token 撑大）
  - `async def recent_history(self, *, student_id: str, limit: int) -> list[dict[str, str]]`，元素为 `{"role": "user"|"assistant", "content": str}`，**取该学生最近 limit 条消息（跨会话联表——Ruling Q 回填：`record_exchange` 每轮 INSERT 新 conversation 行，按"最近一条会话"过滤只会剩上一轮 2 条，spec 12 的 6 轮上限永不生效）**
  - `SqlQueryRecord(sql_raw, sql_scoped, refused_code, row_count, latency_ms)`（Task 8 消费）
  - `record_exchange(*, student_id, user_text, assistant_text, tool_call, steps, sql: SqlQueryRecord | None = None) -> int | None`（向后兼容：不传 `sql` 的既有调用与测试不受影响）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_history.py`：

```python
from app.db.migrations import init_sqlite
from app.db.repository import build_repository


async def _seed_conversations(db, repo):
    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230001','周晓楠','x')")
    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230002','陈默','x')")
    # 本人第一条会话（两轮）
    await repo.record_exchange(student_id="20230001", user_text="第一问",
                               assistant_text="第一答", tool_call=None, steps=[])
    # 别人的会话（不得被读到）
    await repo.record_exchange(student_id="20230002", user_text="别人的问",
                               assistant_text="别人的答", tool_call=None, steps=[])
    # 本人最新一条会话（三轮）
    for i in range(2, 5):
        await repo.record_exchange(student_id="20230001",
                                   user_text=f"第{i}问", assistant_text=f"第{i}答",
                                   tool_call=None, steps=[])


async def test_history_取本人最近limit条消息_跨会话且排除他人(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)
    await _seed_conversations(db, repo)

    history = await repo.recent_history(student_id="20230001", limit=6)
    contents = [h["content"] for h in history]
    assert "别人的问" not in contents            # 跨用户隔离
    assert "第一问" not in contents              # 本人更早的消息被 limit 截掉
    assert contents == ["第2问", "第2答", "第3问", "第3答", "第4问", "第4答"]
    assert all(h["role"] in ("user", "assistant") for h in history)


async def test_history_不超limit且每条截到200字(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)
    await db.execute("INSERT INTO students (student_id, name, password_hash)"
                     " VALUES ('20230001','周晓楠','x')")
    for i in range(8):
        await repo.record_exchange(student_id="20230001",
                                   user_text=f"{i}问" + "长" * 500,
                                   assistant_text=f"{i}答" + "长" * 500,
                                   tool_call=None, steps=[])

    history = await repo.recent_history(student_id="20230001", limit=6)
    assert len(history) == 6                       # 6 条消息（3 轮）封顶
    assert all(len(h["content"]) <= 200 for h in history)
    # 最新的在末尾
    assert history[-1]["content"].startswith("7答")


async def test_history_无人对话时返回空(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    repo = build_repository(db)
    assert await repo.recent_history(student_id="20230001", limit=6) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_history.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'recent_history'`

- [ ] **Step 3: 实现**

`backend/app/config.py` 在 `session_ttl_seconds` 行后加：

```python
    history_limit: int = 6   # spec 12：6 轮上限，每条另截 200 字
```

`backend/app/db/repository.py` 加（import 处补 `from typing import Protocol` 已有，`BaseModel` 已有）：

```python
class SqlQueryRecord(BaseModel):
    sql_raw: str
    sql_scoped: str = ""
    refused_code: str | None = None
    row_count: int = 0
    latency_ms: int = 0
```

`ConversationRepository` 协议与 `DbConversationRepository` 各加一个方法（协议里追加一行签名）：

```python
    async def recent_history(self, *, student_id: str,
                             limit: int) -> list[dict[str, str]]:
        """读该学生最近 limit 条消息（跨会话），按时间升序，每条截 200 字。

        不看客户端传来的任何会话 id——历史回读的身份只来自会话（spec 5.1 要点）。
        record_exchange 每次 INSERT 新 conversation 行，一次对话=一个 conversation，
        所以按"最近一条会话"过滤只会剩上一轮 2 条，spec 12 的 6 轮上限用不上；
        必须跨会话取本人最近 limit 条（Ruling Q 回填）。
        """
        rows = await self._db.fetch_all(
            "SELECT m.role, m.content FROM messages m"
            " JOIN conversations c ON c.id = m.conversation_id"
            " WHERE c.student_id = ?"
            " ORDER BY m.id DESC LIMIT ?", (student_id, limit))
        rows.reverse()   # 取的是最近 limit 条，要翻回时间升序给模型读
        return [{"role": r["role"], "content": str(r["content"])[:200]} for r in rows]
```

`record_exchange` 签名加 `sql: SqlQueryRecord | None = None`，并在 `if tool_call is not None:` 块之后加：

```python
        if sql is not None:
            await self._db.execute(
                """INSERT INTO sql_queries
                   (conversation_id, student_id, sql_raw, sql_scoped,
                    refused_code, row_count, latency_ms)
                   VALUES (?,?,?,?,?,?,?)""",
                (conv_id, student_id, sql.sql_raw, sql.sql_scoped,
                 sql.refused_code, int(sql.row_count), int(sql.latency_ms)))
```

（`SqlQueryRecord` 定义在 `ToolCallRecord` 下方即可。）

- [ ] **Step 4: chat 注入 history（在落库之前读，本轮消息还没进库）**

`backend/app/api/chat.py` 的 `initial_state` 上方加，并把它写进 `initial_state`：

```python
    settings = req.app.state.settings
    history = await repository.recent_history(
        student_id=student.student_id, limit=settings.history_limit)
```

`initial_state` 里补 `"history": history`（其余键已在 Task 6 Step 1 补齐）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_history.py -v`
Expected: 3 passed

- [ ] **Step 6: 让 provider 真用上 history（接线，不做提示词精修）**

`backend/app/llm/openai_compat.py` 的 `stream_answer` 把历史并进 messages：

```python
        messages = [{"role": "system", "content": ANSWER_SYSTEM}]
        for h in (state.get("history") or []):
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user",
                         "content": f"用户问: {user_input}{tool_note}"})
```

（替换原 `messages = [system, user]` 那三行；`FakeProvider` 不读 history，集成测只断言 state 里有值即可——规则式 provider 读历史只会变成第二套假 NLU，spec 12 已经警告过。）

- [ ] **Step 7: 全量回归 + 提交**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: 全绿

```bash
git add backend/app/config.py backend/app/db/repository.py backend/app/api/chat.py \
        backend/app/llm/openai_compat.py backend/tests/test_history.py
git commit -m "feat(history): 服务端回读本会话最近 6 轮，身份只来自会话"
```

---

## Task 8: `sql_queries` 落库、`sql_refused` 事件与全链路接线

**Files:**
- Modify: `backend/app/api/chat.py`（把 `state["sql"]` 落库 + 拒绝时发 `error` 事件）
- Test: `backend/tests/test_chat_auth.py`（追加）

**Interfaces:**
- Consumes: `SqlQueryRecord`（Task 7）、`state["sql"]`（Task 6）、`repository.record_exchange(sql=…)`
- Produces: 每次查数都在 `sql_queries` 留一行——**成功与拒绝都留**，A1 的验收要看 `sql_scoped` 含 `student_id = ?`，A3/A4/A5 要看 `refused_code`；拒绝时前端额外收到 `error{code:"sql_refused"}`（计划开头偏离 2）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_chat_auth.py`。该文件既有 fixture 是 `env`（返回 `(app, path)`）、helper 是 `login(client)`（登 20230002），但它只挂了 `resolve_page`，查不了数——所以本任务**另加一个带 academic 工具的 fixture**，照 `env` 的形状写，不复制登录逻辑：

```python
@pytest.fixture
def sql_env(tmp_path):
    """带 describe_schema/run_sql 的最小链路。
    这里用 InMemory 假 run_sql 而不是真子进程——本任务只断言
    "state['sql'] 被落库、拒绝时发 sql_refused 事件"这两条接线；
    真 academic 子进程的越权语义归 Task 10。"""
    path = tmp_path / "campus.db"

    async def setup():
        db = await init_sqlite(path)
        await seed_students(db)
        return db

    db = asyncio.run(setup())

    async def fake_run_sql(sql: str):
        if "student_id='20230007'" in sql:
            return {"ok": False, "refused_code": "identity_column",
                    "refused_message": "无需指定身份，系统已按你的账号过滤",
                    "scoped_sql": "", "columns": [], "rows": [],
                    "row_count": 0, "latency_ms": 1}
        return {"ok": True, "refused_code": None, "refused_message": None,
                "scoped_sql": "SELECT course FROM (SELECT * FROM v_grades"
                              " WHERE student_id = ?) AS v_grades",
                "columns": ["course"], "rows": [["高等数学（上）"]],
                "row_count": 1, "latency_ms": 1}

    async def fake_describe():
        return [{"name": "v_grades", "columns": ["course", "term"],
                 "description": "成绩视图"}]

    app = FastAPI()
    app.state.settings = Settings()
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.provider = FakeProvider()
    app.state.repository = build_repository(db)
    app.state.registry = InMemoryRegistry({
        "describe_schema": {
            "spec": {"name": "describe_schema", "description": "d",
                     "input_schema": {"type": "object", "properties": {}}},
            "fn": fake_describe,
        },
        "run_sql": {
            "spec": {"name": "run_sql", "description": "d",
                     "input_schema": {"type": "object",
                                      "properties": {"sql": {"type": "string"}},
                                      "required": ["sql"]}},
            "fn": fake_run_sql,
        },
    })
    app.include_router(auth_router)
    app.include_router(chat_router)
    return app, path


def test_查数成功把scoped_sql落进sql_queries(sql_env):
    """A1 的落库半边：scoped 必须能看到 student_id = ?——
    这是"改写真的发生了"的证据，光看返回行数看不出来。"""
    import asyncio
    import json  # noqa: F401  （与本文件其它测试的局部 import 风格一致）

    import aiosqlite

    app, path = sql_env
    with TestClient(app) as c:
        login(c)
        text = c.post("/chat", json={"message": "我的高数成绩"}).text
    assert "event: sql_result" in text

    async def read():
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT sql_raw, sql_scoped, refused_code, row_count"
                " FROM sql_queries")
            return await cur.fetchall()

    rows = asyncio.run(read())
    assert len(rows) == 1
    sql_raw, sql_scoped, refused_code, row_count = rows[0]
    assert "v_grades" in sql_raw                    # 记的是模型原文
    assert "student_id = ?" in sql_scoped           # 记的是改写后文本
    assert refused_code is None
    assert row_count == 1


def test_拒绝时发sql_refused错误事件(sql_env):
    import json

    app, path = sql_env

    class RefusingProvider(FakeProvider):
        async def generate_sql(self, user_input: str, schema_json: str) -> str:
            return "SELECT * FROM v_grades WHERE student_id='20230007'"

    app.state.provider = RefusingProvider()
    with TestClient(app) as c:
        login(c)
        text = c.post("/chat", json={"message": "陈默的高数成绩"}).text

    # 把 SSE 的 event/data 成对解出来，别靠子串猜
    lines = [ln for ln in text.splitlines() if ln]
    events = []
    for i, ln in enumerate(lines):
        if ln.startswith("event: ") and i + 1 < len(lines) \
                and lines[i + 1].startswith("data: "):
            events.append((ln[7:], json.loads(lines[i + 1][6:])))
    assert [d["code"] for e, d in events if e == "error"] == ["sql_refused"]

    import asyncio

    import aiosqlite

    async def read():
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT refused_code FROM sql_queries")
            return await cur.fetchall()

    # 拒绝也留痕，否则 A3/A4/A5 无从复盘
    assert asyncio.run(read()) == [("identity_column",)]
```

> `import asyncio` / `import aiosqlite` 是该文件既有的局部 import 习惯（见 `test_登录后对话落库带上该学号`），不要顺手提到模块顶——那会连带动别人的 import 排序，扩大 diff。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chat_auth.py -v`
Expected: 新增两条 FAIL（`sql_queries` 里没有行 / 没有 `sql_refused` 事件）

- [ ] **Step 3: 实现落库与事件**

`backend/app/api/chat.py` 的 `persist()` 里，`record_exchange` 调用补 `sql=`：

```python
                sql_state = state.get("sql")
                sql_record = None
                if sql_state:
                    sql_record = SqlQueryRecord(
                        sql_raw=sql_state.get("raw", ""),
                        sql_scoped=sql_state.get("scoped", ""),
                        refused_code=sql_state.get("refused_code"),
                        row_count=int(sql_state.get("row_count") or 0),
                        latency_ms=0,
                    )
                conversation_id = await repository.record_exchange(
                    student_id=student.student_id,
                    user_text=request.message,
                    assistant_text=state.get("answer", ""),
                    tool_call=build_record(state),
                    steps=state.get("steps", []),
                    sql=sql_record,
                )
```

（import 处补 `from ..db.repository import SqlQueryRecord, ToolCallRecord`。）

拒绝事件在 `stream()` 的 custom 分支后追加——注意 `sql_executor` 已把 `error` 写进 state，这里借 `values` 模式发一次：

```python
                else:
                    final_state = payload
            # 拒绝是"查了但不让查"，不是链路故障：先出 generator 的人话，
            # 再补一条可标红的错误事件（spec 4.3 + 7.2 两条都满足）
            sql_state = (final_state or {}).get("sql") or {}
            if sql_state.get("refused_code"):
                yield sse_frame("error", {
                    "code": "sql_refused",
                    "message": (final_state or {}).get("error")
                               or sql_state["refused_code"],
                })
```

（放在 `await persist()` 之后、`done` 事件之前，顺序为：token → sql_result/clarify → error → done。）

- [ ] **Step 4: 跑测试确认通过并全量回归**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/chat.py backend/tests/test_chat_auth.py
git commit -m "feat(chat): 查数与拒绝都落 sql_queries，拒绝补发 sql_refused 事件"
```

---

## Task 9: 前端澄清选项条与数据表 + SQL 折叠

**Files:**
- Modify: `frontend/src/types.ts`（加两个事件类型）
- Modify: `frontend/src/composables/useChatStream.ts`（处理两事件）
- Create: `frontend/src/components/chat/ClarifyBar.vue`
- Create: `frontend/src/components/chat/SqlResultTable.vue`
- Modify: `frontend/src/components/chat/MessageBubble.vue`（渲染两者）
- Modify: `frontend/src/components/chat/MessageList.vue`（滚动 key 补两项）
- Test: `frontend/tests/useChatStream.test.ts`（追加）

**Interfaces:**
- Consumes: SSE `clarify`/`sql_result` 事件（Task 6/8 发出）、`useChatStream().send`（模块级单例，`ClarifyBar` 直接取，不逐层 emit）
- Produces:
  - `ClarifyEvent { question: string; options: { label: string }[] }`
  - `SqlResultEvent { sql: string; columns: string[]; rows: (string|number|null)[][]; row_count: number; truncated: boolean }`
  - `ChatMessage` 增 `clarify: ClarifyEvent | null`、`sqlResult: SqlResultEvent | null`（**两个都进 MessageList 的滚动 key**，否则选项条到达时列表不滚到底）

- [ ] **Step 1: 写失败测试（两个新事件落到响应式消息上）**

追加到 `frontend/tests/useChatStream.test.ts` 的 `describe('useChatStream')` 内（沿用该文件已有的 `stubStream` 辅助函数，不新建 fixture）：

```ts
  it('clarify 事件落到气泡上，选项与问题完整', async () => {
    stubStream([
      'event: clarify\ndata: {"question":"你要查哪个学期？","options":[{"label":"2025 秋"},{"label":"2026 春"}]}\n\n',
      'event: done\ndata: {"message_id":"m2","steps":["router","sql_executor","generator"]}\n\n',
    ])

    const { messages, send } = useChatStream()
    await send('我的数据结构成绩')

    const assistant = messages.value[messages.value.length - 1]
    expect(assistant.clarify?.question).toBe('你要查哪个学期？')
    expect(assistant.clarify?.options.map((o) => o.label)).toEqual(['2025 秋', '2026 春'])
    expect(assistant.error).toBeNull()
  })

  it('sql_result 事件带列、行、行数与 SQL 原文', async () => {
    stubStream([
      'event: sql_result\ndata: {"sql":"SELECT course FROM (SELECT * FROM v_grades WHERE student_id = ?) AS v_grades","columns":["course","term"],"rows":[["高等数学（上）","2025 秋"]],"row_count":1,"truncated":false}\n\n',
      'event: done\ndata: {"message_id":"m3","steps":["router","sql_executor","generator"]}\n\n',
    ])

    const { messages, send } = useChatStream()
    await send('我成绩怎么样')

    const assistant = messages.value[messages.value.length - 1]
    expect(assistant.sqlResult?.columns).toEqual(['course', 'term'])
    expect(assistant.sqlResult?.rows).toHaveLength(1)
    expect(assistant.sqlResult?.row_count).toBe(1)
    expect(assistant.sqlResult?.sql).toContain('student_id = ?')
    expect(assistant.sqlResult?.truncated).toBe(false)
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run tests/useChatStream.test.ts`
Expected: FAIL — `assistant.clarify` 为 undefined（事件未被处理）

- [ ] **Step 3: 加类型**

`frontend/src/types.ts` 在 `ErrorEvent` 后加：

```ts
export interface ClarifyOption { label: string }
export interface ClarifyEvent {
  question: string
  options: ClarifyOption[]
}
export interface SqlResultEvent {
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  row_count: number
  truncated: boolean
}
```

`frontend/src/composables/useChatStream.ts` 的 `ChatMessage` 加两个字段并给每处 `push` 的对象补 `clarify: null, sqlResult: null`（`send` 里两处 push 都要补，否则 TypeScript 会报缺字段）。

- [ ] **Step 4: 实现事件处理**

`useChatStream.ts` 的 frame 循环里，`nav_card` 分支之后加：

```ts
          } else if (frame.event === 'clarify') {
            assistant.clarify = JSON.parse(frame.data) as ClarifyEvent
          } else if (frame.event === 'sql_result') {
            assistant.sqlResult = JSON.parse(frame.data) as SqlResultEvent
          }
```

import 处补 `ClarifyEvent, SqlResultEvent`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run tests/useChatStream.test.ts`
Expected: 全绿（含新增 2 条）

- [ ] **Step 6: 写两个组件**

`frontend/src/components/chat/ClarifyBar.vue`：

```vue
<script setup lang="ts">
import type { ClarifyEvent } from '../../types'
import { useChatStream } from '../../composables/useChatStream'

const props = defineProps<{ clarify: ClarifyEvent }>()
const { send, streaming } = useChatStream()

// 直接用模块级单例的 send：中间三层组件逐层 emit 只为传一个回调，
// 而 useChatStream 本来就是设计成跨组件存活的单例（悬浮球卸载也不断流）
function choose(label: string) {
  if (!streaming.value) void send(label)
}
</script>

<template>
  <div class="clarify">
    <p class="clarify-q">{{ props.clarify.question }}</p>
    <div class="clarify-opts">
      <button
        v-for="o in props.clarify.options"
        :key="o.label"
        type="button"
        class="clarify-opt"
        :disabled="streaming"
        @click="choose(o.label)"
      >
        {{ o.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.clarify {
  border: 1px dashed var(--rule-2);
  border-radius: var(--r-sm);
  background: var(--paper);
  padding: 8px 10px;
}

.clarify-q {
  font-size: 13px;
  color: var(--text);
}

.clarify-opts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.clarify-opt {
  font: inherit;
  font-size: 12.5px;
  padding: 5px 12px;
  color: var(--ink);
  background: var(--card);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.clarify-opt:hover:not(:disabled) {
  color: #fff;
  background: var(--seal);
  border-color: var(--seal);
}

.clarify-opt:disabled {
  color: var(--faint);
  border-color: var(--rule-2);
  cursor: default;
}
</style>
```

`frontend/src/components/chat/SqlResultTable.vue`：

```vue
<script setup lang="ts">
import type { SqlResultEvent } from '../../types'

const props = defineProps<{ result: SqlResultEvent }>()
</script>

<template>
  <div class="sql-block">
    <div v-if="!props.result.rows.length" class="sql-empty">没有查到数据</div>
    <div v-else class="sql-scroll">
      <table class="sql-table">
        <thead>
          <tr><th v-for="c in props.result.columns" :key="c">{{ c }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in props.result.rows" :key="i">
            <td v-for="(cell, j) in row" :key="j">{{ cell ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="props.result.truncated" class="sql-trunc">仅显示前 50 行</p>

    <!-- SQL 外显是 spec 的设计原则 3：能看见机器在做什么，也是唯一能发现"查错了"的证据 -->
    <details class="sql-details">
      <summary>查看用到的查询</summary>
      <pre class="sql-code"><code>{{ props.result.sql }}</code></pre>
    </details>
  </div>
</template>

<style scoped>
.sql-block {
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--paper);
  padding: 8px 10px;
}

.sql-empty {
  font-size: 12.5px;
  color: var(--faint);
}

.sql-scroll {
  max-height: 220px;
  overflow: auto;
}

.sql-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.sql-table th,
.sql-table td {
  text-align: left;
  padding: 5px 8px;
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}

.sql-table th {
  position: sticky;
  top: 0;
  background: var(--card);
  color: var(--ink);
  font-weight: 600;
}

.sql-trunc {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--faint);
}

.sql-details {
  margin-top: 8px;
}

.sql-details summary {
  font-size: 12px;
  color: var(--ink-2);
  cursor: pointer;
}

.sql-code {
  margin-top: 6px;
  padding: 8px;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  font-family: var(--mono);
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-x: auto;
}
</style>
```

- [ ] **Step 7: 挂进气泡与滚动 key**

`frontend/src/components/chat/MessageBubble.vue`：import 两个新组件，在 `<NavigationCard …>` 之后插：

```html
    <SqlResultTable v-if="message.sqlResult" :result="message.sqlResult" />
    <ClarifyBar v-if="message.clarify" :clarify="message.clarify" />
```

`frontend/src/components/chat/MessageList.vue` 的 `tail` 计算补两项（否则选项条/表格到达时列表不滚到底）：

```ts
  return `${props.messages.length}|${last?.text.length ?? 0}|${last?.toolCall ? 1 : 0}|${last?.navCard ? 1 : 0}|${last?.error ? 1 : 0}|${last?.clarify ? 1 : 0}|${last?.sqlResult ? 1 : 0}`
```

- [ ] **Step 8: 全量前端验证**

```bash
cd frontend && npx vitest run && npx vite build && npx vue-tsc --noEmit
```

Expected: vitest 全绿（4 个文件，22 条）；build 绿；`vue-tsc` 无未找到导出类错误（新增类型若漏导出，这里必报）

- [ ] **Step 9: 提交**

```bash
git add frontend/src frontend/tests/useChatStream.test.ts
git commit -m "feat(front): clarify 选项条与 sql_result 数据表 + SQL 折叠外显"
```

---

## Task 10: 越权用例 A1–A6 真路径 + 真库冒烟 + 收尾

**Files:**
- Test: `backend/tests/test_sql_authz.py`（新建）
- 无生产代码改动（**若此任务改了生产代码，说明前面某个任务的验收没做实**）

**Interfaces:**
- Consumes: Task 2–8 全部产出；`init_sqlite`、`build_repository`、`build_provider(Settings(llm_provider="fake"))`、`build_graph`、`CompositeRegistry`（测试里用 `InMemoryRegistry` 拼 navigation + **真 academic 子进程**）
- Produces: A1–A6 的可跑判据（spec 9.1 要求"真 SQL 生成路径：FakeProvider 的固定 SQL 脚本 + 真 academic server + 真 SQLite，不是 mock 校验函数"）

- [ ] **Step 1: 写 A1–A6（真路径）**

`backend/tests/test_sql_authz.py`：

```python
"""spec 9.1 A1–A6：必须走真 academic 子进程 + 真 SQLite，
mock 掉校验函数就测不出绕过——校验层和被测代码之间隔一层 mock 等于没测。"""
import json
import os
from pathlib import Path

import pytest

from app.agent.graph import build_graph
from app.config import Settings
from app.db.migrations import init_sqlite
from app.db.repository import build_repository
from app.llm.base import RouteDecision
from app.llm.fake import FakeProvider
from app.tools.composite import CompositeRegistry
from app.tools.inmemory import InMemoryRegistry
from app.tools.stdio_mcp import stdio_registry

NAV_SPEC = {"name": "resolve_page", "description": "d",
            "input_schema": {"type": "object",
                             "properties": {"intent": {"type": "string"}},
                             "required": ["intent"]}}


class ScriptedProvider(FakeProvider):
    """按脚本吐 SQL：A3–A6 直接把要被拒的语句交给真 run_sql。"""

    def __init__(self, sql: str):
        self._sql = sql

    async def route(self, user_input, tools):
        return RouteDecision(intent=user_input, tool_name=None,
                             tool_args={}, confidence=1.0)

    async def generate_sql(self, user_input: str, schema_json: str) -> str:
        return self._sql


@pytest.fixture
async def academic_registry(tmp_path):
    db_path = tmp_path / "campus.db"
    db = await init_sqlite(db_path)
    await db.execute(
        "INSERT INTO students (student_id, name, password_hash)"
        " VALUES ('20230001','周晓楠','x'),('20230007','林知远','x')")
    await db.execute(
        "INSERT INTO enrollments (student_id, course_name, term, credits,"
        " score, grade_points, teacher) VALUES"
        " ('20230001','数据结构','2026 春',4,87,3.7,'李慧'),"
        " ('20230007','数据结构','2026 春',4,93,4.3,'李慧'),"
        " ('20230001','高等数学（上）','2025 秋',5,91,4.1,'王建国')")

    env = {**os.environ, "DB_BACKEND": "sqlite", "SQLITE_PATH": str(db_path)}
    nav = InMemoryRegistry({"resolve_page": {
        "spec": NAV_SPEC, "fn": lambda intent: {"path": "/x", "title": "t",
                                                "capabilities": []}}})
    async with stdio_registry(Path("mcp_servers/academic"), env=env) as acad:
        yield CompositeRegistry([nav, acad])


async def run(provider, registry, student_id="20230001"):
    graph = build_graph(provider, registry)
    final = None
    async for mode, payload in graph.astream(
        {"user_input": "查我的成绩", "student_id": student_id,
         "history": [], "intent": None, "route": None,
         "tool_name": None, "tool_args": {}, "tool_results": {},
         "answer": "", "nav_card": None, "needs_clarification": False,
         "clarification": None, "sql": None, "steps": [], "error": None},
        stream_mode=["custom", "values"],
    ):
        if mode == "values":
            final = payload
    return final


class TestA1到A6:
    async def test_A1_只返回自己的行且scoped留下证据(self, academic_registry):
        final = await run(FakeProvider(), academic_registry)
        assert final["error"] is None
        rows = final["sql"]["rows"]
        assert rows and all("林知远" not in str(r) for r in rows)
        assert "student_id = ?" in final["sql"]["scoped"]

    async def test_A2_同名课程分数按人隔离(self, academic_registry):
        provider = ScriptedProvider(
            "SELECT course, term, score FROM v_grades"
            " WHERE course = '数据结构' ORDER BY term")
        final = await run(provider, academic_registry)
        assert final["sql"]["rows"] == [["数据结构", "2026 春", 87]]   # 不是 93

    async def test_A3_身份列拒绝并记录refused_code(self, academic_registry):
        provider = ScriptedProvider(
            "SELECT * FROM v_grades WHERE student_id='20230007'")
        final = await run(provider, academic_registry)
        assert final["sql"]["refused_code"] == "identity_column"
        assert final["sql"]["scoped"] == ""
        assert final["sql"]["row_count"] == 0

    async def test_A4_基表拒绝(self, academic_registry):
        final = await run(
            ScriptedProvider("SELECT * FROM enrollments"), academic_registry)
        assert final["sql"]["refused_code"] == "relation_not_whitelisted"

    async def test_A5_多语句拒绝(self, academic_registry):
        final = await run(
            ScriptedProvider("SELECT 1; DROP TABLE students"), academic_registry)
        assert final["sql"]["refused_code"] == "multi_statement"

    async def test_A6_耗时函数拒绝且不占连接(self, academic_registry, tmp_path):
        final = await run(ScriptedProvider("SELECT SLEEP(30)"), academic_registry)
        assert final["sql"]["refused_code"] == "cost_function"
        # 拒绝后库仍完好（表还在，连接没被占死）
        import aiosqlite
        async with aiosqlite.connect(tmp_path / "campus.db") as db:
            cur = await db.execute("SELECT COUNT(*) FROM students")
            assert (await cur.fetchone())[0] == 2
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_sql_authz.py -v`
Expected: 6 passed

**若失败**：按 `refused_code` 与 `rows` 的实际值判断是校验漏了、改写漏了、还是 env 没透传（`ModuleNotFoundError`/`db_unavailable` 即 env 问题，回 Task 4 Step 6）。**不许用 mock 绕过、不许放宽断言**——这六条是 S3 的全部安全价值。

- [ ] **Step 3: 真库冒烟（MySQL 路径，手动一次）**

```bash
# 起库（WSL 内）
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d && \
  sleep 10 && docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps"

# 迁移建视图（root 执行一次授权脚本——不是迁移文件，SQLite 无权限概念）
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T mysql \
  mysql -uroot -p<MYSQL_ROOT_PASSWORD> campus < deploy/mysql/grant_agent_ro_views.sql"

# 灌库 + 服务起来
cd backend && DB_BACKEND=mysql .venv/Scripts/python.exe ../scripts/seed_academic.py
DB_BACKEND=mysql .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &

# 判据 1：agent_ro 能读视图、仍读不了基表（spec 4.4 纵深）
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T mysql \
  mysql -uagent_ro -p<AGENT_RO_PASSWORD> -e 'SELECT COUNT(*) FROM campus.v_grades'"
# Expected: 返回一个数字

wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T mysql \
  mysql -uagent_ro -p<AGENT_RO_PASSWORD> -e 'SELECT COUNT(*) FROM campus.enrollments'"
# Expected: ERROR 1142（基表仍不可读）

# 判据 2：MySQL 路径下问成绩能出数据表
curl -s -c /tmp/s3.txt -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"student_id":"20230001","password":"demo1234"}' > /dev/null
curl -s -N -b /tmp/s3.txt -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"我的高等数学成绩"}' | head -40
# Expected: 含 event: sql_result，columns 里有 course/score，rows 是周晓楠的行
kill %1
```

- [ ] **Step 4: 全量回归 + 契约 + 前端**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
cd .. && backend/.venv/Scripts/python.exe scripts/check_routes_contract.py
cd frontend && npx vitest run && npx vite build
cd .. && git status --short
```

Expected: 后端全绿（约 90+ 条）；契约三行 OK、exit 0；前端 vitest 22 条全绿、build 绿；`git status` 里 `deploy/.env`/`backend/.env`/`backend/data/*.db` 均不出现

- [ ] **Step 5: 手测 spec 13 的完成定义第 3、4、5 条**

```bash
cd backend && rm -f data/campus.db && DB_BACKEND=sqlite .venv/Scripts/python.exe ../scripts/seed_academic.py
DB_BACKEND=sqlite .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
cd frontend && npx vite dev
```

浏览器 `http://localhost:5173` 登录 20230001 后：

1. 问「我的高等数学成绩」→ 气泡里出现**数据表**（课程/学期/分数/绩点），点「查看用到的查询」能看到含 `student_id = ?` 的改写后 SQL —— **不是跳转卡片**
2. 问「我的数据结构成绩」→ 出**选项条**，点「2025 秋」→ 直接给该学期结果，不重复追问
3. 问「陈默的高数成绩」→ 返回的仍是周晓楠自己的行（可在 SQL 折叠里核对过滤条件）
4. 无 Cookie 打 `/chat` → 401；塞 `student_id` 进请求体 → 422

- [ ] **Step 6: 提交**

```bash
git add backend/tests/test_sql_authz.py
git commit -m "test(authz): A1-A6 真 SQL 路径越权用例，走真 academic 子进程"
```

---

## S3 完成判据（对应 spec §10 S3 行与 §13 第 3/4/5 条）

| # | 判据 | 可跑命令 |
|---|---|---|
| 1 | 问"我的高等数学成绩"→ 返回分数表格而非跳转卡片 | Task 10 Step 5 手测 1 |
| 2 | 跨学期收到 `clarify`，点选项后收敛 | Task 10 Step 5 手测 2 |
| 3 | **A1–A6 全过** | `cd backend && .venv/Scripts/python.exe -m pytest tests/test_sql_authz.py -v` |
| 4 | 前端能看到实际执行的 SQL | Task 10 Step 5 手测 1 的折叠区 |
| 5 | 双方言迁移文件同名（0002/0003） | `backend/.venv/Scripts/python.exe scripts/check_routes_contract.py` → `同名 3 个` |
| 6 | `agent_ro` 能读视图、读不了基表 | Task 10 Step 3 两条 `mysql -e` 判据 |
| 7 | 全绿且工作树干净 | Task 10 Step 4 四条命令 |
| 8 | S2 记账的 6 条欠账仍挂在 S3 名下 | 见下方"本计划未覆盖的欠账" |

## 本计划未覆盖的欠账（不要当成遗漏）

`specs/2026-09-22-campus-roadmap-s4-s7-design.md` §3.1 登记了 6 条"延后到 S3"的项：MySQL 缺 FOREIGN KEY（需 `0004` 迁移）、`record_exchange` 三 INSERT 无共享事务、`save_row` 每行两趟往返、`_get_pool` 首调竞态、五页 `.state-*` 外壳收敛成 `StateShell.vue`、契约脚本只扫 `academic.py`。

**这 6 条不在本计划的 10 个任务里**，理由：它们与"查数能力"无功能耦合，混进 S3 会让每个任务的 review 边界变糊（例如 `0004` 迁移会与本计划的 `0002/0003` 抢迁移序号与契约断言的期望值）。它们应作为**独立的一次性收尾提交**在 S3 之后单独做，或并入 S4 的首个任务。本计划只承诺不新增欠账。
