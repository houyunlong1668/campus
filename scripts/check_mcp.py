import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp_servers" / "navigation"


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,  # 硬约束：不用字符串 "python"
        args=["server.py"],
        cwd=str(SERVER_DIR),     # 硬约束：绝对路径
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", names)
            assert "list_pages" in names and "resolve_page" in names

            result = await session.call_tool("resolve_page", {"intent": "查成绩"})
            print("resolve_page('查成绩') ->", result.content[0].text)
            assert "/academic/grades" in result.content[0].text


if __name__ == "__main__":
    asyncio.run(main())
