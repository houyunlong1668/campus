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


class TestCTE白名单绕过回归:
    def test_CTE体内读基表_限定名必须拒(self):
        # 限定名 main.students 在任何引擎里都永远不指 CTE——
        # 旧版按裸名豁免把它放行，实测读出基表全部行（Critical 白名单绕过）。
        assert code_of("WITH students AS (SELECT * FROM main.students) SELECT * FROM students") \
            == "relation_not_whitelisted"

    def test_CTE体内自引用_非限定也必须拒(self):
        # 非递归 SQL 语义里 CTE 体内看不到自己的名字，体内同名引用解析到
        # 真实基表。引擎可能自己挡住（SQLite 报 circular reference），但
        # guard 必须先拒——不能依赖引擎侥幸。
        assert code_of("WITH students AS (SELECT * FROM students) SELECT * FROM students") \
            == "relation_not_whitelisted"

    def test_合法CTE仍然放行_别把放行测试修红(self):
        assert validate("WITH t AS (SELECT 1 AS a) SELECT a FROM t", DIALECT).ok

    def test_兄弟子树诱饵CTE不给豁免(self):
        # 诱饵 CTE students 在派生表子查询里声明，外层标量子查询里的
        # FROM students 是指向真基表的兄弟子树引用——不能搭诱饵的便车。
        assert code_of(
            "SELECT (SELECT COUNT(*) FROM students) "
            "FROM (WITH students AS (SELECT 1 AS x) SELECT * FROM students) u"
        ) == "relation_not_whitelisted"
