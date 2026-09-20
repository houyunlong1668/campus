# S1 身份与会话 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给校园 Agent 装上真实的登录与会话，让 `student_id` 第一次真正"只从会话取"，并把未登录访问全部挡在门外。

**Architecture:** 后端加一层 `app/auth/`（密码哈希、学生仓储、进程内会话、登录限速、`require_student` 依赖）与 `/auth/*` 端点；`/chat` 改为从会话取身份，请求体里不再有任何身份/会话标识。前端加 `useAuth` 单例 + 登录页 + 路由守卫，顶栏姓名改读 `/auth/me`。

**Tech Stack:** FastAPI + pydantic v2 + aiosqlite（SQLite，S2 才换 MySQL）、stdlib `hashlib.pbkdf2_hmac`、Vue 3 + vue-router 4 + vitest。

**Spec:** `docs/superpowers/specs/2026-09-20-campus-auth-text2sql-mysql-design.md` 第 5.1（students 表）、7.1、7.2、8.1、8.2、9.1 节。本计划只覆盖该 spec 的 **S1 里程碑**；S2（MySQL 数据层）与 S3（academic MCP + Text-to-SQL）各自另出计划。

## Global Constraints

- Python 一律 `uv`，不用裸 `pip install`；后端与 MCP server 是两个独立 uv 项目。
- 依赖只用 stdlib 或已锁定的包；S1 唯一新增是 dev 组的 `httpx>=0.27`（FastAPI `TestClient` 需要），运行时零新依赖。
- 密码哈希格式逐字为 `pbkdf2_sha256$600000$<salt_b64>$<hash_b64>`，16 字节随机 salt，比较必须用 `hmac.compare_digest`。
- Cookie 名逐字 `sid`，属性固定 `HttpOnly; SameSite=Lax; Path=/; Max-Age=43200`；`config.cookie_secure` 默认 `False`。
- 会话 TTL 固定 12 小时（43200 秒），**不做滑动续期**。
- 登录失败提示逐字为「学号或密码不正确」，不区分账号不存在与密码错误。
- 限速：同一学号连续失败 5 次锁 60 秒，返回 429，错误码逐字 `too_many_attempts`。
- CORS 必须 `allow_credentials=True` 且源仍是显式白名单，**禁止** `allow_origins=["*"]`。
- `student_id` 永不出现在任何请求体模型字段里；`ChatRequest` 只允许 `message` 一个字段，多余字段一律 422。
- 前端组件不发请求，网络出口只在 composable 里（沿用 MVP spec 5.6 的边界）。
- 每个任务结束时提交一次；`backend/.env`、`backend/data/*.db` 不得被跟踪。

## File Structure

**新建（后端）**
- `backend/app/auth/__init__.py` — 空包标记
- `backend/app/auth/passwords.py` — 密码哈希与校验，纯函数，无 IO
- `backend/app/auth/students.py` — `Student` 模型 + `StudentRepository` 协议 + SQLite 实现 + seed
- `backend/app/auth/session.py` — `Session` + `SessionStore`（进程内、TTL、过期清理）
- `backend/app/auth/rate_limit.py` — `LoginGuard` 失败计数与锁定窗口
- `backend/app/auth/deps.py` — `require_student` FastAPI 依赖
- `backend/app/api/auth.py` — `/auth/login`、`/auth/logout`、`/auth/me`
- `backend/tests/test_passwords.py`、`test_students.py`、`test_session.py`、`test_rate_limit.py`、`test_auth_api.py`

**修改（后端）**
- `backend/pyproject.toml` — dev 组加 `httpx>=0.27`
- `backend/app/config.py` — 加 `cookie_secure`、`session_ttl_seconds`
- `backend/app/schemas.py` — `ChatRequest` 删 `session_id`、加 `extra="forbid"`；新增 `LoginRequest`
- `backend/app/db/engine.py` — `students` 建表 + `conversations.student_id` 列补齐
- `backend/app/db/repository.py` — `record_exchange` 加 `student_id` 参数
- `backend/app/tools/base.py` — `validate_args` 拒绝未知字段
- `backend/app/main.py` — CORS credentials、挂 auth 路由、lifespan 装配 store/仓储
- `backend/app/api/chat.py` — 身份取自 `require_student`

**新建（前端）**
- `frontend/src/composables/useAuth.ts` — 模块级会话状态 + 唯一认证网络出口
- `frontend/src/views/LoginView.vue`
- `frontend/tests/useAuth.test.ts`

**修改（前端）**
- `frontend/src/router/index.ts` — `/login` 路由 + `beforeEach` 守卫
- `frontend/src/App.vue` — 顶栏身份改读 `useAuth`，加"退出"
- `frontend/src/composables/useChatStream.ts` — 删 `session_id`、加 `credentials`、401 上抛
- `frontend/vite.config.ts` — 代理补 `/auth`
- `frontend/src/types.ts` — `ChatRequest` 与 `StudentInfo`

---

### Task 1: 密码哈希工具

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/passwords.py`
- Test: `backend/tests/test_passwords.py`

**Interfaces:**
- Produces: `hash_password(plain: str) -> str`、`verify_password(plain: str, encoded: str) -> bool`。后续 Task 2 的 seed 与 Task 4 的登录端点消费这两个函数。

- [ ] **Step 1: 建包并写失败测试**

`backend/app/auth/__init__.py` 留空文件。

```python
# backend/tests/test_passwords.py
import re

from app.auth.passwords import hash_password, verify_password


def test_同一密码两次哈希结果不同():
    assert hash_password("demo1234") != hash_password("demo1234")


def test_格式符合约定():
    encoded = hash_password("demo1234")
    assert re.fullmatch(r"pbkdf2_sha256\$600000\$[A-Za-z0-9+/=]{22,}\$[A-Za-z0-9+/=]{43,}", encoded)


def test_正确密码通过_错误密码不通过():
    encoded = hash_password("demo1234")
    assert verify_password("demo1234", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_空串与畸形哈希不抛异常():
    assert verify_password("", "") is False
    assert verify_password("x", "pbkdf2_sha256$600000$abc") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: 写实现**

```python
# backend/app/auth/passwords.py
import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(plain: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", plain.encode(), base64.b64decode(salt_b64), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)
```

`secrets` 而非 `os.urandom`：语义直白，且与 Task 3 生成 sid 用同一套 API。畸形哈希（段数不足、base64 坏、iterations 非数字）一律走 `except` 返回 `False`，绝不抛到调用方。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_passwords.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/auth backend/tests/test_passwords.py
git commit -m "feat(auth): pbkdf2 密码哈希与常量时间校验"
```

---

### Task 2: 学生表、仓储与 seed

**Files:**
- Create: `backend/app/auth/students.py`
- Modify: `backend/app/db/engine.py`（SCHEMA 与列补齐）
- Test: `backend/tests/test_students.py`

**Interfaces:**
- Consumes: `app.auth.passwords.hash_password`（Task 1）
- Produces:
  - `Student(student_id: str, name: str, major: str, class_name: str, college: str)`（pydantic 模型）
  - `class StudentRepository(Protocol)`：`async def get(self, student_id: str) -> Student | None`、`async def get_password_hash(self, student_id: str) -> str | None`、`async def upsert(self, student: Student, password_hash: str) -> None`
  - `def build_student_repository(path: Path) -> StudentRepository`
  - `SEED_STUDENTS: list[tuple[Student, str]]`（明文密码只存在这里，供本地仿真）
  - `async def seed_students(path: Path) -> int`

- [ ] **Step 1: 建表与列补齐**

在 `backend/app/db/engine.py` 的 `SCHEMA` 字符串末尾追加：

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
```

并把 `conversations` 的建表语句里 `session_id TEXT NOT NULL,` 之后插入一行 `student_id TEXT NOT NULL DEFAULT '',`。

老库不会有这一列（`CREATE TABLE IF NOT EXISTS` 不改已存在的表），因此在 `init_db` 里补一次列检查：

```python
async def _ensure_column(db, table: str, column: str, ddl: str) -> None:
    rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
    if column not in {r[1] for r in rows}:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


async def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await _ensure_column(db, "conversations", "student_id", "TEXT NOT NULL DEFAULT ''")
        await db.commit()
```

> `table`/`column`/`ddl` 三个参数全部由本模块内写死调用，不接受任何外部输入——`PRAGMA`/`ALTER` 不能用占位符绑定，这里靠"只传字面量"约束，不靠转义。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_students.py
from app.auth.students import SEED_STUDENTS, Student, build_student_repository, seed_students
from app.db.engine import init_db


async def test_seed_灌三个账号且可查回(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)

    assert await seed_students(path) == 3

    repo = build_student_repository(path)
    student = await repo.get("20230001")
    assert student is not None and student.name == "周晓楠"
    assert await repo.get_password_hash("20230001") is not None


async def test_不存在的学号返回None(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    await seed_students(path)

    assert await build_student_repository(path).get("20990001") is None


async def test_seed幂等_重复调用不重复插入(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    await seed_students(path)
    await seed_students(path)

    import aiosqlite

    async with aiosqlite.connect(path) as db:
        n = await (await db.execute("SELECT COUNT(*) FROM students")).fetchone()
    assert n[0] == 3


async def test_seed密码不是明文入库(tmp_path):
    path = tmp_path / "campus.db"
    await init_db(path)
    await seed_students(path)

    import aiosqlite

    async with aiosqlite.connect(path) as db:
        row = await (await db.execute(
            "SELECT password_hash FROM students WHERE student_id='20230001'")).fetchone()
    assert row[0].startswith("pbkdf2_sha256$")
    assert "demo1234" not in row[0]
    assert len(SEED_STUDENTS) == 3
    assert isinstance(SEED_STUDENTS[0][0], Student)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_students.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth.students'`

- [ ] **Step 4: 写实现**

`backend/app/auth/students.py` 按此顺序落盘（`SEED_STUDENTS` 引用 `Student`，必须在类定义之后）：

```python
# backend/app/auth/students.py
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from .passwords import hash_password

SEED_PASSWORD = "demo1234"  # 本地仿真账号；见 spec 第 11 节告警


class Student(BaseModel):
    student_id: str
    name: str
    major: str = ""
    class_name: str = ""
    college: str = ""


class StudentRepository(Protocol):
    async def get(self, student_id: str) -> Student | None: ...
    async def get_password_hash(self, student_id: str) -> str | None: ...
    async def upsert(self, student: Student, password_hash: str) -> None: ...


class SqliteStudentRepository:
    def __init__(self, path: Path):
        self._path = path

    async def get(self, student_id: str) -> Student | None:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT student_id, name, major, class_name, college "
                "FROM students WHERE student_id = ?", (student_id,))).fetchone()
        return Student(**dict(row)) if row else None

    async def get_password_hash(self, student_id: str) -> str | None:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            row = await (await db.execute(
                "SELECT password_hash FROM students WHERE student_id = ?",
                (student_id,))).fetchone()
        return row[0] if row else None

    async def upsert(self, student: Student, password_hash: str) -> None:
        import aiosqlite

        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """INSERT INTO students (student_id, name, password_hash, major, class_name, college)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(student_id) DO UPDATE SET
                     name=excluded.name, password_hash=excluded.password_hash,
                     major=excluded.major, class_name=excluded.class_name,
                     college=excluded.college""",
                (student.student_id, student.name, password_hash,
                 student.major, student.class_name, student.college),
            )
            await db.commit()


def build_student_repository(path: Path) -> StudentRepository:
    return SqliteStudentRepository(path)


SEED_STUDENTS: list[tuple[Student, str]] = [
    (Student(student_id="20230001", name="周晓楠", major="计算机科学与技术",
             class_name="计科 2301", college="信息科学与工程学院"), SEED_PASSWORD),
    (Student(student_id="20230002", name="陈默", major="建筑学",
             class_name="建筑 2302", college="建筑与艺术学院"), SEED_PASSWORD),
    (Student(student_id="20230007", name="林知远", major="计算机科学与技术",
             class_name="计科 2301", college="信息科学与工程学院"), SEED_PASSWORD),
]


async def seed_students(path: Path) -> int:
    """幂等灌库：ON CONFLICT 覆盖，重复调用不产生新行。"""
    repo = build_student_repository(path)
    for student, plain in SEED_STUDENTS:
        await repo.upsert(student, hash_password(plain))
    return len(SEED_STUDENTS)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_students.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/auth/students.py backend/app/db/engine.py backend/tests/test_students.py
git commit -m "feat(auth): students 表、学生仓储与三个仿真账号 seed"
```

---

### Task 3: 进程内会话存储

**Files:**
- Create: `backend/app/auth/session.py`
- Test: `backend/tests/test_session.py`

**Interfaces:**
- Produces:
  - `@dataclass Session: sid: str; student_id: str; expires_at: float`，方法 `is_expired(now: float) -> bool`
  - `class SessionStore(ttl_seconds: float)`：`create(student_id: str) -> Session`、`get(sid: str) -> Session | None`（过期即删并返回 None）、`revoke(sid: str) -> bool`、`count() -> int`
  - `COOKIE_NAME = "sid"`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_session.py
import time

from app.auth.session import SessionStore


def test_create后可查回():
    store = SessionStore(ttl_seconds=43200)
    session = store.create("20230001")

    assert session.student_id == "20230001"
    assert store.get(session.sid) is not None
    assert store.count() == 1


def test_sid足够长且每次不同():
    store = SessionStore(ttl_seconds=43200)
    a, b = store.create("x"), store.create("x")
    assert a.sid != b.sid and len(a.sid) >= 32


def test_过期会话查不到并被清掉():
    store = SessionStore(ttl_seconds=1)
    session = store.create("20230001")
    session.expires_at = time.time() - 1

    assert store.get(session.sid) is None
    assert store.count() == 0


def test_revoke后查不到():
    store = SessionStore(ttl_seconds=43200)
    session = store.create("20230001")

    assert store.revoke(session.sid) is True
    assert store.get(session.sid) is None
    assert store.revoke("不存在") is False


def test_未知sid返回None不抛异常():
    assert SessionStore(ttl_seconds=60).get("random") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth.session'`

- [ ] **Step 3: 写实现**

```python
# backend/app/auth/session.py
import secrets
import time
from dataclasses import dataclass

COOKIE_NAME = "sid"
SID_BYTES = 32


@dataclass
class Session:
    sid: str
    student_id: str
    expires_at: float

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


class SessionStore:
    """进程内会话。重启即全部失效——spec 第 1 节已确认可接受。"""

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, student_id: str) -> Session:
        session = Session(
            sid=secrets.token_urlsafe(SID_BYTES),
            student_id=student_id,
            expires_at=time.time() + self._ttl,
        )
        self._sessions[session.sid] = session
        return session

    def get(self, sid: str) -> Session | None:
        session = self._sessions.get(sid)
        if session is None:
            return None
        if session.is_expired(time.time()):
            self._sessions.pop(sid, None)
            return None
        return session

    def revoke(self, sid: str) -> bool:
        return self._sessions.pop(sid, None) is not None

    def count(self) -> int:
        return len(self._sessions)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_session.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/auth/session.py backend/tests/test_session.py
git commit -m "feat(auth): 进程内会话存储，12 小时固定 TTL"
```

---

### Task 4: 登录限速与 `/auth/*` 端点

**Files:**
- Create: `backend/app/auth/rate_limit.py`
- Create: `backend/app/auth/deps.py`
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_rate_limit.py`、`backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `SessionStore`（Task 3）、`StudentRepository`（Task 2）、`verify_password`（Task 1）
- Produces:
  - `LoginGuard(allowed_failures: int = 5, lock_seconds: float = 60)`：`check(key: str) -> float | None`（返回还需等待的秒数，可用则 `None`）、`record_failure(key: str) -> None`、`reset(key: str) -> None`
  - `async def require_student(request: Request) -> Student`（未认证抛 `HTTPException(401, {"code": "unauthenticated"})`）
  - 端点 `POST /auth/login`、`POST /auth/logout`、`GET /auth/me`
  - `app.state.sessions`、`app.state.students`、`app.state.login_guard`

- [ ] **Step 1: 加 httpx 到 dev 依赖**

`backend/pyproject.toml` 的 `[dependency-groups] dev` 改为：

```toml
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27"]
```

Run: `cd backend && uv sync` — Expected: 安装 httpx 成功。

- [ ] **Step 2: 写限速失败测试**

```python
# backend/tests/test_rate_limit.py
from app.auth.rate_limit import LoginGuard


def test_五次失败内仍允许():
    guard = LoginGuard(allowed_failures=5, lock_seconds=60)
    for _ in range(5):
        assert guard.check("20230001") is None
        guard.record_failure("20230001")
    assert guard.check("20230001") is not None


def test_锁定后返回剩余秒数():
    guard = LoginGuard(allowed_failures=1, lock_seconds=60)
    guard.record_failure("x")
    wait = guard.check("x")
    assert wait is not None and 0 < wait <= 60


def test_锁定窗口过后自动放行():
    guard = LoginGuard(allowed_failures=1, lock_seconds=0.01)
    guard.record_failure("x")
    import time
    time.sleep(0.02)
    assert guard.check("x") is None


def test_成功登录清零计数():
    guard = LoginGuard(allowed_failures=2, lock_seconds=60)
    guard.record_failure("x")
    guard.reset("x")
    assert guard.check("x") is None
    guard.record_failure("x")
    assert guard.check("x") is None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_rate_limit.py -v`
Expected: FAIL — 模块不存在

- [ ] **Step 4: 写限速实现**

```python
# backend/app/auth/rate_limit.py
import time


class LoginGuard:
    """同一学号连续失败若干次后锁一段时间。进程内计数，重启即清零。"""

    def __init__(self, allowed_failures: int = 5, lock_seconds: float = 60):
        self._allowed = allowed_failures
        self._lock = lock_seconds
        self._failures: dict[str, list[float]] = {}

    def check(self, key: str) -> float | None:
        stamps = [t for t in self._failures.get(key, []) if time.time() - t < self._lock]
        self._failures[key] = stamps
        if len(stamps) < self._allowed:
            return None
        return self._lock - (time.time() - stamps[0])

    def record_failure(self, key: str) -> None:
        self._failures.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_rate_limit.py -v`
Expected: 4 passed

- [ ] **Step 6: 写认证端点失败测试**

测试用最小 app（不启 MCP 子进程），避免把 lifespan 的重启动拉进来：

```python
# backend/tests/test_auth_api.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.auth.rate_limit import LoginGuard
from app.auth.session import SessionStore
from app.auth.students import seed_students
from app.auth.students import build_student_repository
from app.config import Settings
from app.db.engine import init_db


@pytest.fixture
def client(tmp_path):
    async def setup():
        await init_db(tmp_path / "campus.db")
        await seed_students(tmp_path / "campus.db")

    import asyncio
    asyncio.run(setup())

    app = FastAPI()
    app.state.students = build_student_repository(tmp_path / "campus.db")
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.settings = Settings(cookie_secure=False)
    app.include_router(auth_router)
    with TestClient(app) as c:
        yield c


def test_正确凭据登录成功并下发Cookie(client):
    r = client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    assert r.status_code == 200
    assert r.json()["name"] == "周晓楠"
    cookie = r.cookies.get("sid")
    assert cookie and len(cookie) >= 32
    assert "HttpOnly" in r.headers["set-cookie"]
    assert "SameSite=lax" in r.headers["set-cookie"].lower()


def test_密码错误返回统一文案(client):
    r = client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]["message"] == "学号或密码不正确"


def test_不存在的学号与密码错误同响应(client):
    bad = client.post("/auth/login", json={"student_id": "20990001", "password": "wrong"})
    no_such = client.post("/auth/login", json={"student_id": "20990001", "password": "demo1234"})
    assert bad.status_code == no_such.status_code == 401
    assert bad.json() == no_such.json()


def test_me需要会话(client):
    assert client.get("/auth/me").status_code == 401
    client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["student_id"] == "20230001"


def test_登出后会话立即失效(client):
    client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_连续失败五次后六次被限流(client):
    for _ in range(5):
        client.post("/auth/login", json={"student_id": "20230001", "password": "wrong"})
    r = client.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "too_many_attempts"


def test_登录请求体多余字段被拒(client):
    r = client.post("/auth/login", json={
        "student_id": "20230001", "password": "demo1234", "role": "admin"})
    assert r.status_code == 422
```

- [ ] **Step 7: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_auth_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'app.api.auth'`

- [ ] **Step 8: 写 schemas、config、依赖与端点**

`backend/app/schemas.py` 追加（`ChatRequest` 的改动在 Task 5）：

```python
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
```

顶部 import 改为 `from pydantic import BaseModel, ConfigDict, Field`。

`backend/app/config.py` 的 `Settings` 追加两行（放在 `fake_student_id` 之后）：

```python
    cookie_secure: bool = False
    session_ttl_seconds: int = 43200
```

```python
# backend/app/auth/deps.py
from fastapi import HTTPException, Request

from .session import COOKIE_NAME
from .students import Student


async def require_student(request: Request) -> Student:
    sid = request.cookies.get(COOKIE_NAME)
    session = request.app.state.sessions.get(sid) if sid else None
    if session is None:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated",
                                                    "message": "请先登录"})
    student = await request.app.state.students.get(session.student_id)
    if student is None:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated",
                                                    "message": "请先登录"})
    return student
```

```python
# backend/app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth.deps import require_student
from ..auth.passwords import verify_password
from ..auth.session import COOKIE_NAME
from ..auth.students import Student
from ..schemas import LoginRequest

router = APIRouter(prefix="/auth")


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    students = request.app.state.students
    guard = request.app.state.login_guard

    wait = guard.check(body.student_id)
    if wait is not None:
        raise HTTPException(status_code=429, detail={
            "code": "too_many_attempts",
            "message": f"尝试次数过多，请 {int(wait) + 1} 秒后再试",
        })

    stored_hash = await students.get_password_hash(body.student_id)
    if stored_hash is None or not verify_password(body.password, stored_hash):
        guard.record_failure(body.student_id)
        raise HTTPException(status_code=401, detail={
            "code": "bad_credentials", "message": "学号或密码不正确"})

    guard.reset(body.student_id)
    session = request.app.state.sessions.create(body.student_id)
    settings = request.app.state.settings
    response.set_cookie(
        key=COOKIE_NAME, value=session.sid, max_age=settings.session_ttl_seconds,
        httponly=True, samesite="lax", secure=settings.cookie_secure, path="/",
    )
    student = await students.get(body.student_id)
    return student.model_dump()


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        request.app.state.sessions.revoke(sid)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return Response(status_code=204)


@router.get("/me")
async def me(student: Student = Depends(require_student)):
    return student.model_dump()
```

账号不存在与密码错误走同一个分支、同一句文案（`stored_hash is None or not verify_password(...)`），不给攻击者区分二者的信号。

- [ ] **Step 9: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_auth_api.py -v`
Expected: 7 passed

- [ ] **Step 10: 接进主应用**

`backend/app/main.py`：CORS 加 `allow_credentials=True`；lifespan 装配三件套；挂路由。

```python
from .api.auth import router as auth_router
from .auth.rate_limit import LoginGuard
from .auth.session import SessionStore
from .auth.students import build_student_repository, seed_students
```

`lifespan` 内 `await init_db(...)` 之后插入：

```python
    await seed_students(settings.sqlite_path)
    app.state.students = build_student_repository(settings.sqlite_path)
    app.state.sessions = SessionStore(ttl_seconds=settings.session_ttl_seconds)
    app.state.login_guard = LoginGuard()
    app.state.settings = settings
```

`add_middleware(CORSMiddleware, ...)` 的参数加一行 `allow_credentials=True,`；`create_app` 内在 `app.include_router(chat_router)` 之前加 `app.include_router(auth_router)`。

- [ ] **Step 11: 全量后端测试**

Run: `cd backend && uv run pytest -q`
Expected: 全部通过（原 15 + 本任务新增 11）

- [ ] **Step 12: 提交**

```bash
git add backend/
git commit -m "feat(auth): /auth/login|logout|me 端点、require_student 依赖与登录限速"
```

---

### Task 5: `/chat` 改走会话身份，请求体去标识

**Files:**
- Modify: `backend/app/schemas.py:4-7`
- Modify: `backend/app/api/chat.py:38-54,69-75,96`
- Modify: `backend/app/db/repository.py:16-40`
- Test: `backend/tests/test_chat_auth.py`

**Interfaces:**
- Consumes: `require_student`（Task 4）
- Produces:
  - `ChatRequest` 只含 `message: str`，`extra="forbid"`
  - `ConversationRepository.record_exchange(*, student_id: str, user_text: str, assistant_text: str, tool_call: ToolCallRecord | None, steps: list[str]) -> None`（`session_id` 参数**移除**，会话即身份）
  - `done` 事件 data 增 `conversation_id`，`session_id` 字段移除

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_chat_auth.py
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.auth.rate_limit import LoginGuard
from app.auth.session import SessionStore
from app.auth.students import build_student_repository, seed_students
from app.config import Settings
from app.db.engine import init_db
from app.db.repository import build_repository
from app.llm.fake import FakeProvider
from app.tools.inmemory import InMemoryRegistry


@pytest.fixture
def app_and_store(tmp_path):
    path = tmp_path / "campus.db"

    async def setup():
        await init_db(path)
        await seed_students(path)

    asyncio.run(setup())

    async def fake_resolve(intent: str, params: dict | None = None):
        return {"path": "/academic/grades", "title": "成绩查询", "capabilities": []}

    app = FastAPI()
    app.state.settings = Settings()
    app.state.students = build_student_repository(path)
    app.state.sessions = SessionStore(ttl_seconds=43200)
    app.state.login_guard = LoginGuard()
    app.state.provider = FakeProvider()
    app.state.repository = build_repository(path)
    app.state.registry = InMemoryRegistry({
        "resolve_page": {"spec": {
            "name": "resolve_page", "description": "解析页面",
            "input_schema": {"type": "object", "properties": {"intent": {"type": "string"}},
                             "required": ["intent"]}},
        "fn": fake_resolve,
    })
    app.include_router(chat_router)
    return app, path


def test_未登录打chat返回401(app_and_store):
    app, _ = app_and_store
    with TestClient(app) as c:
        assert c.post("/chat", json={"message": "查成绩"}).status_code == 401


def test_未登录时带session_id也拿不到身份(app_and_store):
    """请求体里的身份/会话标识一律无效：未登录仍是 401，而不是被当成会话凭据。"""
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.post("/chat", json={"message": "查成绩", "session_id": "s1"})
        assert r.status_code == 422  # extra="forbid" 先拒掉整个请求


def test_schema层拒绝多余字段():
    import pydantic

    from app.schemas import ChatRequest

    with pytest.raises(pydantic.ValidationError):
        ChatRequest.model_validate({"message": "查成绩", "session_id": "s1"})
    with pytest.raises(pydantic.ValidationError):
        ChatRequest.model_validate({"message": "查成绩", "student_id": "20230002"})
    ChatRequest.model_validate({"message": "查成绩"})  # 合法形态不抛


def test_登录后对话落库带上该学号(app_and_store):
    app, path = app_and_store
    with TestClient(app) as c:
        c.post("/auth/login", json={"student_id": "20230002", "password": "demo1234"})
        r = c.post("/chat", json={"message": "查成绩"})
        assert r.status_code == 200
        assert "event: done" in r.text

    import aiosqlite

    async def read():
        async with aiosqlite.connect(path) as db:
            return await (await db.execute(
                "SELECT student_id FROM conversations ORDER BY id DESC LIMIT 1")).fetchone()

    assert asyncio.run(read())[0] == "20230002"


def test_done事件带出conversation_id(app_and_store):
    app, _ = app_and_store
    with TestClient(app) as c:
        c.post("/auth/login", json={"student_id": "20230001", "password": "demo1234"})
        text = c.post("/chat", json={"message": "查成绩"}).text
    done = [ln for ln in text.splitlines() if ln.startswith("data:") and "conversation_id" in ln]
    assert done, "done 事件应带 conversation_id"
```

> 注意 fixture 里必须 `app.include_router(auth_router)` 才能登录——在 `app.include_router(chat_router)` 之前加这一行，并 `from app.api.auth import router as auth_router`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_chat_auth.py -v`
Expected: FAIL — `session_id` 仍是必填字段 / 未登录仍返回 200

- [ ] **Step 3: 改 schema**

`backend/app/schemas.py` 的 `ChatRequest` 整块替换为：

```python
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    # 身份与会话标识一律不从请求体来：只认 Cookie 里的会话（spec 6.1）
```

- [ ] **Step 4: 改仓储签名**

`backend/app/db/repository.py` 三处同步改：
1. `ConversationRepository.record_exchange` 协议：`session_id: str` → `student_id: str`，返回类型 `None` → `int | None`（返回新建的 conversation id，供 `done` 事件带出）。
2. `SqliteConversationRepository.record_exchange` 同步改参数与返回类型，末尾 `return conv_id`。
3. `INSERT INTO conversations(session_id) VALUES (?)` → `INSERT INTO conversations(student_id) VALUES (?)`。

- [ ] **Step 5: 改 `/chat`**

`backend/app/api/chat.py`：

```python
from fastapi import APIRouter, Depends, Request
from ..auth.deps import require_student
from ..auth.students import Student
```

路由签名与 initial_state：

```python
@router.post("/chat")
async def chat(request: ChatRequest, req: Request, student: Student = Depends(require_student)):
    registry = req.app.state.registry
    provider = req.app.state.provider
    repository = req.app.state.repository
    graph = build_graph(provider, registry)
    request_id = uuid.uuid4().hex[:12]
    message_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    initial_state = {
        "user_input": request.message,
        "session_id": student.student_id,   # 图内会话即学号，节点不感知身份来源
        "intent": None, "tool_name": None, "tool_args": {},
        "tool_results": {}, "answer": "", "nav_card": None,
        "steps": [], "error": None,
    }
```

`persist()` 与 `done` 帧改为共享一个 `conversation_id` 局部量：

```python
        conversation_id: int | None = None

        async def persist():
            nonlocal persisted, conversation_id
            if persisted:
                return
            persisted = True
            state = final_state or {}
            try:
                conversation_id = await repository.record_exchange(
                    student_id=student.student_id,
                    user_text=request.message,
                    assistant_text=state.get("answer", ""),
                    tool_call=build_record(state),
                    steps=state.get("steps", []),
                )
            except Exception:
                logger.exception("request_id=%s 落库失败（不中断对话流）", request_id)
```

```python
            yield sse_frame("done", {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "steps": (final_state or {}).get("steps", []),
            })
```

`session_id` 字段从 `done` 事件里移除（前端不再持有会话标识）。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_chat_auth.py tests/test_repository.py -v`
Expected: 全部通过（`test_repository.py` 里两处 `session_id="s1"` 调用需同步改为 `student_id="..."`）

- [ ] **Step 7: 全量测试**

Run: `cd backend && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 8: 提交**

```bash
git add backend/
git commit -m "feat(auth): /chat 身份改取自会话，请求体去掉 session_id 并禁止多余字段"
```

---

### Task 6: `validate_args` 拒绝未知字段

**Files:**
- Modify: `backend/app/tools/base.py:43-61`
- Test: `backend/tests/test_tools.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `validate_args(schema, args)` 在 args 含 schema 未声明的键时返回 `(False, "参数校验失败: ...")`。S3 的 `TRUSTED_ARGS` 注入依赖"未知即拒"这条底线。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_tools.py` 的 `TestValidateArgs` 类内：

```python
    def test_未声明字段被拒(self):
        ok, err = validate_args(self.schema, {"intent": "查成绩", "student_id": "20230002"})
        assert not ok and "student_id" in err

    def test_多余未知键即使类型正确也被拒(self):
        ok, err = validate_args(self.schema, {"intent": "查成绩", "params": {"a": 1}, "extra": 1})
        assert not ok and "extra" in err
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_tools.py -v`
Expected: 新增 2 条 FAIL（当前宽松放行）

- [ ] **Step 3: 改实现**

`_args_model` 的 `create_model` 调用加 `__config__`：

```python
from pydantic import BaseModel, ConfigDict, create_model

    return create_model(
        "ToolArgs",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_tools.py tests/test_stdio_mcp.py -v`
Expected: 全部通过（真子进程用例确认没把合法参数误拒）

- [ ] **Step 5: 全量测试并提交**

```bash
cd backend && uv run pytest -q
git add backend/app/tools/base.py backend/tests/test_tools.py
git commit -m "fix(tools): validate_args 拒绝 schema 未声明的参数"
```

---

### Task 7: 前端认证状态、登录页与路由守卫

**Files:**
- Create: `frontend/src/composables/useAuth.ts`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/tests/useAuth.test.ts`
- Modify: `frontend/src/types.ts`、`frontend/src/router/index.ts`、`frontend/src/App.vue:34-45`、`frontend/src/composables/useChatStream.ts:37-45`、`frontend/vite.config.ts:8-12`
- Test: `frontend/tests/useAuth.test.ts`

**Interfaces:**
- Consumes: `POST /auth/login`、`GET /auth/me`、`POST /auth/logout`（Task 4）；`/chat` 不再接受 `session_id`（Task 5）
- Produces:
  - `interface StudentInfo { student_id: string; name: string; major: string; class_name: string; college: string }`
  - `useAuth()` → `{ user: Ref<StudentInfo | null>, status: Ref<AuthStatus>, login(id, pw): Promise<LoginResult>, logout(): Promise<void>, bootstrap(): Promise<void>, signOut(): void }`，`AuthStatus = 'unknown' | 'authed' | 'anonymous'`。`signOut()` 只清本地状态不发请求，供 `/chat` 收到 401 时调用（服务端会话此时已不可用，再打一次 logout 没有意义）。
  - `LoginResult = { ok: true } | { ok: false; code: 'bad_credentials' | 'too_many_attempts' | 'network'; message: string }`

- [ ] **Step 1: 类型与代理**

`frontend/src/types.ts` 的 `ChatRequest` 改为：

```ts
export interface ChatRequest { message: string }

export interface StudentInfo {
  student_id: string
  name: string
  major: string
  class_name: string
  college: string
}
```

`frontend/vite.config.ts` 的 proxy 加一行 `'/auth': 'http://localhost:8000',`。

- [ ] **Step 2: 写 useAuth 失败测试**

```ts
// frontend/tests/useAuth.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../src/composables/useAuth'

function json(body: unknown, status = 200) {
  return vi.fn(async () => ({ status, ok: status < 400, json: async () => body }))
}

beforeEach(() => vi.unstubAllGlobals())

describe('useAuth', () => {
  it('bootstrap 成功则状态为 authed 并带出姓名', async () => {
    vi.stubGlobal('fetch', json({ student_id: '20230001', name: '周晓楠', major: '计算机', class_name: '计科2301', college: '信息学院' }))
    const { bootstrap, status, user } = useAuth()
    await bootstrap()
    expect(status.value).toBe('authed')
    expect(user.value?.name).toBe('周晓楠')
  })

  it('401 则状态为 anonymous 且 user 清空', async () => {
    vi.stubGlobal('fetch', json({ detail: { code: 'unauthenticated' } }, 401))
    const { bootstrap, status, user } = useAuth()
    await bootstrap()
    expect(status.value).toBe('anonymous')
    expect(user.value).toBeNull()
  })

  it('登录失败返回统一文案且不置为 authed', async () => {
    vi.stubGlobal('fetch', json({ detail: { code: 'bad_credentials', message: '学号或密码不正确' } }, 401))
    const { login, status } = useAuth()
    const r = await login('20230001', 'wrong')
    expect(r).toEqual({ ok: false, code: 'bad_credentials', message: '学号或密码不正确' })
    expect(status.value).toBe('anonymous')
  })

  it('429 透出 too_many_attempts', async () => {
    vi.stubGlobal('fetch', json({ detail: { code: 'too_many_attempts', message: '尝试次数过多，请 60 秒后再试' } }, 429))
    const { login } = useAuth()
    const r = await login('20230001', 'demo1234')
    expect(r.ok).toBe(false)
    expect((r as { code: string }).code).toBe('too_many_attempts')
  })
})
```

Run: `cd frontend && npx vitest run tests/useAuth.test.ts` → Expected: FAIL（模块不存在）

- [ ] **Step 3: 写 useAuth**

```ts
// frontend/src/composables/useAuth.ts
import { ref } from 'vue'
import type { StudentInfo } from '../types'

export type AuthStatus = 'unknown' | 'authed' | 'anonymous'
export type LoginResult =
  | { ok: true }
  | { ok: false; code: 'bad_credentials' | 'too_many_attempts' | 'network'; message: string }

// 模块级：登录态是全站状态，守卫与顶栏共用一份
const user = ref<StudentInfo | null>(null)
const status = ref<AuthStatus>('unknown')

async function readError(resp: Response): Promise<LoginResult> {
  const code = resp.status === 429 ? 'too_many_attempts' : 'bad_credentials'
  let message = '学号或密码不正确'
  try {
    const body = await resp.json()
    if (body?.detail?.message) message = body.detail.message
  } catch {
    /* 非 JSON 响应保留默认文案 */
  }
  return { ok: false, code, message }
}

export function useAuth() {
  async function bootstrap(): Promise<void> {
    try {
      const resp = await fetch('/auth/me', { credentials: 'include' })
      if (resp.ok) {
        user.value = (await resp.json()) as StudentInfo
        status.value = 'authed'
      } else {
        user.value = null
        status.value = 'anonymous'
      }
    } catch {
      status.value = 'anonymous'
    }
  }

  async function login(studentId: string, password: string): Promise<LoginResult> {
    let resp: Response
    try {
      resp = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ student_id: studentId, password }),
      })
    } catch {
      return { ok: false, code: 'network', message: '连不上服务器，请确认后端已启动' }
    }
    if (!resp.ok) return readError(resp)

    user.value = (await resp.json()) as StudentInfo
    status.value = 'authed'
    return { ok: true }
  }

  async function logout(): Promise<void> {
    await fetch('/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {})
    user.value = null
    status.value = 'anonymous'
  }

  function signOut(): void {
    user.value = null
    status.value = 'anonymous'
  }

  return { user, status, login, logout, bootstrap, signOut }
}
```

Run: `cd frontend && npx vitest run tests/useAuth.test.ts` → Expected: 4 passed

- [ ] **Step 4: 路由与守卫**

`frontend/src/router/index.ts` 整文件替换：

```ts
import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const routes = [
  { path: '/login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: "/", component: () => import('../views/HomeView.vue') },
  { path: "/academic/schedule", component: () => import('../views/ScheduleView.vue') },
  { path: "/academic/grades", component: () => import('../views/GradesView.vue') },
  { path: "/academic/makeup", component: () => import('../views/MakeupView.vue') },
  { path: "/library", component: () => import('../views/LibraryView.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const { status, bootstrap } = useAuth()
  if (status.value === 'unknown') await bootstrap()
  if (!to.meta.public && status.value !== 'authed') {
    return { path: '/login', query: { next: to.fullPath } }
  }
  if (to.path === '/login' && status.value === 'authed') return { path: '/' }
  return true
})

export { routes }
export default router
```

- [ ] **Step 5: 登录页**

`frontend/src/views/LoginView.vue`：沿用 `.signplate` 视觉，居中 380px 卡片，原生 form（Enter 提交），错误条 `role="status" aria-live="polite"`，429 时按钮禁用并倒计时。

```vue
<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const { login } = useAuth()
const route = useRoute()
const router = useRouter()

const studentId = ref('20230001')
const password = ref('')
const busy = ref(false)
const error = ref('')
const cooldown = ref(0)
const composing = ref(false)

let timer: number | undefined
function startCooldown(seconds: number) {
  cooldown.value = seconds
  timer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) window.clearInterval(timer)
  }, 1000)
}
onUnmounted(() => window.clearInterval(timer))

const disabled = computed(() => busy.value || cooldown.value > 0)
const buttonLabel = computed(() =>
  cooldown.value > 0 ? `请 ${cooldown.value} 秒后再试` : busy.value ? '登录中' : '登录')

async function submit() {
  if (disabled.value || composing.value) return
  error.value = ''
  busy.value = true
  const r = await login(studentId.value.trim(), password.value)
  busy.value = false
  if (r.ok) {
    router.replace(typeof route.query.next === 'string' ? route.query.next : '/')
    return
  }
  error.value = r.message
  if (r.code === 'too_many_attempts') startCooldown(60)
}
</script>

<template>
  <div class="login">
    <form class="card" @submit.prevent="submit">
      <p class="eyebrow">南岭大学 · 教务系统</p>
      <h1>学生登录</h1>
      <p v-if="error" class="error" role="status" aria-live="polite">{{ error }}</p>

      <label for="sid">学号</label>
      <input id="sid" v-model="studentId" class="field" type="text" autocomplete="username"
             inputmode="numeric" maxlength="32" />

      <label for="pw">密码</label>
      <input id="pw" v-model="password" class="field" type="password"
             autocomplete="current-password" maxlength="128"
             @compositionstart="composing = true" @compositionend="composing = false" />

      <button class="submit" type="submit" :disabled="disabled">{{ buttonLabel }}</button>
      <p class="hint">仿真环境账号：20230001 / 20230002 / 20230007，密码均为 demo1234</p>
    </form>
  </div>
</template>

<style scoped>
.login {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 40px 20px;
}

.card {
  width: 380px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 26px 24px;
  box-shadow: var(--shadow);
}

.card h1 {
  margin: 6px 0 18px;
  font-size: 26px;
}

label {
  font-family: var(--display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--faint);
  margin-bottom: 5px;
}

.field {
  font: inherit;
  font-size: 15px;
  color: var(--ink);
  border: 1px solid var(--rule-2);
  border-radius: var(--r-sm);
  padding: 9px 11px;
  margin-bottom: 16px;
}

.field:focus {
  outline: none;
  border-color: var(--ink);
}

.submit {
  font: inherit;
  font-size: 15px;
  font-weight: 500;
  color: #fff;
  background: var(--ink);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  padding: 10px;
  cursor: pointer;
}

.submit:hover:not(:disabled) {
  background: var(--seal);
  border-color: var(--seal);
}

.submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.error {
  font-size: 13px;
  color: var(--seal);
  border-left: 2px solid var(--seal);
  padding-left: 9px;
  margin-bottom: 16px;
}

.hint {
  margin-top: 14px;
  font-size: 11.5px;
  color: var(--faint);
}
</style>
```

- [ ] **Step 6: 顶栏改读真值 + 退出**

`frontend/src/App.vue`：删 `import { student } from './data/seed'` 之外的身份引用，改为：

```ts
import { useAuth } from './composables/useAuth'
const { user, logout, bootstrap } = useAuth()
bootstrap()
```

`.who` 区块替换为（周次仍来自 `student.week`，S2 才搬走）：

```html
<span class="who">
  <span class="who-name">{{ user?.name ?? '—' }}</span>
  <span class="code who-id">{{ user?.student_id ?? '未登录' }}</span>
  <button type="button" class="logout" @click="logout">退出</button>
</span>
```

`.logout` 样式：`font: inherit; font-size: 12px; color: rgba(231,235,242,.72); background: none; border: none; cursor: pointer;`，hover 变白。

登录页不显示导航：`<nav class="tabs" v-if="route.path !== '/login'">`，`<footer class="foot" v-if="route.path !== '/login'">`。

- [ ] **Step 7: 聊天请求去 session_id、带 credentials**

`frontend/src/composables/useChatStream.ts`：
- 删 `const sessionId = crypto.randomUUID()` 与 `ChatRequest` 里的 `session_id`；`return` 对象里去掉 `sessionId`
- `fetch('/chat', {...})` 加 `credentials: 'include'`
- 收到 `resp.status === 401` 时：`assistant.error = '登录已过期，请重新登录'`，并调用 `useAuth().signOut()` 后 `router.push('/login')`

```ts
      const resp = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text } satisfies ChatRequest),
        credentials: 'include',
        signal: controller.signal,
      })
      if (resp.status === 401) {
        const { signOut } = useAuth()
        signOut()
        assistant.error = '登录已过期，请重新登录'
        router.push({ path: '/login', query: { next: router.currentRoute.value.fullPath } })
        return
      }
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
```

顶部加 `import { useAuth } from './useAuth'` 与 `import router from '../router'`。

- [ ] **Step 8: 修既有测试对 `session_id` 的依赖**

`frontend/tests/useChatStream.test.ts` 里两处 `session_id` 断言/构造删除；`done` 帧的 `data` 改为 `{message_id, conversation_id, steps}`。

Run: `cd frontend && npx vitest run` → Expected: 全部通过

- [ ] **Step 9: 端到端手测（S1 验收）**

```bash
cd backend && uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

浏览器 `http://localhost:5173/academic/grades`：
1. 未登录 → 落到 `/login?next=/academic/grades`
2. 错密码 → 卡内出现「学号或密码不正确」，学号不被清空
3. 连错 5 次 → 按钮变「请 60 秒后再试」并禁用
4. 用 20230002 / demo1234 登录 → 回到成绩页，顶栏显示「陈默 20230002」
5. 打开助手问「查成绩」→ 正常流式 + 卡片；DevTools Application→Cookies 里 `sid` 带 HttpOnly
6. 点顶栏「退出」→ 回登录页；再直接访问 `/academic/grades` 仍被挡

命令行验证 401：

```bash
curl -i -s -X POST http://localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"message":"查成绩"}' | head -1          # 期望 HTTP/1.1 401
curl -i -s -X POST http://localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"message":"查成绩","session_id":"s1"}' | head -1   # 期望 422
```

- [ ] **Step 10: 提交**

```bash
git add frontend/
git commit -m "feat(auth): 登录页、useAuth 会话状态与路由守卫，顶栏改读会话真值"
```

---

## S1 完成判据

对应 spec 第 10 节 S1 行与第 13 节第 1、2 条：

1. 未登录访问 `/academic/grades` 落到 `/login`，登录后回到原页面。
2. 顶栏姓名/学号来自 `/auth/me`，换账号登录显示不同姓名。
3. `curl` 无 Cookie 打 `/chat` → 401；带 `session_id` 字段 → 422。
4. 后端 `uv run pytest -q` 全绿（新增 test_passwords / test_students / test_session / test_rate_limit / test_auth_api / test_chat_auth 六组）；前端 `npx vitest run` 全绿；`npm run build` 成功。
5. 越权用例 A7、A8、A9、A10 通过（A1–A6 属 S3）。
6. `git status` 干净，`backend/.env` 未被跟踪。
