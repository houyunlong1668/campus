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
