# S2 MySQL 数据层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把教务数据从 `frontend/src/data/seed.ts` 常量搬进数据库：Docker 起 MySQL 8.4、自建极简迁移器跑双方言 DDL、`Database` 协议统一 `aiomysql`/`aiosqlite`、seed 脚本灌三个账号的异构数据、`/api/*` 四端点供前端四页与首页改读真库。

**Architecture:** 后端加 `app/db/base.py`（`Database` 协议 + 占位符转换）、`app/db/database.py`（两个实现）、`app/db/migrations.py`（`schema_version` 按序执行未应用文件）与 `app/db/migrations/{mysql,sqlite}/0001_init.sql`。仓储（students / conversations）从"每函数自开 aiosqlite 连接"改为注入 `Database`。新端点集中在 `app/api/academic.py`。前端加 `useResource` composable，四页与首页只换数据源、不动版式。

**Tech Stack:** FastAPI + pydantic v2、aiomysql（新运行时依赖）+ aiosqlite、Docker Compose（mysql:8.4）、Vue 3 + vitest。

**Spec:** `docs/superpowers/specs/2026-09-20-campus-auth-text2sql-mysql-design.md` 第 5、6、8.3、9.2、10 节（S2 行）。前置：S1 已合入 main（`d45fc93`）。

## Global Constraints

- Python 一律 `uv`；后端与 MCP server 是两个独立 uv 项目。本计划唯一新增运行时依赖是 `aiomysql>=0.2`。
- 不引入 ORM 与 Alembic；迁移是"`schema_version` 表 + 按序执行未应用 `.sql` 文件，单文件一个事务"。
- 调用方 SQL 一律写 `?` 占位符；`%s` 只许出现在 `database.py` 的转换函数里。调用方 SQL 字符串字面量内不得含 `?`（转换函数只认引号外的 `?`）。
- DDL 方言差异只许出现在 `migrations/mysql/` 与 `migrations/sqlite/` 文件里，代码里不许有方言分支（`build_database` 的 backend 选择除外）。
- `DB_BACKEND` 默认 `mysql`；`sqlite` 用于无 Docker 的机器与全部自动化测试。
- 迁移文件名集合双方言必须一致（契约脚本断言）。
- `student_id` 永不出现在任何请求体/查询串里；`/api/*` 全部走 `require_student`。
- `conversations` 新 schema 不再保留 `session_id` 列（S1 代码注释已预告）；**存量开发库 `backend/data/campus.db` 是旧形状，本计划中"本地起服务"步骤前直接删除它**（gitignored、可再生成）。
- seed 明文密码 `demo1234` 只因本地仿真成立（spec 第 11 节告警）；搬运到公网前必须换账号并强制 `cookie_secure=True`。
- `backend/.env`、`deploy/.env`、`backend/data/*.db` 不得被跟踪。
- 每个任务结束时提交一次。
- 语义视图（`v_grades` 等）与 `agent_ro` 的视图授权属 S3；本计划只把 `agent_ro` 锁到"对 `campus` 库零权限"，S3 再授视图 SELECT。

---

### Task 1: Docker 引擎先决 + compose + agent_ro 锁死

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/.env.example`
- Create: `deploy/mysql/lockdown_agent_ro.sql`
- Create: `deploy/.env`（本地，gitignored）

**Interfaces:**
- Produces: 可 `docker info` 的引擎、`deploy/.env`（`MYSQL_ROOT_PASSWORD` / `AGENT_RO_PASSWORD`）、healthy 的 mysql 容器、`agent_ro` 对基表零权限的先验判据。后续任务只依赖"引擎可达 + compose 文件存在"，不依赖本任务的具体密码。

> **状态：本任务已于 2026-09-20 执行完毕**（deploy 文件见提交 `31c8cda`；MySQL 8.4.11 healthy、`agent_ro` 已锁到对 `campus` 零权限、Windows 侧 `127.0.0.1:3306` TCP 可达）。下面的勾即当时的实测判据，复跑可验证。

> **环境结论（2026-09-20 实测，取代 spec 6.1 的 install.sh 路线）**：Windows 侧 docker CLI 走 2375 且未监听；按用户决策**不再配置 2375**，所有 docker 操作都在 WSL 内执行（Git Bash 里以 `wsl docker ...` 或 `wsl bash -lc "cd /mnt/c/... && docker compose ..."` 调用）。WSL 内 daemon 原生可达（实测 29.7.2），compose 发布的 `3306:3306` 经 WSL2 端口转发后 Windows 侧 `127.0.0.1:3306` 可直连（已实测 TCP_OK），后端 aiomysql 无需任何特殊配置。

- [x] **Step 1: 确认引擎可达**

Run: `wsl docker info --format '{{.ServerVersion}}'`
Expected: 输出非空版本号。若 WSL 内也不可达，报告环境阻塞并停止整个 S2（不许改用 SQLite 冒充交付，spec 6.1 精神不变）。

- [x] **Step 2: 写 compose 与锁死脚本**

`deploy/docker-compose.yml` 逐字（spec 6.2；注释照抄其说明）：

```yaml
services:
  mysql:
    image: mysql:8.4
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --default-time-zone=+08:00
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: campus
      MYSQL_USER: agent_ro
      MYSQL_PASSWORD: ${AGENT_RO_PASSWORD}
    ports: ["3306:3306"]
    volumes: [campus-mysql:/var/lib/mysql]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 5s
      timeout: 5s
      retries: 20
volumes:
  campus-mysql: {}
```

`deploy/.env.example`：

```bash
MYSQL_ROOT_PASSWORD=change-me-root
AGENT_RO_PASSWORD=change-me-agent-ro
```

`deploy/mysql/lockdown_agent_ro.sql`（为什么不是迁移文件：迁移要求双方言同名同集合，而 SQLite 无用户权限概念；GRANT/REVOKE 是 MySQL 独有的一次性运维脚本，S3 的 0002 会在此基础上授视图 SELECT）：

```sql
-- compose 的 MYSQL_USER 默认授予 agent_ro 对 campus.* 的全部权限；
-- 最小权限原则：S2 先全部收回（agent_ro 尚无可查对象），S3 授四个视图的 SELECT。
REVOKE ALL PRIVILEGES ON campus.* FROM 'agent_ro'@'%';
FLUSH PRIVILEGES;
```

创建 `deploy/.env`（本地仿真，值可以弱但**不得入库**；`.gitignore` 的 `.env`/`.env.*` 规则已覆盖）：

```bash
MYSQL_ROOT_PASSWORD=root-local-dev
AGENT_RO_PASSWORD=agent-ro-local
```

- [x] **Step 3: 起库并等 healthy**

```bash
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d"
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps"
# 期望 STATUS 出现 (healthy)；未 healthy 看日志：docker compose ... logs mysql
```

若 root 登录报 1045（Access denied）：是 `campus-mysql` 数据卷带着旧密码初始化过（compose 只在卷空白时执行初始化）。S2 之前库内没有任何要保留的数据，重建是安全的：

```bash
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml down -v && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d"
```

- [x] **Step 4: 执行锁死并验证 agent_ro 最小权限**

```bash
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T mysql \
  mysql -uroot -proot-local-dev campus < deploy/mysql/lockdown_agent_ro.sql"
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T mysql \
  mysql -uagent_ro -pagent-ro-local -e 'SELECT 1; SHOW DATABASES;'"
```

Expected: `SELECT 1` 返回 1；`SHOW DATABASES` 只有 `information_schema` 与 `performance_schema`——`campus` 都不可见。若能看到 campus 或任何业务表，锁死失败，停查。

- [x] **Step 5: 从 Windows 侧验证端口转发**

```bash
(echo > /dev/tcp/127.0.0.1/3306) && echo TCP_OK
```

Expected: `TCP_OK`。此判据保证后端 `aiomysql` 用 `127.0.0.1:3306` 直连即可，无需改任何网络配置。

- [x] **Step 6: 提交**

```bash
git add deploy/docker-compose.yml deploy/.env.example deploy/mysql/lockdown_agent_ro.sql
git commit -m "feat(deploy): mysql 8.4 compose、agent_ro 最小权限锁死脚本"
```

---

### Task 2: Database 双驱动抽象 + 极简迁移器

**Files:**
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/database.py`
- Create: `backend/app/db/migrations.py`
- Create: `backend/app/db/migrations/mysql/0001_init.sql`
- Create: `backend/app/db/migrations/sqlite/0001_init.sql`
- Modify: `backend/app/config.py`
- Modify: `backend/pyproject.toml`（dependencies 加 `aiomysql>=0.2`）
- Test: `backend/tests/test_database.py`

**Interfaces:**
- Consumes: `Settings`（Task 内新增字段）
- Produces:
  - `class Database(Protocol)`：`dialect: Literal["mysql","sqlite"]`；`async def fetch_all(sql: str, args: Sequence[Any] = ()) -> list[dict]`；`async def execute(sql: str, args: Sequence[Any] = ()) -> int`（返回 `lastrowid`）；`async def execute_script(sql: str) -> None`
  - `class SqliteDatabase(path: Path)`、`class MySQLDatabase(host, port, user, password, database)`
  - `def to_mysql_placeholders(sql: str) -> str`（引号外的 `?` → `%s`，字面量内的 `?` 不动）
  - `def build_database(settings: Settings) -> Database`
  - `async def run_migrations(db: Database) -> list[int]`（返回本次应用的版本号；幂等）
  - `async def init_sqlite(path: Path) -> Database`（建父目录 + `SqliteDatabase` + `run_migrations`，测试与 sqlite 启动共用）
  - 建表后的库形状：`students / courses / enrollments / course_sections / makeup_items / library_loans / conversations(id, student_id, created_at) / messages / tool_calls / schema_version`
- 后续 Task 3 消费 `init_sqlite`/`build_database`/`run_migrations`；Task 5 消费表形状。

- [ ] **Step 1: 加 aiomysql 依赖**

`backend/pyproject.toml` 的 `dependencies` 列表在 `"aiosqlite>=0.20",` 后加一行 `"aiomysql>=0.2",`。

Run: `cd backend && uv sync` — Expected: 锁文件更新成功，`uv run python -c "import aiomysql"` 无报错。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_database.py
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
    db = await init_sqlite(tmp_path / "campus.db")

    applied = await run_migrations(db)
    assert applied == [1]

    # 幂等：再跑无新应用
    assert await run_migrations(db) == []

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
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_database.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.base'`

- [ ] **Step 4: 写实现**

`backend/app/db/base.py`：

```python
from typing import Any, Literal, Protocol, Sequence


class Database(Protocol):
    """双驱动最小协议。调用方一律写 ? 占位符，方言差异收敛在实现里。"""

    dialect: Literal["mysql", "sqlite"]

    async def fetch_all(self, sql: str, args: Sequence[Any] = ()) -> list[dict]: ...
    async def execute(self, sql: str, args: Sequence[Any] = ()) -> int: ...
    async def execute_script(self, sql: str) -> None: ...
```

`backend/app/db/database.py`：

```python
from pathlib import Path
from typing import Any, Sequence

from .base import Database


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
```

`backend/app/config.py` 的 `Settings` 在 `sqlite_path` 行后追加：

```python
    db_backend: str = "mysql"  # mysql | sqlite；sqlite 用于无 Docker 机器与全部测试
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "campus"
```

同时往 `backend/.env`（gitignored）追加这几行——日常开发先走 sqlite，真库冒烟时改 `DB_BACKEND=mysql`：

```bash
DB_BACKEND=sqlite
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root-local-dev
MYSQL_DATABASE=campus
```

- [ ] **Step 5: 写双方言迁移文件**

`backend/app/db/migrations/sqlite/0001_init.sql`：

```sql
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    major TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL DEFAULT '',
    college TEXT NOT NULL DEFAULT '',
    enrolled_year INTEGER NOT NULL DEFAULT 2023,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS courses (
    course_code TEXT PRIMARY KEY,
    course_name TEXT NOT NULL,
    credits REAL NOT NULL,
    teacher TEXT NOT NULL DEFAULT '',
    college TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '必修',
    domain TEXT NOT NULL DEFAULT 'hum'
);
CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    course_name TEXT NOT NULL,
    term TEXT NOT NULL,
    credits REAL NOT NULL,
    score REAL NOT NULL,
    grade_points REAL NOT NULL DEFAULT 0,
    teacher TEXT NOT NULL DEFAULT '',
    UNIQUE(student_id, course_code, term)
);
CREATE TABLE IF NOT EXISTS course_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    course_name TEXT NOT NULL,
    weekday INTEGER NOT NULL,
    start_period INTEGER NOT NULL,
    end_period INTEGER NOT NULL,
    room TEXT NOT NULL DEFAULT '',
    teacher TEXT NOT NULL DEFAULT '',
    weeks_from INTEGER NOT NULL DEFAULT 1,
    weeks_to INTEGER NOT NULL DEFAULT 16,
    term TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS makeup_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_name TEXT NOT NULL,
    course_code TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '补考',
    reason TEXT NOT NULL DEFAULT '',
    scheduled_at TEXT NOT NULL,
    place TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '已报名',
    seats_left INTEGER,
    seats_total INTEGER,
    term TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS library_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    title TEXT NOT NULL,
    call_no TEXT NOT NULL,
    due_at TEXT NOT NULL,
    shelf TEXT NOT NULL DEFAULT '',
    returned_at TEXT
);
-- 新形状：不再有 session_id 列（S1 兼容写法随之删除，见 Task 3）
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    latency_ms INTEGER NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`backend/app/db/migrations/mysql/0001_init.sql`（同表集合、MySQL 方言；`kind`/`domain` 两列是对 spec 5.1 的有意增补——spec 8.3 要求返回结构与前端 `CourseEntry` 对齐，而 `courses` 表没有这两列无处可放）：

```sql
CREATE TABLE IF NOT EXISTS students (
    student_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    major VARCHAR(128) NOT NULL DEFAULT '',
    class_name VARCHAR(64) NOT NULL DEFAULT '',
    college VARCHAR(128) NOT NULL DEFAULT '',
    enrolled_year INT NOT NULL DEFAULT 2023,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS courses (
    course_code VARCHAR(32) PRIMARY KEY,
    course_name VARCHAR(128) NOT NULL,
    credits DECIMAL(4,1) NOT NULL,
    teacher VARCHAR(64) NOT NULL DEFAULT '',
    college VARCHAR(128) NOT NULL DEFAULT '',
    kind VARCHAR(16) NOT NULL DEFAULT '必修',
    domain VARCHAR(16) NOT NULL DEFAULT 'hum'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS enrollments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    course_code VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    term VARCHAR(32) NOT NULL,
    credits DECIMAL(4,1) NOT NULL,
    score DECIMAL(5,1) NOT NULL,
    grade_points DECIMAL(3,1) NOT NULL DEFAULT 0,
    teacher VARCHAR(64) NOT NULL DEFAULT '',
    UNIQUE KEY uq_enrollment (student_id, course_code, term),
    INDEX idx_enroll_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS course_sections (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    course_code VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    weekday INT NOT NULL,
    start_period INT NOT NULL,
    end_period INT NOT NULL,
    room VARCHAR(64) NOT NULL DEFAULT '',
    teacher VARCHAR(64) NOT NULL DEFAULT '',
    weeks_from INT NOT NULL DEFAULT 1,
    weeks_to INT NOT NULL DEFAULT 16,
    term VARCHAR(32) NOT NULL DEFAULT '',
    INDEX idx_sections_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS makeup_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    course_code VARCHAR(32) NOT NULL DEFAULT '',
    kind VARCHAR(16) NOT NULL DEFAULT '补考',
    reason VARCHAR(256) NOT NULL DEFAULT '',
    scheduled_at DATETIME NOT NULL,
    place VARCHAR(128) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT '已报名',
    seats_left INT NULL,
    seats_total INT NULL,
    term VARCHAR(32) NOT NULL DEFAULT '',
    INDEX idx_makeup_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS library_loans (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    title VARCHAR(256) NOT NULL,
    call_no VARCHAR(64) NOT NULL,
    due_at DATETIME NOT NULL,
    shelf VARCHAR(128) NOT NULL DEFAULT '',
    returned_at DATETIME NULL,
    INDEX idx_loans_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conv_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_msg_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS tool_calls (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    tool_name VARCHAR(64) NOT NULL,
    args_json TEXT NOT NULL,
    ok TINYINT NOT NULL,
    error TEXT,
    latency_ms INT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tc_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 6: 写迁移器**

```python
# backend/app/db/migrations.py
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
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_database.py -v`
Expected: 7 passed

- [ ] **Step 8: 全量回归 + 提交**

Run: `cd backend && uv run pytest -q`
Expected: 全绿（本任务只新增，不改旧行为）

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/db backend/app/config.py backend/tests/test_database.py
git commit -m "feat(db): Database 双驱动协议、?→%s 转换与双方言极简迁移器"
```

---

### Task 3: 仓储与 lifespan 迁到 Database，删除旧引擎

**Files:**
- Modify: `backend/app/auth/students.py`（`SqliteStudentRepository(path)` → `DbStudentRepository(db)`；`build_student_repository(path)` → `(db)`；`seed_students(path)` → `(db)`）
- Modify: `backend/app/db/repository.py`（同上；`record_exchange` 去掉 `session_id` 列写入）
- Delete: `backend/app/db/engine.py`（SCHEMA/_ensure_column/init_db 被迁移器取代）
- Modify: `backend/app/main.py`（lifespan 用 `build_database` + `run_migrations`）
- Test: 更新 `backend/tests/test_students.py`、`test_auth_api.py`、`test_chat_auth.py`、`test_repository.py` 的 fixture（`init_db(path)` → `init_sqlite(path)`，三个 `build_*(path)` → `(db)`）

**Interfaces:**
- Consumes: `Database`/`init_sqlite`/`build_database`/`run_migrations`（Task 2）
- Produces:
  - `build_student_repository(db: Database) -> StudentRepository`
  - `seed_students(db: Database) -> int`
  - `build_repository(db: Database) -> ConversationRepository`；`record_exchange` 签名不变，但 `conversations` 插入只剩 `student_id` 一列
  - `app.state.db`（lifespan 挂出，端点与后续任务直接用）

- [ ] **Step 1: 改学生仓储**

`backend/app/auth/students.py`：删去全部函数内的 `import aiosqlite` 与自开连接；`SqliteStudentRepository` 更名 `DbStudentRepository`，`__init__(self, db: Database)`；三个方法体改为：

```python
    async def get(self, student_id: str) -> Student | None:
        rows = await self._db.fetch_all(
            "SELECT student_id, name, major, class_name, college "
            "FROM students WHERE student_id = ?", (student_id,))
        return Student(**rows[0]) if rows else None

    async def get_password_hash(self, student_id: str) -> str | None:
        rows = await self._db.fetch_all(
            "SELECT password_hash FROM students WHERE student_id = ?", (student_id,))
        return rows[0]["password_hash"] if rows else None

    async def upsert(self, student: Student, password_hash: str) -> None:
        await self._db.execute(
            """INSERT INTO students (student_id, name, password_hash, major, class_name, college)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(student_id) DO UPDATE SET
                 name=excluded.name, password_hash=excluded.password_hash,
                 major=excluded.major, class_name=excluded.class_name,
                 college=excluded.college""",
            (student.student_id, student.name, password_hash,
             student.major, student.class_name, student.college),
        )
```

`build_student_repository(path: Path)` → `build_student_repository(db: Database)`，返回 `DbStudentRepository(db)`；`seed_students(path)` → `seed_students(db)`，循环体不变。文件头 import 改为 `from ..db.base import Database`。

- [ ] **Step 2: 改会话仓储**

`backend/app/db/repository.py`：`SqliteConversationRepository(path)` → `DbConversationRepository(db)`；`record_exchange` 里 `INSERT INTO conversations(student_id, session_id) VALUES (?,?)` 改为 `INSERT INTO conversations(student_id) VALUES (?)`，参数只传 `student_id`，并删掉上方那段"session_id 列暂与 student_id 同值"注释；`build_repository(path)` → `build_repository(db)`。

- [ ] **Step 3: 删旧引擎**

`git rm backend/app/db/engine.py`。全仓搜 `from app.db.engine import` / `from .db.engine import`，只剩测试 fixture 里的引用（下一步改）。

- [ ] **Step 4: 改 lifespan**

`backend/app/main.py`：

```python
from .db.base import Database
from .db.database import build_database
from .db.migrations import run_migrations
```

lifespan 内替换：

```python
    db = build_database(settings)
    await run_migrations(db)
    app.state.db = db
    await seed_students(db)
    app.state.repository = build_repository(db)
    app.state.students = build_student_repository(db)
```

（`init_db`/`seed_students(settings.sqlite_path)` 两行删除；`app.state.settings = settings` 保留。）

- [ ] **Step 5: 改四个测试文件的 fixture**

统一模式——`backend/tests/test_students.py`、`test_auth_api.py`、`test_chat_auth.py`、`test_repository.py` 里：

```python
from app.db.migrations import init_sqlite
```

- `await init_db(path)` → `db = await init_sqlite(path)`
- `build_student_repository(path)` → `build_student_repository(db)`；`seed_students(path)` → `seed_students(db)`
- `build_repository(path)` → `build_repository(db)`
- fixture 里不再把 `path` 传给仓储；`test_repository.py` 里直读库校验的部分把 `aiosqlite.connect(path)` 换成 `db.fetch_all(...)`（行断言不变，取 `r["student_id"]` 等键）。

- [ ] **Step 6: 全量回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。若有 `no such column: session_id` 之外的方言错，停查。

- [ ] **Step 7: 删除旧开发库并手测起服务（sqlite 模式）**

```bash
rm -f backend/data/campus.db
cd backend && uv run uvicorn app.main:app --port 8000
```

另开终端：`curl -s http://localhost:8000/health` → `{"status":"ok"}`；`curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"student_id":"20230001","password":"demo1234"}'` → 200。Ctrl+C 停掉。

- [ ] **Step 8: 提交**

```bash
git add backend/
git commit -m "refactor(db): 仓储与 lifespan 迁到 Database 协议，conversations 去掉 session_id 列"
```

---

### Task 4: seed_academic.py 灌库脚本

**Files:**
- Create: `scripts/seed_academic.py`
- Test: `backend/tests/test_seed_academic.py`

**Interfaces:**
- Consumes: `build_database`/`run_migrations`/`init_sqlite`（Task 2）、`hash_password`（S1）
- Produces: `async def seed_academic(db: Database) -> dict[str, int]`（返回 `{"students": 3, "courses": 36, "enrollments": 32, "course_sections": 30, "makeup_items": 3, "library_loans": 7}` 这类计数，便于测试与冒烟断言）；`python scripts/seed_academic.py` 可直接运行（读 `backend/.env` 选后端，sqlite 模式自动建父目录）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_seed_academic.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed_academic import seed_academic  # noqa: E402

from app.db.migrations import init_sqlite  # noqa: E402


async def test_seed_三账号异构数据(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    counts = await seed_academic(db)

    assert counts["students"] == 3
    assert counts["enrollments"] >= 28
    assert counts["makeup_items"] == 3  # 全部属于周晓楠（唯一有挂科的人）

    # 20230007 与 20230001 有同名课程但分数不同（spec 5.2，越权用例 A2 的靶子）
    rows = await db.fetch_all(
        "SELECT student_id, score FROM enrollments "
        "WHERE course_name = '数据结构（暑期补习）' AND term = '2026 春'")
    by_student = {r["student_id"]: r["score"] for r in rows}
    assert by_student["20230001"] != by_student["20230007"]

    # 陈默（建筑学）与周晓楠课程完全不同、且无不及格
    rows = await db.fetch_all(
        "SELECT COUNT(*) AS n FROM enrollments WHERE student_id='20230002' AND score < 60")
    assert rows[0]["n"] == 0
    rows = await db.fetch_all(
        "SELECT COUNT(*) AS n FROM enrollments e JOIN enrollments z "
        "ON e.course_code = z.course_code "
        "WHERE e.student_id='20230002' AND z.student_id='20230001'")
    assert rows[0]["n"] == 0

    # 幂等：再灌一遍行数不变
    again = await seed_academic(db)
    assert again == counts


async def test_seed_日期是真日期_且相对灌库日推导(tmp_path):
    """spec 5.1：落库必须真日期；seed 以运行日为锚，重灌即刷新（days_left 由查询时计算）。"""
    db = await init_sqlite(tmp_path / "campus.db")
    await seed_academic(db)
    rows = await db.fetch_all("SELECT due_at FROM library_loans ORDER BY due_at")
    assert len(rows) == 7
    for r in rows:
        assert r["due_at"].count("-") == 2 and ":" in r["due_at"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_seed_academic.py -v`
Expected: FAIL — `No module named 'seed_academic'`

- [ ] **Step 3: 写 seed 脚本**

数据设计（spec 5.2 逐条对齐）：**20230001 周晓楠**承接现前端 seed 全量——12 门在读课程（课表）、12 条历学期成绩（含 56 分大物上、0 分体育一）、3 条补考重修、4 本在借（含 1 本逾期）；**20230002 陈默**建筑学，6 门课、6 条成绩全及格、0 补考、2 本在借；**20230007 林知远**计科，课表与周晓楠完全相同，成绩同名课程不同分、全及格、0 补考、1 本在借。

```python
# scripts/seed_academic.py
"""幂等灌库：三个仿真账号的教务数据。明文密码只因本地仿真成立（spec 第 11 节）。

用法：
    cd backend && uv run python ../scripts/seed_academic.py          # 按 backend/.env 选后端
    DB_BACKEND=sqlite uv run python ../scripts/seed_academic.py      # 指定后端
日期一律相对"运行日"推导；重灌即刷新，days_left 由查询时计算（视图/SQL），不落冗余天数。
"""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.auth.passwords import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.base import Database  # noqa: E402
from app.db.database import build_database  # noqa: E402
from app.db.migrations import run_migrations  # noqa: E402

SEED_PASSWORD = "demo1234"

STUDENTS = [
    ("20230001", "周晓楠", "计算机科学与技术", "计科 2301", "信息科学与工程学院"),
    ("20230002", "陈默", "建筑学", "建筑 2302", "建筑与艺术学院"),
    ("20230007", "林知远", "计算机科学与技术", "计科 2301", "信息科学与工程学院"),
]

# (code, name, credits, teacher, college, kind, domain)
COURSES = [
    ("MATH2041", "高等数学（下）", 5, "王建国", "信息科学与工程学院", "必修", "math"),
    ("CS2052", "数据结构", 4, "李慧", "信息科学与工程学院", "必修", "cs"),
    ("PE2061", "体育（篮球）", 1, "陈毅", "信息科学与工程学院", "必修", "pe"),
    ("FL2034", "大学英语（四）", 2, "Chen Min", "外国语学院", "必修", "lang"),
    ("MATH2032", "离散数学", 3.5, "孙立", "信息科学与工程学院", "必修", "math"),
    ("CS3011", "计算机网络", 3.5, "赵东", "信息科学与工程学院", "必修", "cs"),
    ("CS3021", "算法设计与分析", 3, "周涛", "信息科学与工程学院", "必修", "cs"),
    ("CS3031", "操作系统", 4, "吴敏", "信息科学与工程学院", "必修", "cs"),
    ("MATH2042", "概率论与数理统计", 3.5, "何秀", "信息科学与工程学院", "必修", "math"),
    ("CS3099", "人工智能导论", 2, "林一", "信息科学与工程学院", "选修", "cs"),
    ("HS2012", "中国近现代史纲要", 3, "徐平", "马克思主义学院", "必修", "hum"),
    ("CS2062", "数据库系统实验", 1.5, "郑好", "信息科学与工程学院", "实践", "lab"),
    ("ARCH2101", "建筑设计基础（一）", 6, "王小禾", "建筑与艺术学院", "必修", "hum"),
    ("ARCH2201", "建筑制图", 3, "李瑞安", "建筑与艺术学院", "必修", "hum"),
    ("ARCH2301", "建筑史（外国）", 2, "顾远", "建筑与艺术学院", "必修", "hum"),
    ("ARCH2401", "阴影透视", 2, "阮青", "建筑与艺术学院", "必修", "lab"),
    ("ART2501", "美术实习", 2, "宋珂", "建筑与艺术学院", "实践", "lab"),
    ("PE2031", "体育（三）", 1, "陈毅", "信息科学与工程学院", "必修", "pe"),
    # 历学期课程：enrollments.course_code 有外键，MySQL 侧必须先建行再灌成绩
    ("MATH2031", "高等数学（上）", 5, "王建国", "信息科学与工程学院", "必修", "math"),
    ("CS1011", "C 语言程序设计", 4, "李慧", "信息科学与工程学院", "必修", "cs"),
    ("MATH1021", "线性代数", 3, "许文", "信息科学与工程学院", "必修", "math"),
    ("PHY1031", "大学物理（上）", 4, "康宁", "信息科学与工程学院", "必修", "lab"),
    ("CS1001", "计算机导论", 2, "周涛", "信息科学与工程学院", "必修", "cs"),
    ("HS1011", "思想道德与法治", 3, "马原", "马克思主义学院", "必修", "hum"),
    ("PE1011", "体育（一）", 1, "陈毅", "信息科学与工程学院", "必修", "pe"),
    ("FL1033", "大学英语（三）", 2, "Wang Fang", "外国语学院", "必修", "lang"),
    ("CS1041", "数字逻辑", 3, "吴敏", "信息科学与工程学院", "必修", "cs"),
    ("PHY1032", "大学物理（下）", 3.5, "康宁", "信息科学与工程学院", "必修", "lab"),
    ("CS2042", "面向对象程序设计", 3, "李慧", "信息科学与工程学院", "必修", "cs"),
    ("PE1012", "体育（二）", 1, "陈毅", "信息科学与工程学院", "必修", "pe"),
    ("ARCH2100", "建筑设计基础（上）", 6, "王小禾", "建筑与艺术学院", "必修", "hum"),
    ("ARCH2200", "建筑制图（上）", 3, "李瑞安", "建筑与艺术学院", "必修", "hum"),
    ("ART2400", "素描基础", 2, "宋珂", "建筑与艺术学院", "必修", "lab"),
    ("ARCH2501", "建筑力学", 3.5, "顾远", "建筑与艺术学院", "必修", "math"),
    ("ART2300", "建筑写生", 2, "宋珂", "建筑与艺术学院", "实践", "lab"),
    ("ARCH2400", "阴影透视（上）", 2, "阮青", "建筑与艺术学院", "必修", "hum"),
]

# (student_id, code, course_name, term, credits, score, teacher)
ENROLLMENTS = [
    ("20230001", "MATH2031", "高等数学（上）", "2025 秋", 5, 91, "王建国"),
    ("20230001", "CS1011", "C 语言程序设计", "2025 秋", 4, 95, "李慧"),
    ("20230001", "MATH1021", "线性代数", "2025 秋", 3, 84, "许文"),
    ("20230001", "PHY1031", "大学物理（上）", "2025 秋", 4, 56, "康宁"),
    ("20230001", "CS1001", "计算机导论", "2025 秋", 2, 82, "周涛"),
    ("20230001", "HS1011", "思想道德与法治", "2025 秋", 3, 90, "马原"),
    ("20230001", "PE1011", "体育（一）", "2025 秋", 1, 0, "陈毅"),
    ("20230001", "FL1033", "大学英语（三）", "2025 秋", 2, 89, "Wang Fang"),
    ("20230001", "CS1041", "数字逻辑", "2026 春", 3, 78, "吴敏"),
    ("20230001", "PHY1032", "大学物理（下）", "2026 春", 3.5, 83, "康宁"),
    ("20230001", "CS2042", "面向对象程序设计", "2026 春", 3, 92, "李慧"),
    ("20230001", "PE1012", "体育（二）", "2026 春", 1, 88, "陈毅"),
    ("20230001", "CS2052", "数据结构（暑期补习）", "2026 春", 4, 87, "李慧"),
    ("20230007", "MATH2031", "高等数学（上）", "2025 秋", 5, 88, "王建国"),
    ("20230007", "CS1011", "C 语言程序设计", "2025 秋", 4, 91, "李慧"),
    ("20230007", "MATH1021", "线性代数", "2025 秋", 3, 79, "许文"),
    ("20230007", "PHY1031", "大学物理（上）", "2025 秋", 4, 72, "康宁"),
    ("20230007", "CS1001", "计算机导论", "2025 秋", 2, 85, "周涛"),
    ("20230007", "HS1011", "思想道德与法治", "2025 秋", 3, 90, "马原"),
    ("20230007", "PE1011", "体育（一）", "2025 秋", 1, 86, "陈毅"),
    ("20230007", "FL1033", "大学英语（三）", "2025 秋", 2, 84, "Wang Fang"),
    ("20230007", "CS1041", "数字逻辑", "2026 春", 3, 81, "吴敏"),
    ("20230007", "PHY1032", "大学物理（下）", "2026 春", 3.5, 88, "康宁"),
    ("20230007", "CS2042", "面向对象程序设计", "2026 春", 3, 90, "李慧"),
    ("20230007", "PE1012", "体育（二）", "2026 春", 1, 85, "陈毅"),
    ("20230007", "CS2052", "数据结构（暑期补习）", "2026 春", 4, 93, "李慧"),
    ("20230002", "ARCH2100", "建筑设计基础（上）", "2025 秋", 6, 85, "王小禾"),
    ("20230002", "ARCH2200", "建筑制图（上）", "2025 秋", 3, 78, "李瑞安"),
    ("20230002", "ART2400", "素描基础", "2025 秋", 2, 90, "宋珂"),
    ("20230002", "ARCH2501", "建筑力学", "2026 春", 3.5, 72, "顾远"),
    ("20230002", "ART2300", "建筑写生", "2026 春", 2, 88, "宋珂"),
    ("20230002", "ARCH2400", "阴影透视（上）", "2026 春", 2, 81, "阮青"),
]

# (student_id, code, course_name, weekday, start, end, room, teacher, weeks_from, weeks_to, term)
SECTIONS_CS = [
    ("MATH2041", "高等数学（下）", 1, 1, 2, "主楼 A302", "王建国", 1, 16),
    ("CS2052", "数据结构", 1, 3, 4, "实验楼 B101", "李慧", 1, 16),
    ("PE2061", "体育（篮球）", 1, 7, 8, "风雨球馆 2 号场", "陈毅", 2, 17),
    ("FL2034", "大学英语（四）", 2, 1, 2, "外语楼 C203", "Chen Min", 1, 14),
    ("MATH2032", "离散数学", 2, 5, 6, "主楼 A205", "孙立", 1, 16),
    ("CS3011", "计算机网络", 3, 3, 4, "主楼 A415", "赵东", 3, 18),
    ("CS3021", "算法设计与分析", 3, 5, 6, "实验楼 B207", "周涛", 3, 18),
    ("CS3031", "操作系统", 4, 1, 2, "主楼 A302", "吴敏", 4, 19),
    ("MATH2042", "概率论与数理统计", 4, 3, 4, "主楼 A205", "何秀", 4, 19),
    ("CS3099", "人工智能导论", 4, 7, 8, "实验楼 B305", "林一", 5, 16),
    ("HS2012", "中国近现代史纲要", 5, 1, 2, "文渊楼报告厅", "徐平", 1, 14),
    ("CS2062", "数据库系统实验", 5, 5, 6, "实验楼 B108", "郑好", 6, 18),
]
SECTIONS_ARCH = [
    ("ARCH2101", "建筑设计基础（一）", 1, 1, 4, "建筑馆 302 画室", "王小禾", 1, 16),
    ("ARCH2201", "建筑制图", 2, 1, 2, "建筑馆 201", "李瑞安", 1, 16),
    ("ARCH2301", "建筑史（外国）", 2, 3, 4, "建筑馆 报告厅", "顾远", 1, 14),
    ("ARCH2401", "阴影透视", 3, 5, 6, "建筑馆 208", "阮青", 3, 18),
    ("ART2501", "美术实习", 4, 1, 4, "美术馆 地下画室", "宋珂", 6, 12),
    ("PE2031", "体育（三）", 5, 7, 8, "风雨球馆 1 号场", "陈毅", 2, 17),
]

BOOKS = {
    "算法": ("TP301.6 / C24", "三楼自然科学借阅区"),
    "CSAPP": ("TP368.1 / Z33", "三楼自然科学借阅区"),
    "数据库": ("TP311.13 / A25", "三楼自然科学借阅区"),
    "人类简史": ("K02 / H44", "五楼人文社科借阅区"),
    "建筑空间": ("TU-86 / L12", "二楼建筑艺术借阅区"),
    "建构文化": ("TU26 / F33", "二楼建筑艺术借阅区"),
    "费马": ("O1-49 / S21", "三楼自然科学借阅区"),
}


def points(score: float) -> float:
    if score < 60:
        return 0.0
    return round(min((score - 50) / 10, 5), 1)


def dt(days: int, hour: int, minute: int = 0) -> str:
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")


async def seed_academic(db: Database) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sid, name, major, cls, college in STUDENTS:
        await db.execute(
            "INSERT INTO students (student_id, name, password_hash, major, class_name, college)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(student_id) DO UPDATE SET"
            " name=excluded.name, major=excluded.major, class_name=excluded.class_name,"
            " college=excluded.college",
            (sid, name, hash_password(SEED_PASSWORD), major, cls, college))
    counts["students"] = len(STUDENTS)

    for code, name, credits, teacher, college, kind, domain in COURSES:
        await db.execute(
            "INSERT INTO courses (course_code, course_name, credits, teacher, college, kind, domain)"
            " VALUES (?,?,?,?,?,?,?) ON CONFLICT(course_code) DO UPDATE SET"
            " course_name=excluded.course_name, credits=excluded.credits, teacher=excluded.teacher,"
            " college=excluded.college, kind=excluded.kind, domain=excluded.domain",
            (code, name, credits, teacher, college, kind, domain))
    counts["courses"] = len(COURSES)

    for sid, code, name, term, credits, score, teacher in ENROLLMENTS:
        await db.execute(
            "INSERT INTO enrollments (student_id, course_code, course_name, term, credits, score,"
            " grade_points, teacher) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(student_id, course_code, term) DO UPDATE SET"
            " course_name=excluded.course_name, credits=excluded.credits, score=excluded.score,"
            " grade_points=excluded.grade_points, teacher=excluded.teacher",
            (sid, code, name, term, credits, score, points(score), teacher))
    counts["enrollments"] = len(ENROLLMENTS)

    n = 0
    for sid in ("20230001", "20230007"):
        for code, name, day, s, e, room, teacher, wf, wt in SECTIONS_CS:
            await db.execute(
                "INSERT INTO course_sections (student_id, course_code, course_name, weekday,"
                " start_period, end_period, room, teacher, weeks_from, weeks_to, term)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, code, name, day, s, e, room, teacher, wf, wt, "2026 秋"))
            n += 1
    for code, name, day, s, e, room, teacher, wf, wt in SECTIONS_ARCH:
        await db.execute(
            "INSERT INTO course_sections (student_id, course_code, course_name, weekday,"
            " start_period, end_period, room, teacher, weeks_from, weeks_to, term)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("20230002", code, name, day, s, e, room, teacher, wf, wt, "2026 秋"))
        n += 1
    counts["course_sections"] = n

    makeups = [
        ("20230001", "大学物理（上）", "PHY1031", "补考", "期末 56 分，未达 60 分线",
         dt(8, 9), "主楼 A102", "已报名", None, None),
        ("20230001", "体育（一）", "PE1011", "重修", "缺考，成绩记为 0 分",
         dt(22, 14), "风雨球馆 1 号场", "待缴费", None, None),
        ("20230001", "概率论与数理统计", "MATH2042", "重修", "上学期未选，本学期补选",
         dt(4, 17), "线上教务系统", "报名中", 23, 120),
    ]
    for row in makeups:
        await db.execute(
            "INSERT INTO makeup_items (student_id, course_name, course_code, kind, reason,"
            " scheduled_at, place, status, seats_left, seats_total) VALUES (?,?,?,?,?,?,?,?,?,?)",
            row)
    counts["makeup_items"] = len(makeups)

    loans = [
        ("20230001", "算法导论（第三版）上册", *BOOKS["算法"], dt(2, 20)),
        ("20230001", "深入理解计算机系统（第 3 版）", *BOOKS["CSAPP"], dt(-3, 20)),
        ("20230001", "数据库系统概念（第 7 版）", *BOOKS["数据库"], dt(11, 20)),
        ("20230001", "人类简史：从动物到上帝", *BOOKS["人类简史"], dt(6, 20)),
        ("20230002", "建筑空间组合论", *BOOKS["建筑空间"], dt(9, 20)),
        ("20230002", "建构文化研究", *BOOKS["建构文化"], dt(-1, 20)),
        ("20230007", "费马大定理：一个困惑了世间智者 358 年的谜", *BOOKS["费马"], dt(5, 20)),
    ]
    for sid, title, call_no, shelf, due in loans:
        await db.execute(
            "INSERT INTO library_loans (student_id, title, call_no, due_at, shelf)"
            " VALUES (?,?,?,?,?)", (sid, title, call_no, due, shelf))
    counts["library_loans"] = len(loans)
    return counts


async def main() -> None:
    settings = get_settings()
    db = build_database(settings)
    await run_migrations(db)
    counts = await seed_academic(db)
    print(f"seed 完成（{db.dialect}）: {counts}")


if __name__ == "__main__":
    asyncio.run(main())
```

注意：`course_sections` 与 `makeup_items`/`library_loans` 的幂等靠"先清后灌"——这两个表没有唯一键，重复 INSERT 会叠行。在 `seed_academic` 开头加：

```python
    await db.execute("DELETE FROM course_sections")
    await db.execute("DELETE FROM makeup_items")
    await db.execute("DELETE FROM library_loans")
```

（`students`/`courses`/`enrollments` 有主键或唯一键，走 UPSERT；这三个表是"个人当前态"，全量替换语义正确。测试里的幂等断言因此成立。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_seed_academic.py -v`
Expected: 2 passed

- [ ] **Step 5: 命令行灌 sqlite 验证**

```bash
rm -f backend/data/campus.db
cd backend && uv run python ../scripts/seed_academic.py
# 期望：seed 完成（sqlite）: {'students': 3, 'courses': 36, 'enrollments': 32, 'course_sections': 30, 'makeup_items': 3, 'library_loans': 7}
```

- [ ] **Step 6: 提交**

```bash
git add scripts/seed_academic.py backend/tests/test_seed_academic.py
git commit -m "feat(seed): 三账号异构教务数据脚本，相对运行日推导真日期"
```

---

### Task 5: `/api/*` 四个教务数据端点

**Files:**
- Create: `backend/app/api/academic.py`
- Modify: `backend/app/main.py`（挂 `academic_router`）
- Test: `backend/tests/test_academic_api.py`

**Interfaces:**
- Consumes: `require_student`（S1）、`app.state.db`（Task 3）、Task 4 的表与数据
- Produces（前端 Task 6 逐字依赖这四处形状，键名 camelCase 以对齐前端现有类型）：
  - `GET /api/grades` → `{"grades": [{"name","code","credits","score","term"}]}`
  - `GET /api/schedule` → `{"courses": [{"name","code","teacher","room","day","periods","credits","weeks","kind","domain"}]}`，`periods` 为整数数组，`weeks` 为 `"3-18"` 串
  - `GET /api/makeup` → `{"items": [{"course","code","type","reason","when","place","status","seats"}]}`，`seats` 可为 `null`
  - `GET /api/loans` → `{"items": [{"title","callNo","due","daysLeft","place"}]}`
  - 四端点均 `Depends(require_student)`，未登录 401

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_academic_api.py
import asyncio
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed_academic import seed_academic  # noqa: E402

from app.api.academic import router as academic_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.auth.rate_limit import LoginGuard  # noqa: E402
from app.auth.session import SessionStore  # noqa: E402
from app.auth.students import build_student_repository  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.migrations import init_sqlite  # noqa: E402

WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2} 周[一二三四五六日] \d{2}:\d{2}$")


@pytest.fixture
def client(tmp_path):
    db = asyncio.run(init_sqlite(tmp_path / "campus.db"))
    asyncio.run(seed_academic(db))

    app = FastAPI()
    app.state.settings = Settings()
    app.state.db = db
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.include_router(auth_router)
    app.include_router(academic_router)
    with TestClient(app) as c:
        yield c


def _login(c, sid):
    assert c.post("/auth/login", json={"student_id": sid, "password": "demo1234"}).status_code == 200


def test_四端点未登录一律401(client):
    for url in ("/api/grades", "/api/schedule", "/api/makeup", "/api/loans"):
        assert client.get(url).status_code == 401, url


def test_成绩含挂科行且只含本人(client):
    _login(client, "20230001")
    rows = client.get("/api/grades").json()["grades"]
    assert len(rows) == 13
    assert {r["name"] for r in rows} >= {"数据结构（暑期补习）", "大学物理（上）"}
    assert next(r for r in rows if r["name"] == "数据结构（暑期补习）")["score"] == 87
    assert next(r for r in rows if r["name"] == "大学物理（上）")["score"] == 56
    assert set(rows[0]) == {"name", "code", "credits", "score", "term"}


def test_课表形状periods与weeks(client):
    _login(client, "20230001")
    courses = client.get("/api/schedule").json()["courses"]
    assert len(courses) == 12
    first = next(c for c in courses if c["code"] == "MATH2041")
    assert first["day"] == 1 and first["periods"] == [1, 2]
    assert first["weeks"] == "1-16" and first["kind"] == "必修" and first["domain"] == "math"


def test_补考时间已格式化且名额有文案(client):
    _login(client, "20230001")
    items = client.get("/api/makeup").json()["items"]
    assert len(items) == 3
    assert all(WEEK_RE.match(i["when"]) for i in items if i["status"] != "报名中")
    opening = next(i for i in items if i["status"] == "报名中")
    assert opening["when"].startswith("报名截止 ")
    assert opening["seats"] == "剩 23 / 120"


def test_借阅含逾期且daysLeft由服务端算(client):
    _login(client, "20230001")
    items = client.get("/api/loans").json()["items"]
    assert len(items) == 4
    assert any(i["daysLeft"] < 0 for i in items)
    assert all(WEEK_RE.match(i["due"]) for i in items)
    assert set(items[0]) == {"title", "callNo", "due", "daysLeft", "place"}


def test_陈默是建筑学数据与周晓楠无交集(client):
    _login(client, "20230002")
    mine = {g["code"] for g in client.get("/api/grades").json()["grades"]}
    assert len(client.get("/api/schedule").json()["courses"]) == 6
    assert client.get("/api/makeup").json()["items"] == []
    _login(client, "20230001")
    theirs = {g["code"] for g in client.get("/api/grades").json()["grades"]}
    assert mine.isdisjoint(theirs)


def test_同名课程分数按人隔离(client):
    _login(client, "20230007")
    lin = next(g for g in client.get("/api/grades").json()["grades"]
               if g["name"] == "数据结构（暑期补习）")
    assert lin["score"] == 93  # 周晓楠同门课是 87
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_academic_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.academic'`

- [ ] **Step 3: 写端点**

```python
# backend/app/api/academic.py
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth.deps import require_student
from ..auth.students import Student

router = APIRouter(prefix="/api")

_WEEKDAYS = "一二三四五六日"


def _as_dt(raw: Any) -> datetime:
    """MySQL 驱动给 datetime 对象，SQLite 给字符串——两侧都要能格式化。"""
    if isinstance(raw, datetime):
        return raw
    return datetime.strptime(str(raw)[:16], "%Y-%m-%d %H:%M")


def _stamp(raw: Any) -> str:
    """教务系统式日期串：2026-09-28 周一 09:00"""
    d = _as_dt(raw)
    return f"{d:%Y-%m-%d} 周{_WEEKDAYS[d.weekday()]} {d:%H:%M}"


def _md(raw: Any) -> str:
    return _as_dt(raw).strftime("%m-%d")


def _days_left(raw: Any) -> int:
    """今天 0 点起算的剩余天数，负数为已逾期（不落冗余列，查询时算）。"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (_as_dt(raw) - today).days


@router.get("/grades")
async def grades(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT course_name, course_code, credits, score, term FROM enrollments"
        " WHERE student_id = ? ORDER BY term, course_name", (student.student_id,))
    return {"grades": [{"name": r["course_name"], "code": r["course_code"],
                        "credits": r["credits"], "score": r["score"],
                        "term": r["term"]} for r in rows]}


@router.get("/schedule")
async def schedule(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT s.course_name, s.course_code, s.teacher, s.room, s.weekday,"
        " s.start_period, s.end_period, s.weeks_from, s.weeks_to,"
        " c.credits, c.kind, c.domain"
        " FROM course_sections s JOIN courses c ON c.course_code = s.course_code"
        " WHERE s.student_id = ? ORDER BY s.weekday, s.start_period",
        (student.student_id,))
    return {"courses": [
        {"name": r["course_name"], "code": r["course_code"], "teacher": r["teacher"],
         "room": r["room"], "day": r["weekday"],
         "periods": list(range(r["start_period"], r["end_period"] + 1)),
         "credits": r["credits"], "weeks": f"{r['weeks_from']}-{r['weeks_to']}",
         "kind": r["kind"], "domain": r["domain"]} for r in rows]}


@router.get("/makeup")
async def makeup(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT course_name, course_code, kind, reason, scheduled_at, place, status,"
        " seats_left, seats_total FROM makeup_items WHERE student_id = ?"
        " ORDER BY scheduled_at", (student.student_id,))
    items = []
    for r in rows:
        items.append({
            "course": r["course_name"], "code": r["course_code"], "type": r["kind"],
            "reason": r["reason"],
            "when": (f"报名截止 {_md(r['scheduled_at'])} 17:00"
                     if r["status"] == "报名中" else _stamp(r["scheduled_at"])),
            "place": r["place"], "status": r["status"],
            "seats": (f"剩 {r['seats_left']} / {r['seats_total']}"
                      if r["seats_left"] is not None else None),
        })
    return {"items": items}


@router.get("/loans")
async def loans(request: Request, student: Student = Depends(require_student)):
    rows = await request.app.state.db.fetch_all(
        "SELECT title, call_no, due_at, shelf FROM library_loans"
        " WHERE student_id = ? AND returned_at IS NULL ORDER BY due_at",
        (student.student_id,))
    return {"items": [
        {"title": r["title"], "callNo": r["call_no"], "due": _stamp(r["due_at"]),
         "daysLeft": _days_left(r["due_at"]), "place": r["shelf"]} for r in rows]}
```

> 日期格式化与 `days_left` 一律在 Python 侧算，不用 `DATEDIFF`/`strftime` 的 SQL 方言函数——这是"两种 `DB_BACKEND` 返回 JSON 逐字段一致"这条验收的关键前提。

`backend/app/main.py`：import 加 `from .api.academic import router as academic_router`；在 `app.include_router(chat_router)` 之后加 `app.include_router(academic_router)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_academic_api.py -v`
Expected: 7 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `cd backend && uv run pytest -q`
Expected: 全绿

```bash
git add backend/app/api/academic.py backend/app/main.py backend/tests/test_academic_api.py
git commit -m "feat(api): /api/grades|schedule|makeup|loans 四端点从库读教务数据"
```

---

### Task 6: 前端四页与首页改读 `/api/*`，seed.ts 退成展示常量

**Files:**
- Modify: `frontend/src/types.ts`（加业务类型，`Domain`/`DOMAIN_LABELS` 从 seed 迁入）
- Modify: `frontend/src/data/seed.ts`（删业务数据，只留展示常量与纯函数；`nowPeriod`/`todayCourses`/`nextUp` 改为接收 courses 参数）
- Create: `frontend/src/composables/useResource.ts`
- Modify: `frontend/vite.config.ts`（代理补 `/api`）
- Modify: `frontend/src/components/TimetableGrid.vue`、`frontend/src/views/{Grades,Schedule,Makeup,Library,Home}View.vue`、`frontend/src/App.vue`（`student` → `termMeta`）
- Create: `frontend/tests/useResource.test.ts`

**Interfaces:**
- Consumes: Task 5 的四个端点响应形状（逐字一致）
- Produces: `useResource<T>(url) -> { data: Ref<T|null>, loading: Ref<boolean>, error: Ref<string>, reload(): Promise<void> }`，`data`/`loading`/`error`/`reload` 是后续各页唯一的数据入口

- [ ] **Step 1: 代理与类型**

`frontend/vite.config.ts` 的 proxy 对象加一行 `'/api': 'http://localhost:8000',`。

`frontend/src/types.ts` 末尾追加（`Domain` 与其标签从 `seed.ts` 迁来，避免 `types.ts` 反向依赖数据文件）：

```ts
/** 学科域：课表配色的依据，颜色在此承载真实信息而非装饰 */
export type Domain = 'math' | 'cs' | 'lang' | 'pe' | 'hum' | 'lab'

export const DOMAIN_LABELS: Record<Domain, string> = {
  math: '数学',
  cs: '计算机',
  lang: '外语',
  pe: '体育',
  hum: '人文',
  lab: '实践',
}

/** 以下四个接口逐字对应 Task 5 的 /api/* 响应字段 */
export interface GradeRow {
  name: string
  code: string
  credits: number
  score: number
  term: string
}

export interface CourseEntry {
  name: string
  code: string
  teacher: string
  room: string
  /** 1=周一 … 5=周五 */
  day: number
  /** 节次序号，连堂写成 [3, 4] */
  periods: number[]
  credits: number
  weeks: string
  kind: '必修' | '选修' | '实践'
  domain: Domain
}

export interface MakeupItem {
  course: string
  code: string
  type: '补考' | '重修'
  reason: string
  when: string
  place: string
  status: '已报名' | '待缴费' | '报名中'
  seats: string | null
}

export interface LoanItem {
  title: string
  callNo: string
  due: string
  /** 距应还日剩余天数，负数为已逾期 */
  daysLeft: number
  place: string
}
```

- [ ] **Step 2: seed.ts 收缩成展示常量**

`frontend/src/data/seed.ts` 整文件替换为下面内容。**删掉**的是：`student`（拆成 `termMeta`）、`courses`、`grades`、`makeup`、`loans`、`libraryStats`（改名 `libraryMeta`）、`gpa`/`creditsDone`/`failedCount` 三个常量、`GradeRow`/`CourseEntry`/`MakeupItem`/`LoanItem`/`Domain`/`DOMAIN_LABELS` 六个类型与常量（迁到 `types.ts`）、`fromToday`/`stamp`（日期格式化已由 Task 5 的 `_stamp` 在服务端做）。**保留** `md`——`TimetableGrid` 用它把"周一"落到具体日期，属展示逻辑而非业务数据。

```ts
/** 展示常量与纯函数。课表、成绩、借阅等业务数据一律来自 /api/*（spec 8.3）。 */

/** 教务系统式的月日读数：09-28 */
export function md(d: Date): string {
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export interface Period {
  index: number
  start: string
  end: string
  label: string
}

/** 真实高校作息：上下午各两连节，傍晚两节体育/选修 */
export const periods: Period[] = [
  { index: 1, start: '08:00', end: '08:50', label: '第 1 节' },
  { index: 2, start: '08:50', end: '09:40', label: '第 2 节' },
  { index: 3, start: '10:00', end: '10:50', label: '第 3 节' },
  { index: 4, start: '10:50', end: '11:40', label: '第 4 节' },
  { index: 5, start: '14:00', end: '14:50', label: '第 5 节' },
  { index: 6, start: '14:50', end: '15:40', label: '第 6 节' },
  { index: 7, start: '16:20', end: '17:10', label: '第 7 节' },
  { index: 8, start: '17:10', end: '18:00', label: '第 8 节' },
]

export const weekdays = ['周一', '周二', '周三', '周四', '周五']

/** 学期抬头与周次：仿真环境无教务日历，作为展示常量固定（S3 之后再接真实校历） */
export const termMeta = {
  semester: '2026–2027 学年 第一学期',
  week: 6,
  totalWeeks: 19,
  creditsRequired: 165,
}

/** 图书馆馆情常量：座位与罚款额度不是学生个人数据 */
export const libraryMeta = {
  quota: 10,
  seatsOpen: 47,
  seatsTotal: 220,
  fine: '6.00 元',
}

/** 5.0 分制：绩点 = (分数 − 50) / 10，90 分以上封顶 5.0 */
export function points(score: number): number {
  if (score < 60) return 0
  return Math.round(Math.min((score - 50) / 10, 5) * 10) / 10
}

export function gpaOf(grades: GradeRow[]): number {
  if (!grades.length) return 0
  const total = grades.reduce((s, g) => s + g.credits, 0)
  const weighted = grades.reduce((s, g) => s + points(g.score) * g.credits, 0)
  return Math.round((weighted / total) * 100) / 100
}

export function creditsDoneOf(grades: GradeRow[]): number {
  return Math.round(grades.reduce((s, g) => s + g.credits, 0) * 10) / 10
}

/** 把当前时刻映射到节次：课间返回 null，但给出下一节的定位 */
export function nowPeriod(courses: CourseEntry[]): {
  index: number | null
  next: { course: CourseEntry; period: Period } | null
} {
  const now = new Date()
  const day = now.getDay()
  const mins = now.getHours() * 60 + now.getMinutes()
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))

  let index: number | null = null
  for (const p of periods) {
    if (mins >= toMin(p.start) && mins < toMin(p.end)) index = p.index
  }

  const today = courses.filter((c) => c.day === day)
  let next: { course: CourseEntry; period: Period } | null = null
  for (const c of today) {
    const first = periods.find((p) => p.index === c.periods[0])
    if (first && toMin(first.start) > mins) {
      if (!next || toMin(first.start) < toMin(periods.find((p) => p.index === next!.course.periods[0])!.start)) {
        next = { course: c, period: first }
      }
    }
  }
  return { index, next }
}

export function todayCourses(courses: CourseEntry[]): CourseEntry[] {
  const day = new Date().getDay()
  return courses
    .filter((c) => c.day === day)
    .sort((a, b) => a.periods[0] - b.periods[0])
}

/** 未来 7 天内第一节还没上的课，用于"此刻无课"时给出真正的下一步 */
export function nextUp(courses: CourseEntry[]): { course: CourseEntry; period: Period; dayOffset: number } | null {
  const now = new Date()
  const mins = now.getHours() * 60 + now.getMinutes()
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))
  const today = now.getDay()

  for (let offset = 0; offset < 7; offset++) {
    const day = offset === 0 ? today : ((today - 1 + offset) % 7) + 1
    if (day > 5) continue
    const list = courses
      .filter((c) => c.day === day)
      .map((c) => ({ c, p: periods.find((x) => x.index === c.periods[0])! }))
      .filter((x) => offset > 0 || toMin(x.p.start) > mins)
      .sort((a, b) => a.p.index - b.p.index)
    if (list.length) return { course: list[0].c, period: list[0].p, dayOffset: offset }
  }
  return null
}
```

在该文件顶部加上类型 import：

```ts
import type { CourseEntry, GradeRow } from '../types'
```

- [ ] **Step 3: 写 useResource 失败测试**

```ts
// frontend/tests/useResource.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

const signOut = vi.fn()
const push = vi.fn()

beforeEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
  signOut.mockClear()
  push.mockClear()
  vi.doMock('../src/composables/useAuth', () => ({ useAuth: () => ({ signOut }) }))
  vi.doMock('../src/router', () => ({
    default: { push, currentRoute: { value: { fullPath: '/academic/grades' } } },
  }))
})

async function use() {
  const { useResource } = await import('../src/composables/useResource')
  return useResource<{ grades: { name: string }[] }>('/api/grades')
}

describe('useResource', () => {
  it('成功时填充 data、清空 error、结束 loading', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 200, ok: true, json: async () => ({ grades: [{ name: '高等数学' }] }),
    })))
    const r = await use()
    await r.reload()
    expect(r.data.value?.grades[0].name).toBe('高等数学')
    expect(r.error.value).toBe('')
    expect(r.loading.value).toBe(false)
  })

  it('非 2xx 时置错误文案且 data 保持空', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 500, ok: false })))
    const r = await use()
    await r.reload()
    expect(r.data.value).toBeNull()
    expect(r.error.value).toContain('加载失败')
    expect(r.loading.value).toBe(false)
  })

  it('网络异常同样进错误态不抛出', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom') }))
    const r = await use()
    await expect(r.reload()).resolves.toBeUndefined()
    expect(r.error.value).toContain('加载失败')
  })

  it('401 清登录态并跳登录页，带上 next', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 401, ok: false })))
    const r = await use()
    await r.reload()
    expect(signOut).toHaveBeenCalledTimes(1)
    expect(push).toHaveBeenCalledWith({ path: '/login', query: { next: '/academic/grades' } })
    expect(r.error.value).toBe('')
    expect(r.loading.value).toBe(false)
  })

  it('请求带 credentials: include', async () => {
    const fetchMock = vi.fn(async () => ({ status: 200, ok: true, json: async () => ({ grades: [] }) }))
    vi.stubGlobal('fetch', fetchMock)
    const r = await use()
    await r.reload()
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })
})
```

Run: `cd frontend && npx vitest run tests/useResource.test.ts` → Expected: FAIL（模块不存在）

- [ ] **Step 4: 写 useResource**

```ts
// frontend/src/composables/useResource.ts
import { ref, type Ref } from 'vue'
import router from '../router'
import { useAuth } from './useAuth'

export interface Resource<T> {
  data: Ref<T | null>
  loading: Ref<boolean>
  error: Ref<string>
  reload: () => Promise<void>
}

/** 页面数据的唯一出口：组件不发请求（MVP spec 5.6 的边界）。 */
export function useResource<T>(url: string): Resource<T> {
  const data = ref<T | null>(null)
  const loading = ref(true)
  const error = ref('')

  async function reload(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const resp = await fetch(url, { credentials: 'include' })
      if (resp.status === 401) {
        // 会话已不可用，再打 logout 没意义：只清本地态并跳登录
        useAuth().signOut()
        router.push({ path: '/login', query: { next: router.currentRoute.value.fullPath } })
        return
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      data.value = (await resp.json()) as T
    } catch {
      error.value = '加载失败，请确认后端已启动后重试'
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, reload }
}
```

Run: `cd frontend && npx vitest run tests/useResource.test.ts` → Expected: 5 passed

- [ ] **Step 5: TimetableGrid 去掉 seed 依赖**

`frontend/src/components/TimetableGrid.vue` 的 `<script setup>` 三处改动：

```ts
import { computed } from 'vue'
import { md, nowPeriod, periods, weekdays } from '../data/seed'
import type { CourseEntry } from '../types'

const props = withDefaults(defineProps<{
  days: number[]
  detailed?: boolean
  items?: CourseEntry[]
}>(), { detailed: false, items: () => [] })

const shown = computed(() => props.items)

const dayNow = computed(() => new Date().getDay())

const live = computed(() => nowPeriod(shown.value))
```

（`items` 默认值从 `courses` 改 `[]`：调用方必须显式传，缺数据时是"格子空白"而非"读到别人的 seed"。`template` 与 `style` 不动。）

两个调用方随之传参：

- `ScheduleView.vue`：已是 `:items="shown"`，不动。
- `HomeView.vue`：`<TimetableGrid v-if="agenda.length" :days="[jsDay]" :items="agenda" detailed class="today" />`（加 `:items="agenda"`）。

- [ ] **Step 6: 三态外壳（四个教务页共用同一段）**

每页在 `<div class="page-body">` 之后紧跟插入下面这段，并把该页原有区块整体包进 `<template v-else>`。样式在每页 `<style scoped>` 末尾追加同一份 `.state-*` 规则（复制即可，四页一致）。

```html
    <div v-if="loading" class="state-block" role="status">
      <p class="state-title">正在读取教务数据…</p>
      <div class="state-skeleton"><span /><span /><span /></div>
    </div>
    <div v-else-if="error" class="state-block" role="alert">
      <p class="state-title">{{ error }}</p>
      <button type="button" class="state-retry" @click="reload">重试</button>
    </div>
    <template v-else>
      <!-- 该页原有区块原样搬进来 -->
    </template>
```

```css
.state-block {
  padding: 34px 20px;
  border: 1px dashed var(--rule-2);
  border-radius: var(--r-md);
  background: var(--card);
  text-align: center;
}

.state-title {
  font-size: 13.5px;
  color: var(--faint);
}

.state-skeleton {
  margin-top: 16px;
  display: grid;
  gap: 8px;
}

.state-skeleton span {
  height: 12px;
  border-radius: 2px;
  background: var(--rule);
}

.state-skeleton span:nth-child(1) { width: 62%; }
.state-skeleton span:nth-child(2) { width: 84%; }
.state-skeleton span:nth-child(3) { width: 45%; }

.state-retry {
  font: inherit;
  font-size: 13px;
  margin-top: 14px;
  padding: 7px 16px;
  color: #fff;
  background: var(--ink);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.state-retry:hover {
  background: var(--seal);
  border-color: var(--seal);
}
```

- [ ] **Step 7: 四页各自的 `<script setup>`**

`GradesView.vue` 整段替换 `<script setup>`（模板里 `student.semester` → `termMeta.semester`、`student.creditsRequired` → `termMeta.creditsRequired`、`student.week` → `termMeta.week`；`<style>` 不动，另在成绩表为空时于 `<template v-else>` 内首个位置插入空态）：

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useResource } from '../composables/useResource'
import { creditsDoneOf, gpaOf, points, termMeta } from '../data/seed'
import type { GradeRow } from '../types'

const { data, loading, error, reload } = useResource<{ grades: GradeRow[] }>('/api/grades')
onMounted(reload)

const grades = computed(() => data.value?.grades ?? [])
const gpa = computed(() => gpaOf(grades.value))
const creditsDone = computed(() => creditsDoneOf(grades.value))
const failedCount = computed(() => grades.value.filter((g) => g.score < 60).length)
const best = computed(() =>
  grades.value.length ? grades.value.reduce((a, b) => (b.score > a.score ? b : a)) : null)
</script>
```

模板里 `{{ best.score }}` 改为 `{{ best?.score ?? '—' }}`。空态（沿用既有 `.empty` 视觉，本页 `<style>` 内补一份 HomeView 的 `.empty` 规则）：

```html
      <div v-if="!grades.length" class="empty">
        <p class="empty-title">还没有开放的成绩</p>
        <p class="empty-hint">成绩公布后会出现在这里。也可以问助手"我的绩点怎么样"。</p>
      </div>
      <section v-else class="panel">
```

`ScheduleView.vue` 的 `<script setup>` 整段替换（模板 `student.semester`/`student.week` → `termMeta.*`）：

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import TimetableGrid from '../components/TimetableGrid.vue'
import { useResource } from '../composables/useResource'
import { periods, termMeta, weekdays } from '../data/seed'
import { DOMAIN_LABELS, type CourseEntry, type Domain } from '../types'

const { data, loading, error, reload } = useResource<{ courses: CourseEntry[] }>('/api/schedule')
onMounted(reload)

const courses = computed(() => data.value?.courses ?? [])
const activeWeek = ref(termMeta.week)
watch(courses, (v) => { if (v.length && activeWeek.value > termMeta.totalWeeks) activeWeek.value = termMeta.week })
const weeks = Array.from({ length: termMeta.totalWeeks }, (_, i) => i + 1)

function inWeek(range: string, week: number): boolean {
  const [start, end] = range.split('-').map(Number)
  return week >= start && week <= (end || start)
}

const shown = computed(() => courses.value.filter((c) => inWeek(c.weeks, activeWeek.value)))
const visibleDomains = computed(() =>
  (Object.keys(DOMAIN_LABELS) as Domain[]).filter((d) => shown.value.some((c) => c.domain === d)),
)
const countOf = (d: Domain) => shown.value.filter((c) => c.domain === d).length
</script>
```

模板改动两处：`student.semester` → `termMeta.semester`、`student.week` → `termMeta.week`；`<TimetableGrid>` 之后加空态：

```html
    <div v-if="!shown.length" class="empty">
      <p class="empty-title">第 {{ activeWeek }} 周没有课</p>
      <p class="empty-hint">换一周看看，或到"首页"问助手下次课是什么时候。</p>
    </div>
```

`MakeupView.vue` 的 `<script setup>` 整段替换（`makeup` → `items`，模板里 `v-for="m in makeup"` → `v-for="m in items"`、`共 {{ makeup.length }} 项` → `共 {{ items.length }} 项`、`student.semester` → `termMeta.semester`）：

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useResource } from '../composables/useResource'
import { termMeta } from '../data/seed'
import type { MakeupItem } from '../types'

const { data, loading, error, reload } = useResource<{ items: MakeupItem[] }>('/api/makeup')
onMounted(reload)

const items = computed(() => data.value?.items ?? [])
const statusStyle: Record<string, string> = {
  已报名: 'is-done',
  待缴费: 'is-wait',
  报名中: 'is-open',
}
</script>
```

空态插在 `.list` 区块之前：

```html
    <div v-if="!items.length" class="empty">
      <p class="empty-title">没有需要办理的补考或重修</p>
      <p class="empty-hint">成绩全部通过。要核对分数可去「成绩查询」。</p>
    </div>
```

`LibraryView.vue` 的 `<script setup>` 整段替换（`loans`→`items`、`libraryStats`→`libraryMeta`；模板里 `l.place` 保持——服务端已把 `shelf` 映射成 `place`）：

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useResource } from '../composables/useResource'
import { libraryMeta, termMeta } from '../data/seed'
import type { LoanItem } from '../types'

const { data, loading, error, reload } = useResource<{ items: LoanItem[] }>('/api/loans')
onMounted(reload)

const items = computed(() => data.value?.items ?? [])
const sorted = computed(() => [...items.value].sort((a, b) => a.daysLeft - b.daysLeft))
const borrowed = computed(() => items.value.length)
const overdueCount = computed(() => items.value.filter((l) => l.daysLeft < 0).length)
const seatPct = computed(() =>
  Math.round((libraryMeta.seatsOpen / libraryMeta.seatsTotal) * 100))

function dayLabel(d: number): string {
  if (d < 0) return `已逾期 ${Math.abs(d)} 天`
  if (d === 0) return '今天应还'
  if (d <= 3) return `${d} 天后应还`
  return `剩 ${d} 天`
}
</script>
```

模板里 `libraryStats.quota - libraryStats.borrowed` → `libraryMeta.quota - borrowed`、`libraryStats.quota` → `libraryMeta.quota`、`libraryStats.fine` → `libraryMeta.fine`、`libraryStats.seatsOpen/seatsTotal` → `libraryMeta.*`、`student.semester` → `termMeta.semester`；表格为空时：

```html
    <div v-if="!items.length" class="empty">
      <p class="empty-title">没有在借的图书</p>
      <p class="empty-hint">全部归还完毕。要查馆藏可以问助手"图书馆有哪些书"。</p>
    </div>
```

- [ ] **Step 8: HomeView 改读四个端点**

`frontend/src/views/HomeView.vue` 的 `<script setup>` 整段替换。三处行为修正：`makeup[0]` 之前必须判空（陈默、林知远都没有补考项）；`gpa`/`creditsDone` 由常量变函数；四个请求任一在途即骨架、任一失败即错误条：

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import TimetableGrid from '../components/TimetableGrid.vue'
import { useAssistant } from '../composables/useAssistant'
import { useResource } from '../composables/useResource'
import {
  creditsDoneOf, gpaOf, libraryMeta, nextUp, nowPeriod, periods, termMeta, todayCourses,
} from '../data/seed'
import type { CourseEntry, GradeRow, LoanItem, MakeupItem } from '../types'

const { ask } = useAssistant()

const scheduleR = useResource<{ courses: CourseEntry[] }>('/api/schedule')
const gradesR = useResource<{ grades: GradeRow[] }>('/api/grades')
const makeupR = useResource<{ items: MakeupItem[] }>('/api/makeup')
const loansR = useResource<{ items: LoanItem[] }>('/api/loans')

function reloadAll() {
  void Promise.all([scheduleR.reload(), gradesR.reload(), makeupR.reload(), loansR.reload()])
}
onMounted(reloadAll)

const courses = computed(() => scheduleR.data.value?.courses ?? [])
const grades = computed(() => gradesR.data.value?.grades ?? [])
const makeup = computed(() => makeupR.data.value?.items ?? [])
const loans = computed(() => loansR.data.value?.items ?? [])

const loading = computed(() =>
  scheduleR.loading.value || gradesR.loading.value || makeupR.loading.value || loansR.loading.value)
const error = computed(() =>
  scheduleR.error.value || gradesR.error.value || makeupR.error.value || loansR.error.value)

const dayNames = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const now = new Date()
const jsDay = now.getDay()
const live = computed(() => nowPeriod(courses.value))
const agenda = computed(() => todayCourses(courses.value))

const gpa = computed(() => gpaOf(grades.value))
const creditsDone = computed(() => creditsDoneOf(grades.value))

/** 首页抬头只说一件事：此刻该干什么 */
const status = computed(() => {
  const idx = live.value.index
  if (idx !== null) {
    const c = agenda.value.find((x) => x.periods.includes(idx))
    const p = periods.find((x) => x.index === idx)!
    return c
      ? { lead: `正在上第 ${idx} 节`, main: c.name, tail: `${p.start}–${p.end} · ${c.room}` }
      : { lead: `第 ${idx} 节`, main: '本节无课', tail: `${p.start}–${p.end} · 可用于自习` }
  }
  if (live.value.next) {
    const { course, period } = live.value.next
    return { lead: `下一节 ${period.start}`, main: course.name, tail: `${course.room} · ${course.teacher}` }
  }
  if (agenda.value.length) {
    return { lead: '今日课程已全部结束', main: `${agenda.value.length} 节课已完成`, tail: nextLine() }
  }
  return { lead: `${dayNames[jsDay]}没有排课`, main: '今天不上课', tail: nextLine() }
})

/** 此刻没课时，最有用的信息是"下一次什么时候上课" */
function nextLine(): string {
  const n = nextUp(courses.value)
  if (!n) return '未来一周没有排课'
  const when = n.dayOffset === 0 ? '今天' : n.dayOffset === 1 ? '明天' : dayNames[(jsDay + n.dayOffset) % 7]
  return `下次课 ${when} ${n.period.start} · ${n.course.name}`
}

const weekPct = computed(() => Math.round((termMeta.week / termMeta.totalWeeks) * 100))
const creditPct = computed(() => Math.round((creditsDone.value / termMeta.creditsRequired) * 100))
const weeklySessions = computed(() => courses.value.reduce((s, c) => s + c.periods.length, 0))

const overdue = computed(() => loans.value.filter((l) => l.daysLeft < 0))
const dueSoon = computed(() => loans.value.filter((l) => l.daysLeft >= 0 && l.daysLeft <= 3))

const reminders = computed(() => {
  const items: { to: string; tag: string; title: string; meta: string; urgent: boolean }[] = []
  const m = makeup.value[0]
  if (m) {
    items.push({ to: '/academic/makeup', tag: m.type, title: m.course,
                 meta: `${m.when} · ${m.place}`, urgent: false })
  }
  if (overdue.value.length) {
    items.push({
      to: '/library', tag: '逾期', title: `${overdue.value.length} 本图书已逾期`,
      meta: `应还 ${overdue.value[0].due.slice(0, 10)} · 罚款 ${libraryMeta.fine}`, urgent: true,
    })
  }
  if (dueSoon.value.length) {
    items.push({
      to: '/library', tag: '应还', title: `${dueSoon.value.length} 本图书 3 日内应还`,
      meta: `最近一本 ${dueSoon.value[0].title}`, urgent: false,
    })
  }
  items.push({ to: '/academic/grades', tag: '成绩', title: `${gpa.value} 平均绩点`,
               meta: `${makeup.value.length} 门课程需补考或重修`, urgent: false })
  return items
})

const prompts = [
  '这学期上什么课',
  '查一下我的成绩',
  '补考什么时候',
  '图书馆还有哪些没还',
]
</script>
```

模板改动四处（`<style>` 不动）：

1. 最外层 `<div class="home">` 内首插三态外壳（Step 6 那段，`@click="reloadAll"`）。
2. `第 {{ student.week }} 周` → `第 {{ termMeta.week }} 周`；`{{ student.week }}/{{ student.totalWeeks }} 周` → `{{ termMeta.week }}/{{ termMeta.totalWeeks }} 周`；`{{ creditsDone }}/{{ student.creditsRequired }}` → `{{ creditsDone }}/{{ termMeta.creditsRequired }}`。
3. `<TimetableGrid v-if="agenda.length" :days="[jsDay]" :items="agenda" detailed class="today" />`。
4. 待办区块加空态兜底：`<ul class="reminders">` 前插 `<p v-if="!reminders.length" class="empty-hint">暂时没有待办。</p>`（`reminders` 至少含绩点一条，此句仅为不变量兜底）。

`seed.ts` 里已经没有 `student` 这个导出（学期与周次改名 `termMeta`），`App.vue` 也要跟着改：

```ts
import { termMeta } from './data/seed'
```

模板里 `第 {{ student.week }} 周 / 共 {{ student.totalWeeks }} 周` → `第 {{ termMeta.week }} 周 / 共 {{ termMeta.totalWeeks }} 周`。

- [ ] **Step 9: 前端全量验证**

```bash
cd frontend && npx vitest run && npm run build
```

Expected: vitest 全绿（含既有 sse/useAuth/useChatStream 三组）；`vue-tsc` 无"未找到导出"类错误——`seed.ts` 里被删的符号若还有引用点，这里必然报，按报错定位改到 `/api` 或 `types.ts`。

Run: `cd frontend && rg "data/seed" src -n`
Expected: 只剩 `periods`/`weekdays`/`points`/`gpaOf`/`creditsDoneOf`/`termMeta`/`libraryMeta`/`md`/`nowPeriod`/`todayCourses`/`nextUp` 这些展示符号的 import，无任何业务数据 import。

- [ ] **Step 10: 端到端手测**

```bash
cd backend && rm -f data/campus.db && DB_BACKEND=sqlite uv run python ../scripts/seed_academic.py && DB_BACKEND=sqlite uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

浏览器 `http://localhost:5173`：
1. 用 20230001 登录 → 首页骨架闪过、抬头显示"第 6 周"、今日安排与待办有内容；DevTools Network 里四个 `/api/*` 均 200 且带 Cookie。
2. 成绩页 → 表格 13 行，大学物理（上）56 分朱红；绩点 3.3 左右（与旧 seed 同数）。
3. 课表页 → 12 门课，周次条能点，切到第 20 周显示空态文案。
4. 补考重修 → 3 条，"报名中"那条显示"剩 23 / 120"与"报名截止 …"。
5. 图书馆 → 4 本，深入理解计算机系统显示"已逾期 3 天"。
6. 退出后用 20230002 登录 → 四页全换成建筑学数据，补考页显示空态，借阅 2 本。
7. 停掉后端再刷新任一页 → 出现错误条与"重试"，重启后端后点"重试"能恢复。

- [ ] **Step 11: 提交**

```bash
git add frontend/
git commit -m "feat(front): 四页与首页改读 /api/*，seed.ts 退成展示常量，页面三态齐备"
```

---

### Task 7: 契约脚本扩展 + 双后端一致性与真库冒烟

**Files:**
- Modify: `scripts/check_routes_contract.py`（加两条断言）
- 无新建源文件；本任务只验证与收口

**Interfaces:**
- Consumes: Task 5 的 `app/api/academic.py` 路由声明、Task 2 的两个方言迁移目录、Task 1 的 mysql 容器
- Produces: `python scripts/check_routes_contract.py` 三条 OK 行；S2 验收判据的可复跑命令序列

- [ ] **Step 1: 扩契约脚本**

`scripts/check_routes_contract.py` 在 `print(f"OK: PAGE_REGISTRY ...")` 之前插入两段检查（沿用该脚本既有的 `ROOT` 与 `sys.exit(1)` 风格）：

```python
# 页面与其数据源一一对应：教务页存在但没有 /api/* 端点、或端点挂了却没页面，都算错位
PAGE_TO_API = {
    "/academic/schedule": "/api/schedule",
    "/academic/grades": "/api/grades",
    "/academic/makeup": "/api/makeup",
    "/library": "/api/loans",
}
api_src = (ROOT / "backend" / "app" / "api" / "academic.py").read_text(encoding="utf-8")
api_paths = set(re.findall(r'@router\.get\("([^"]+)"\)', api_src))
unmapped_pages = sorted(p for p in registry_paths if p not in PAGE_TO_API)
missing_apis = sorted({PAGE_TO_API[p] for p in registry_paths if p in PAGE_TO_API} - api_paths)
extra_apis = sorted(api_paths - set(PAGE_TO_API.values()))
if unmapped_pages or missing_apis or extra_apis:
    print("FAIL: 页面与 /api/* 端点错位:", unmapped_pages, missing_apis, extra_apis)
    sys.exit(1)
print(f"OK: {len(registry_paths)} 个教务页与 /api/* 一一对应")

# 迁移文件名集合双方言必须相同：只改一边立刻红（spec 6.3）
mig = ROOT / "backend" / "app" / "db" / "migrations"
mysql_files = {p.name for p in (mig / "mysql").glob("*.sql")}
sqlite_files = {p.name for p in (mig / "sqlite").glob("*.sql")}
if mysql_files != sqlite_files:
    print("FAIL: 迁移文件双方言不一致: 仅 mysql", sorted(mysql_files - sqlite_files),
          "仅 sqlite", sorted(sqlite_files - mysql_files))
    sys.exit(1)
print(f"OK: 迁移文件双方言同名 {len(mysql_files)} 个")
```

Run: `python scripts/check_routes_contract.py`
Expected: 三行 OK（原有的 PAGE_REGISTRY/router 对应 + 新增两条）。`backend/tests/test_contract.py` 已经在跑这个脚本，`uv run pytest tests/test_contract.py -q` 应随之变绿。

- [ ] **Step 2: 双后端 JSON 逐字段一致**

```bash
# sqlite 侧
cd backend && rm -f data/campus.db
uv run python ../scripts/seed_academic.py            # 读 backend/.env 的 DB_BACKEND=sqlite
DB_BACKEND=sqlite uv run uvicorn app.main:app --port 8100 &
# mysql 侧（先确保 deploy 的容器 healthy）
DB_BACKEND=mysql uv run python ../scripts/seed_academic.py
DB_BACKEND=mysql uv run uvicorn app.main:app --port 8200 &
```

另开 Git Bash：

```bash
for port in 8100 8200; do
  curl -s -c /tmp/j-$port.txt -X POST http://localhost:$port/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"student_id":"20230001","password":"demo1234"}' > /dev/null
  for ep in grades schedule makeup loans; do
    curl -s -b /tmp/j-$port.txt http://localhost:$port/api/$ep > /tmp/$port-$ep.json
  done
done
for ep in grades schedule makeup loans; do
  echo "--- $ep"; diff /tmp/8100-$ep.json /tmp/8200-$ep.json && echo SAME
done
```

Expected: 四个端点全 `SAME`。若 `credits`/`score` 出现 `87` 对 `87.0` 之类差异，是 MySQL 的 `DECIMAL` 经 `jsonable_encoder` 后的表示差别——在 `academic.py` 对应字段上显式 `float(...)` 后再比，不改 DDL。

收尾：`kill` 掉两个 uvicorn（或 `Ctrl+C`），别让 8100/8200 悬着。

- [ ] **Step 3: 真库判据复跑**

```bash
# 表已建，agent_ro 仍应被拒（spec 9.2 冒烟判据）
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T mysql \
  mysql -uagent_ro -pagent-ro-local -e 'SELECT COUNT(*) FROM campus.enrollments'"
wsl bash -lc "cd /mnt/c/Users/houyunlong/Desktop/campusProject && \
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps"
```

Expected: 第一条 `ERROR 1142 ... SELECT command denied to user 'agent_ro'@'%' for table 'enrollments'`；第二条 STATUS 含 `(healthy)`。

- [ ] **Step 4: 全量回归与工作区洁净**

```bash
cd backend && uv run pytest -q
cd ../frontend && npx vitest run && npm run build
cd .. && git status --short
```

Expected: 后端全绿（含 test_database / test_seed_academic / test_academic_api / test_contract 四组新增）；前端全绿且 build 成功；`git status` 里 `deploy/.env`、`backend/.env`、`backend/data/*.db` 均不出现（已被 .gitignore 覆盖）。

- [ ] **Step 5: 提交**

```bash
git add scripts/check_routes_contract.py
git commit -m "test(contract): 页面与 /api/* 一一对应、迁移文件双方言同集两条契约"
```

---

## S2 完成判据

对应 spec 第 10 节 S2 行与第 13 节第 6、7 条，每条都有可跑命令：

1. `wsl docker compose ... ps` 显示 mysql `(healthy)`；`deploy/.env` 未被 git 跟踪。
2. `agent_ro` 打 `SELECT COUNT(*) FROM campus.enrollments` → `ERROR 1142`。
3. 迁移幂等：`run_migrations` 二次返回 `[]`（`test_迁移按序应用且幂等` 覆盖）；启动两次服务不重复建表。
4. `DB_BACKEND=sqlite` 与 `DB_BACKEND=mysql` 下，`/api/grades|schedule|makeup|loans` 四份 JSON `diff` 全等。
5. 四个教务页三态齐备：正常渲染、骨架、错误 + 重试；`seed.ts` 里没有任何业务数据（Step 9 的 `rg` 判据）。
6. 越权用例 A7/A8 仍成立（`/api/*` 无 Cookie → 401；请求体带 `student_id` 无处可传，端点无请求体）。
7. 后端 `uv run pytest -q`、前端 `npx vitest run`、`npm run build`、`python scripts/check_routes_contract.py` 全绿；`git status` 干净。
8. 语义视图 `v_grades` 等与 `agent_ro` 的视图授权**不在 S2**（属 S3 的 `0002_semantic_views.sql`），此处 `agent_ro` 对 `campus` 零权限是 S3 的起点。