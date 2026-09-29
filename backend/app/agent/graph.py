from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from ..llm.base import LLMProvider
from ..tools.base import ToolRegistry
from ..write_ops import PendingActionStore
from .nodes.confirm_preparer import confirm_preparer_node
from .nodes.generator import generator_node
from .nodes.grader import grader_node
from .nodes.router import router_node
from .nodes.sql_executor import sql_executor_node
from .nodes.tool_executor import tool_executor_node
from .state import AgentState


def build_graph(provider: LLMProvider, registry: ToolRegistry,
                pending_actions=None):
    # 兜底按注 6：每次 build_graph 新建，不是模块级单例——单例会让
    # 图测试间共享待确认动作（串扰）；每图一个实例既让测试不传也能跑，又隔离。
    store = pending_actions if pending_actions is not None else PendingActionStore()

    async def router(state: AgentState):
        return await router_node(state, provider, registry)

    async def confirm_preparer(state: AgentState, writer: StreamWriter):
        return await confirm_preparer_node(state, store, writer)

    async def tool_executor(state: AgentState, writer: StreamWriter):
        return await tool_executor_node(state, registry, writer)

    async def sql_executor(state: AgentState, writer: StreamWriter):
        return await sql_executor_node(state, registry, provider, writer)

    async def grader(state: AgentState, writer: StreamWriter):
        return await grader_node(state, provider, writer)

    async def generator(state: AgentState, writer: StreamWriter):
        return await generator_node(state, provider, writer)

    workflow = StateGraph(AgentState)
    workflow.add_node("router", router)
    workflow.add_node("tool_executor", tool_executor)
    workflow.add_node("sql_executor", sql_executor)
    workflow.add_node("grader", grader)
    workflow.add_node("confirm_preparer", confirm_preparer)
    workflow.add_node("generator", generator)
    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {"navigate": "tool_executor", "query": "sql_executor",
         "answer": "generator", "write": "confirm_preparer",
         None: "generator"},
    )
    workflow.add_edge("tool_executor", "generator")
    # 写确认链路：confirm_preparer 只出卡不写，出完卡照常进 generator 说人话
    workflow.add_edge("confirm_preparer", "generator")
    # 条件编排：挂了 plan 且还没进 followup 轮 → grader 判分支；
    # followup 轮（orchestration_phase 已置）不再回 grader——循环守卫的
    # 图级防线，正常路径到不了 recursion_limit=10
    workflow.add_conditional_edges(
        "sql_executor",
        lambda state: "grader"
        if (state.get("orchestration") and not state.get("orchestration_phase"))
        else "generator",
    )
    workflow.add_conditional_edges(
        "grader",
        lambda state: "sql_executor"
        if state.get("orchestration_phase") == "followup" else "generator",
    )
    workflow.add_edge("generator", END)
    return workflow.compile().with_config(recursion_limit=10)
