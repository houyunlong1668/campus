"""FakeProvider.generate_sql 的课程短语泛化。

回归自用户反馈：问「我的计算机导论成绩」词典不中 → kw=None → SQL 无
course 过滤 → 全表 14 行（一堆无关项）。词典仍是快路径；正则只兜尾部
「…课程短语+成绩」一种形态，短语含人称/指代/疑问字符一律不猜。
"""
from app.llm.fake import FakeProvider


async def _sql(question: str) -> str:
    return await FakeProvider().generate_sql(question, "[]")


async def test_词典内课程仍走词典快路径():
    assert "course LIKE '%高等数学%'" in await _sql("我的高等数学成绩")
    assert "course LIKE '%数据结构%'" in await _sql("我的数据结构成绩")


async def test_词典外课程从问句抠出短语_不再回全表():
    sql = await _sql("我的计算机导论成绩")
    assert "course LIKE '%计算机导论%'" in sql


async def test_他人成绩问句同样只查该课程():
    assert "course LIKE '%高等数学%'" in await _sql("陈默的高等数学成绩")


async def test_疑问短语不猜课_保持无过滤():
    # 平均分这类聚合问句要的是全表，猜成 LIKE '%平均%' 会一行都查不到
    assert "LIKE" not in await _sql("我这学期平均分多少")
    # 「查我的成绩」抠出来只能是「查我」——含人称，同样不猜
    assert "LIKE" not in await _sql("查我的成绩")
    assert "LIKE" not in await _sql("查成绩")   # 短语不足 2 字，不进正则
