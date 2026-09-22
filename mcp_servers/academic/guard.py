"""spec 4.3 校验清单：任一不过即拒绝，拒绝时不执行任何 SQL。

顺序固定：解析（含多语句、语句类型）→ 结构检查（关系白名单、身份列）→
正则检查（变量/危险子句/耗时函数/系统库）→ LIMIT 归一。
结构检查用 AST 是因为别名、大小写、嵌套只有解析才看得清；
正则检查用原文是为绕开方言解析差异（反引号、函数名变体），
两条路径各司其职，谁也别代替谁。
唯"解析失败"是例外：sqlite 方言本就读不了 MySQL 写法
（DATABASE()、INTO OUTFILE 在 sqlite 下直接 ParseError），
正则的存在理由恰是绕开方言解析差异，故解析抛异常时先交正则归类出
准确拒绝码，三者都不中才是规则 10 的 parse_error——依然拒绝，不降级。
"""
import re
import sqlglot
from dataclasses import dataclass
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

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


def _regex_refuse(sql: str) -> GuardResult | None:
    """规则 5-7 走原文正则，绕开方言解析差异。"""
    if _RE_VARIABLE.search(sql):
        return _refuse("variable", "不支持变量")
    if _RE_DANGEROUS.search(sql):
        return _refuse("dangerous_clause", "不支持")
    if _RE_COST.search(sql):
        return _refuse("cost_function", "不支持")
    return None


def _check_table(table: exp.Table, cte_names: set[str]) -> GuardResult | None:
    name = table.name.lower()
    db = (table.db or "").lower()
    if db in FORBIDDEN_SCHEMAS or name in FORBIDDEN_SCHEMAS:
        return _refuse("forbidden_schema", "该数据不在可查询范围")
    if name in cte_names and not db:
        # 仅非限定名可豁免：限定名（main.students）在任何引擎里都永远不指 CTE，
        # 直接落白名单判定；非限定且在可见 CTE 名内才是 CTE 引用
        # （SQL 同名遮蔽基表，FROM 解析到的是 CTE 本身）。
        return None
    if name not in WHITELIST:
        return _refuse("relation_not_whitelisted", "该数据不在可查询范围")
    return None


def _visible_cte_names(scope: Scope) -> set[str]:
    """作用域可见的 CTE 名 = 本层 + 全部祖先层，再剔除包住本作用域的 CTE。

    非递归 SQL 语义：CTE 体内看不到它自己；同理，一个 CTE 嵌在另一个
    CTE 体内时，外层那个在其自身体内也不可见——两者的体内同名引用解析到
    的都是真实基表，所以包住本作用域的 CTE 名一律剔除（fail-closed，
    剔重名更严不更松）。同一 WITH 的兄弟 CTE 不包住本作用域，仍可见。
    """
    enclosing: set[str] = set()
    node: exp.Expression | None = scope.expression
    while node is not None:
        if isinstance(node, exp.CTE):
            enclosing.add(node.alias.lower())
        node = node.parent
    names: set[str] = set()
    current: Scope | None = scope
    while current is not None:
        names.update(cte.alias.lower() for cte in current.ctes)
        current = current.parent
    return names - enclosing


def _check_relations(tree: exp.Expression) -> GuardResult | None:
    """规则 3（含禁库）：按作用域判定，CTE 名按可见性精确豁免。

    两道防线，都是从严：诱饵 CTE 只在兄弟子树里定义时给不了本处豁免
    （作用域感知）；作用域树算不出来时（traverse_scope 抛异常，或个别
    Table 节点没被任何 scope 收录）一律不豁免任何 CTE 名——算得出就精确，
    算不出就从严，绝不退回整树 CTE 平表那种比正常路径更松的判定。
    """
    seen: set[int] = set()
    try:
        scopes = list(traverse_scope(tree))
    except Exception:
        # fail-closed：拿不到作用域树就没有"可见 CTE 名"可言，零豁免。
        scopes = []
    for scope in scopes:
        visible = _visible_cte_names(scope)
        for table in scope.tables:
            seen.add(id(table))
            refusal = _check_table(table, visible)
            if refusal is not None:
                return refusal
    # 兜底：任何没落进作用域树的 Table 节点，从严——不豁免任何 CTE 名。
    for table in tree.find_all(exp.Table):
        if id(table) not in seen:
            refusal = _check_table(table, set())
            if refusal is not None:
                return refusal
    return None


def validate(sql: str, dialect: str) -> GuardResult:
    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except Exception:
        # 方言解析不了的输入先交正则归类（绕开方言解析差异），
        # 都不中才是真正的 parse_error；两条路径依然各司其职，不合并。
        refusal = _regex_refuse(sql)
        return refusal if refusal is not None else _refuse("parse_error", "查询语句无法解析")

    if len(statements) != 1 or statements[0] is None:
        return _refuse("multi_statement", "一次只允许一条查询")
    tree = statements[0]

    if not isinstance(tree, _QUERY_TYPES):
        return _refuse("not_query", "只能查询，不能修改数据")

    refusal = _check_relations(tree)
    if refusal is not None:
        return refusal

    for col in tree.find_all(exp.Column):
        if col.name.lower() in IDENTITY_COLUMNS:
            return _refuse("identity_column", "无需指定身份，系统已按你的账号过滤")

    refusal = _regex_refuse(sql)
    if refusal is not None:
        return refusal

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
