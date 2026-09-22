import aiosqlite

from app.auth.students import (
    SEED_STUDENTS, Student, build_student_repository, seed_students,
)
from app.db.migrations import init_sqlite


class MySqlGrammarGate:
    """方言闸门：底下仍是临时 sqlite 库，但 MySQL 不认的语法一律先拒绝、不执行。

    存在的唯一目的：证明仓储的 SQL 不是靠 SQLite 专有写法（ON CONFLICT / excluded.）
    通过的——自动化测试全部跑在 sqlite 上，没有这一层就没人拦住方言泄漏。
    """

    dialect = "mysql"

    def __init__(self, inner):
        self._inner = inner

    @staticmethod
    def _guard(sql: str) -> None:
        upper = sql.upper()
        for token in ("ON CONFLICT", "EXCLUDED.", "REPLACE INTO"):
            if token in upper:
                raise AssertionError(f"MySQL 不支持的方言语法 {token!r}：{sql}")

    async def fetch_all(self, sql, args=()):
        self._guard(sql)
        return await self._inner.fetch_all(sql, args)

    async def execute(self, sql, args=()):
        self._guard(sql)
        return await self._inner.execute(sql, args)

    async def execute_script(self, sql):
        self._guard(sql)
        return await self._inner.execute_script(sql)


async def test_seed_灌三个账号且可查回(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")

    assert await seed_students(db) == 3

    repo = build_student_repository(db)
    student = await repo.get("20230001")
    assert student is not None and student.name == "周晓楠"
    assert student.major == "计算机科学与技术"
    assert await repo.get_password_hash("20230001") is not None


async def test_不存在的学号返回None(tmp_path):
    db = await init_sqlite(tmp_path / "campus.db")
    await seed_students(db)

    assert await build_student_repository(db).get("20990001") is None


async def test_seed幂等_重复调用不重复插入(tmp_path):
    path = tmp_path / "campus.db"
    db = await init_sqlite(path)
    await seed_students(db)
    await seed_students(db)

    async with aiosqlite.connect(path) as conn:
        n = await (await conn.execute("SELECT COUNT(*) FROM students")).fetchone()
    assert n[0] == 3


async def test_upsert重复学号走更新分支_非键列被改写(tmp_path):
    """upsert 的 UPDATE 分支必须真的改掉非键列——旧实现只在 ON CONFLICT 里写 SET，
    单看'不重复插入'那条测试是看不出 SET 是否生效的。"""
    db = await init_sqlite(tmp_path / "campus.db")
    await seed_students(db)
    repo = build_student_repository(db)

    await repo.upsert(
        Student(student_id="20230001", name="周晓楠（改）", major="网络空间安全",
                class_name="网安 2301", college="信息技术学院"), "pbkdf2_sha256$new")

    got = await repo.get("20230001")
    assert got is not None
    assert (got.name, got.major, got.class_name, got.college) == (
        "周晓楠（改）", "网络空间安全", "网安 2301", "信息技术学院")
    assert await repo.get_password_hash("20230001") == "pbkdf2_sha256$new"
    n = await db.fetch_all("SELECT COUNT(*) AS n FROM students")
    assert n == [{"n": 3}]  # 更新而非新增


async def test_upsert与seed在mysql语法闸门下同样成立(tmp_path):
    """闸门后面跑同一条 SQL：MySQL 8.4 没有 ON CONFLICT，也没有 REPLACE INTO 的语义。"""
    inner = await init_sqlite(tmp_path / "campus.db")
    db = MySqlGrammarGate(inner)

    assert await seed_students(db) == 3
    await seed_students(db)  # 幂等
    await build_student_repository(db).upsert(
        Student(student_id="20230001", name="改名", major="软件工程",
                class_name="软工 2301", college="信息科学与工程学院"), "h2")

    assert await inner.fetch_all("SELECT COUNT(*) AS n FROM students") == [{"n": 3}]
    rows = await inner.fetch_all(
        "SELECT name, password_hash FROM students WHERE student_id = ?", ("20230001",))
    assert rows == [{"name": "改名", "password_hash": "h2"}]


async def test_密码不以明文入库(tmp_path):
    path = tmp_path / "campus.db"
    db = await init_sqlite(path)
    await seed_students(db)

    async with aiosqlite.connect(path) as conn:
        row = await (await conn.execute(
            "SELECT password_hash FROM students WHERE student_id='20230001'")).fetchone()
    assert row[0].startswith("pbkdf2_sha256$")
    assert "demo1234" not in row[0]


def test_seed常量形状():
    assert len(SEED_STUDENTS) == 3
    assert isinstance(SEED_STUDENTS[0][0], Student)
    assert {s.student_id for s, _ in SEED_STUDENTS} == {"20230001", "20230002", "20230007"}
