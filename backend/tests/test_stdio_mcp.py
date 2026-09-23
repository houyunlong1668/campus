import json
import os

from app.config import get_settings
from app.tools.stdio_mcp import stdio_registry


async def test_起真子进程_命中与未命中的返回结构():
    async with stdio_registry(get_settings().navigation_server_dir) as registry:
        assert sorted(t.name for t in await registry.list_tools()) == ["list_pages", "resolve_page"]

        hit = await registry.call_tool("resolve_page", {"intent": "查成绩"})
        assert hit.ok, hit.error
        assert json.loads(hit.data)["path"] == "/academic/grades"


async def test_server_侧工具异常转成_ok_False_不再被当成成功():
    """MCP 把工具异常包成 is_error 响应帧；不判它，双注册表语义就分歧、埋点数据也被污染。

    注意 MCP v2 不把 server 侧异常原文（ValueError: no matching page…）带给客户端，
    只给 "Error executing tool <name>"，真实原因留在 server stderr 日志里。
    """
    async with stdio_registry(get_settings().navigation_server_dir) as registry:
        miss = await registry.call_tool("resolve_page", {"intent": "今天天气怎么样"})

    assert not miss.ok
    assert miss.data is None
    assert "resolve_page" in miss.error


async def test_describe_schema_真路径返回全部四张视图(tmp_path):
    """list 型工具在 MCP 2.x 线上是"多个 text 块 + structured_content"。

    只取 content[0] 时 registry.data 只剩 v_grades 一张视图，"今天上什么课"
    "有哪些补考"这类查询在真环境必然写不出 SQL——而 InMemoryRegistry 直接给
    list，所有既有测试全绿（Task 6 修复轮端到端实测出的接缝）。
    """
    env = {**os.environ, "DB_BACKEND": "sqlite",
           "SQLITE_PATH": str(tmp_path / "campus.db")}
    async with stdio_registry(get_settings().academic_server_dir, env=env) as registry:
        res = await registry.call_tool("describe_schema", {})

    assert res.ok, res.error
    tables = json.loads(res.data)
    assert isinstance(tables, list)                      # 不是只剩一张视图的 dict
    assert [t["name"] for t in tables] == [
        "v_grades", "v_schedule", "v_makeup", "v_loans"]
