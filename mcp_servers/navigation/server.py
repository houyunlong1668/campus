import logging
from typing import Any

from mcp.server import MCPServer
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)  # stderr，严禁 print 到 stdout

server = MCPServer("navigation")


class PageEntry(BaseModel):
    path: str
    title: str
    keywords: list[str]
    capabilities: list[str]


class ResolvedPage(BaseModel):
    path: str
    title: str
    capabilities: list[str]


PAGE_REGISTRY: list[PageEntry] = [
    PageEntry(
        path="/academic/schedule",
        title="课表查询",
        keywords=["课表", "课程", "上什么课", "选课"],
        capabilities=["查看本学期课表", "按周次筛选课程"],
    ),
    PageEntry(
        path="/academic/grades",
        title="成绩查询",
        keywords=["成绩", "分数", "绩点", "查分"],
        capabilities=["查看各科成绩", "查看 GPA"],
    ),
    PageEntry(
        path="/academic/makeup",
        title="补考重修查询",
        keywords=["补考", "重修"],
        capabilities=["查看补考安排", "查看重修报名"],
    ),
    PageEntry(
        path="/library",
        title="图书馆服务",
        keywords=["图书馆", "借书", "还书", "图书"],
        capabilities=["查询馆藏", "查看借阅记录"],
    ),
]


def resolve_page_impl(intent: str) -> ResolvedPage:
    best: PageEntry | None = None
    best_score = 0.0
    for entry in PAGE_REGISTRY:
        matched = sum(1 for kw in entry.keywords if kw in intent)
        if matched == 0:
            continue
        score = matched / len(entry.keywords)
        if score > best_score:
            best, best_score = entry, score
    if best is None:
        raise ValueError("no matching page for intent")
    return ResolvedPage(path=best.path, title=best.title, capabilities=best.capabilities)


@server.tool()
async def list_pages() -> list[PageEntry]:
    """返回所有已注册页面及其能力描述与关键词。"""
    return PAGE_REGISTRY


@server.tool()
async def resolve_page(intent: str, params: dict[str, Any] | None = None) -> ResolvedPage:
    """把一句意图映射到具体页面路径，返回 {path, title, capabilities}。"""
    logging.info("resolve_page intent=%s params=%s", intent, params)
    return resolve_page_impl(intent)


if __name__ == "__main__":
    server.run(transport="stdio")
