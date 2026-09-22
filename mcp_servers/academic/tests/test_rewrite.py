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
