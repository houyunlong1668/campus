import json

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
