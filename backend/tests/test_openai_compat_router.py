"""openai_compat.route() 的工具调用消费规则。

真模型（deepseek-flash）对"我需要补考吗"这类问题常先调 list_pages 探路、
再调 resolve_page；route() 只执行一个工具时若机械取 tool_calls[0]，
就会把真正的 resolve_page 丢掉，跳转卡片永远不出现。
"""
from types import SimpleNamespace

from app.llm.base import RouteDecision
from app.llm.openai_compat import OpenAICompatProvider
from app.tools.base import ToolSpec


def _resp(*tool_calls):
    msg = SimpleNamespace(tool_calls=list(tool_calls), content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _call(name: str, arguments: str):
    # type 字段镜像真实 API 的联合判别键（Function|Custom 按 type 收窄）
    return SimpleNamespace(type="function",
                           function=SimpleNamespace(name=name, arguments=arguments))


def _provider(resp) -> OpenAICompatProvider:
    p = OpenAICompatProvider(base_url="http://x", model="m", api_key="k")
    completions = SimpleNamespace(create=lambda **kw: _aiter(resp))
    p.client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=completions))
    return p


async def _aiter(value):
    return value


TOOLS = [ToolSpec(name="list_pages", description="列页面", input_schema={"type": "object", "properties": {}}),
         ToolSpec(name="resolve_page", description="解析页面",
                  input_schema={"type": "object",
                                "properties": {"intent": {"type": "string"}},
                                "required": ["intent"]})]


async def test_探路调用排第一时取第一个可执行调用():
    p = _provider(_resp(
        _call("list_pages", "{}"),
        _call("resolve_page", '{"intent": "我需要补考吗"}'),
    ))
    d: RouteDecision = await p.route("我需要补考吗", TOOLS)
    assert d.tool_name == "resolve_page"
    assert d.tool_args == {"intent": "我需要补考吗"}


async def test_只有探路调用时视为不调用工具():
    p = _provider(_resp(_call("list_pages", "{}")))
    d = await p.route("我需要补考吗", TOOLS)
    assert d.tool_name is None


async def test_单resolve_page回归():
    p = _provider(_resp(_call("resolve_page", '{"intent": "查成绩"}')))
    d = await p.route("查成绩", TOOLS)
    assert d.tool_name == "resolve_page"
