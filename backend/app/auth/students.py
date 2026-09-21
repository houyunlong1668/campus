from typing import Protocol

from pydantic import BaseModel

from ..db.base import Database
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


class DbStudentRepository:
    def __init__(self, db: Database):
        self._db = db

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


def build_student_repository(db: Database) -> StudentRepository:
    return DbStudentRepository(db)


SEED_STUDENTS: list[tuple[Student, str]] = [
    (Student(student_id="20230001", name="周晓楠", major="计算机科学与技术",
             class_name="计科 2301", college="信息科学与工程学院"), SEED_PASSWORD),
    (Student(student_id="20230002", name="陈默", major="建筑学",
             class_name="建筑 2302", college="建筑与艺术学院"), SEED_PASSWORD),
    (Student(student_id="20230007", name="林知远", major="计算机科学与技术",
             class_name="计科 2301", college="信息科学与工程学院"), SEED_PASSWORD),
]


async def seed_students(db: Database) -> int:
    """幂等灌库：ON CONFLICT 覆盖，重复调用不产生新行。"""
    repo = build_student_repository(db)
    for student, plain in SEED_STUDENTS:
        await repo.upsert(student, hash_password(plain))
    return len(SEED_STUDENTS)
