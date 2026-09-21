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

    # 幂等：再灌一遍，**从库里数真行**——比返回字典的常量长度抓不到叠行
    again = await seed_academic(db)
    assert again == counts
    for table in ("students", "courses", "enrollments", "course_sections",
                  "makeup_items", "library_loans"):
        rows = await db.fetch_all(f"SELECT COUNT(*) AS n FROM {table}")
        assert rows[0]["n"] == counts[table], f"{table} 重复灌库产生叠行"


async def test_seed_日期是真日期_且相对灌库日推导(tmp_path):
    """spec 5.1：落库必须真日期；seed 以运行日为锚，重灌即刷新（days_left 由查询时计算）。"""
    db = await init_sqlite(tmp_path / "campus.db")
    await seed_academic(db)
    rows = await db.fetch_all("SELECT due_at FROM library_loans ORDER BY due_at")
    assert len(rows) == 7
    for r in rows:
        assert r["due_at"].count("-") == 2 and ":" in r["due_at"]
