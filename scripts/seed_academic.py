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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.auth.passwords import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.base import Database  # noqa: E402
from app.db.database import build_database  # noqa: E402
from app.db.migrations import run_migrations  # noqa: E402
from app.db.upsert import save_row  # noqa: E402

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
    # 一律用 app.db.upsert.save_row（Task 3 已落地的方言无关"先查后写"）：
    # ON CONFLICT 是 SQLite/PG 语法，MySQL 8.4 不认；REPLACE INTO 是 DELETE+INSERT，
    # 会被子表外键 RESTRICT 挡住第二次幂等运行。
    # course_sections / makeup_items / library_loans 没有唯一键，重复 INSERT 会叠行；
    # 这三个表是"个人当前态"，全量替换（先清后灌）语义正确，幂等断言因此成立。
    await db.execute("DELETE FROM course_sections")
    await db.execute("DELETE FROM makeup_items")
    await db.execute("DELETE FROM library_loans")

    counts: dict[str, int] = {}
    for sid, name, major, cls, college in STUDENTS:
        await save_row(db, "students", {"student_id": sid},
                       {"name": name, "password_hash": hash_password(SEED_PASSWORD),
                        "major": major, "class_name": cls, "college": college})
    counts["students"] = len(STUDENTS)

    for code, name, credits, teacher, college, kind, domain in COURSES:
        await save_row(db, "courses", {"course_code": code},
                       {"course_name": name, "credits": credits, "teacher": teacher,
                        "college": college, "kind": kind, "domain": domain})
    counts["courses"] = len(COURSES)

    for sid, code, name, term, credits, score, teacher in ENROLLMENTS:
        await save_row(db, "enrollments",
                       {"student_id": sid, "course_code": code, "term": term},
                       {"course_name": name, "credits": credits, "score": score,
                        "grade_points": points(score), "teacher": teacher})
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
