from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from ..llm.base import LLMProvider
from ..tools.base import ToolRegistry
from .nodes.generator import generator_node
from .nodes.router import router_node
from .nodes.tool_executor import tool_executor_node
from .state import AgentState


def build_graph(provider: LLMProvider, registry: ToolRegistry):
    async def router(state: AgentState):
        return await router_node(state, provider, registry)

    async def tool_executor(state: AgentState, writer: StreamWriter):
        return await tool_executor_node(state, registry, writer)

    async def generator(state: AgentState, writer: StreamWriter):
        return await generator_node(state, provider, writer)

    workflow = StateGraph(AgentState)
    workflow.add_node("router", router)
    workflow.add_node("tool_executor", tool_executor)
    workflow.add_node("generator", generator)
    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state["tool_name"] is not None,
        {True: "tool_executor", False: "generator"},
    )
    workflow.add_edge("tool_executor", "generator")
    workflow.add_edge("generator", END)
    return workflow.compile().with_config(recursion_limit=8)
