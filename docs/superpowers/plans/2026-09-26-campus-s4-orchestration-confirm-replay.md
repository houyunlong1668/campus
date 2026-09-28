# S4 多工具条件编排 + 操作确认与回放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 兑现 roadmap spec §4 的完整编排能力——`grader` 条件分支（阈值/LLM 双模式）、中间结果累加、工具失败降级、`recursion_limit` 守卫、`POST /confirm` 写操作确认（首个写操作：补考报名）、`POST /replay` 执行回放，旗舰演示「查上学期高数成绩，不及格就告诉我补考时间」一次跑通。

**Architecture:** 图从「router → 三态 → generator」扩为五节点：router 之后可进 `grader`（条件分支，then 时把 followup 问句写回 state 再走一轮 sql_executor）、可进 `confirm_preparer`（写意图 → 待确认动作 + `confirm_card` 事件）。编排计划由 provider 新方法 `plan()` 产出（fake 规则、真模型一次 JSON 调用），不改 `route()` 的 function-calling 管线。每步参数/耗时记进 `step_details`（新列 `step_details_json`），`steps` 保持纯节点名数组——S5 路径合规规则与既有前端都不动。写操作不走 MCP：补考报名是 REST 写，只有 `POST /confirm` 能触发，待确认动作存内存 `PendingActionStore`（TTL 600s、一次性 pop、属主校验）。

**Tech Stack:** FastAPI + langgraph、`pydantic`、aiosqlite/aiomysql、Vue 3 + vitest、k6。

**Spec:** `docs/superpowers/specs/2026-09-22-campus-roadmap-s4-s7-design.md` §4（范围/明确不做/验收五条）；接入点承接 `docs/superpowers/specs/2026-09-18-campus-agent-mvp-design.md` §10（`grader` 加节点、`tool_results` dict 累加、`POST /confirm`、`tool_calls.steps_json` 即埋点）。

## Global Constraints

- 调用方 SQL 一律写 `?` 占位符；`%s` 只许出现在驱动转换函数里（`backend/app/db/database.py` 与 `mcp_servers/academic/db.py`）。
- DDL 方言差异只许出现在 `backend/app/db/migrations/{mysql,sqlite}/` 文件里，代码里不许有方言分支。
- 迁移文件名集合双方言必须一致（`scripts/check_routes_contract.py` 有断言，会自动覆盖 0004）。
- `student_id` 永不出现在请求体；`POST /confirm` 的身份来自会话，且必须与会话创建待确认动作时存的 `student_id` 相等（属主校验）。
- **工具异常不向上抛**：两个 registry 的 `call_tool` 已用 `timed_call` 统一降级为 `ok=False`（`backend/app/tools/base.py:57`），S4 不许在节点里再包 try-catch 破坏这层语义。
- 写 SQL 幂等：补考报名重复提交返回 `already`，不许叠行、不许 500。
- 测试全跑 SQLite（`DB_BACKEND=sqlite`）；跑 Python 一律 `backend/.venv/Scripts/python.exe`（裸 `python` 是 Windows Store 假解释器）。
- 每个任务结束时提交一次。
- `demo1234` 是本地仿真密码，不入库真值、不上公网。

## 与 spec 的显式偏离与裁决（先记账，评审按此判定）

1. **编排计划走 provider 独立方法 `plan()`，不塞进 `RouteDecision`**：spec §4 只说「`grader` 节点 + `add_conditional_edges`：条件分支，同时支持硬编码阈值与 LLM 判断两种模式」，没规定计划从哪来。`route()` 是 function-calling 管线，编排计划是路由之后的二次判断；独立方法让 fake 可用纯规则实现，真模型只在命中触发词时多花一次廉价 JSON 调用（导航/闲聊消息零额外开销）。
2. **`POST /replay` 是回放展示，不重执行节点**：真重放会让写操作双写（点两次回放报两次名），与 `/confirm` 一次性语义直接冲突。roadmap 验收 3 只要求「返回上次的节点序列、每步参数与耗时，与 `tool_calls.steps_json` 一致」——展示即满足。
3. **`steps` 保持 `list[str]`，每步参数/耗时进新列 `step_details_json`**：S5 路径合规三条规则（同节点连续 >3 次 / Router 后直接 Generator / Generator 后回 Router）和既有前端 `DoneEvent.steps`、全部现有测试都消费字符串数组；混装 dict 会把它们全改且规则变脆。
4. **写操作不进 MCP**：spec 范围原文是「新增一个**写操作 API**（首个候选：补考报名提交）」。补考报名是 REST 写端点，唯一入口 `POST /confirm`（图中 `confirm_preparer` 只产确认卡不执行）；不自建 `write-mcp`，YAGNI。
5. **seed 数据为旗舰验收服务**：20230001 的「高等数学（下）」改成 2026 春 56 分并新增对应补考条目（status=报名中），否则「高数不及格」问句永远走 else 分支、验收 1 演不出 then 链路。既有测试若钉住旧分数/行数，按新 seed 更新断言并在任务报告注明——这是计划认可的测试数据变更，不是行为回归。

## 现状关键接口（基线 main 5361e5e）

- `AgentState`（`backend/app/agent/state.py`）：`tool_results: dict[str, Any]`（**无** Annotated 合并，节点返回全量覆盖）、`steps: Annotated[list[str], operator.add]`、`sql: dict | None`、`route: Literal["navigate","query","answer"] | None`。
- `build_graph(provider, registry)`（`backend/app/agent/graph.py`）：四节点，三态条件边，`recursion_limit=8`，`tool_executor→generator`、`sql_executor→generator`。
- `sql_executor_node`：先补跑 `resolve_page`（输入驱动），再 `describe_schema → generate_sql → run_sql`，`_maybe_clarify` 跨学期歧义出澄清。
- `LLMProvider` 协议（`backend/app/llm/base.py`）：`route / generate_sql / stream_answer` 三方法。
- `record_exchange(...)`（`backend/app/db/repository.py`）：三 INSERT 无事务，`tool_calls.steps_json` 存节点名 JSON。
- `makeup_items` 表：status ∈ `已报名/待缴费/报名中`，20230001 有三条（大学物理 已报名 / 体育 待缴费 / 概率论 报名中）。

---

## File Structure

**新建：**

| 文件 | 单一职责 |
|---|---|
| `backend/app/db/migrations/{mysql,sqlite}/0004_step_details_and_registrations.sql` | `tool_calls` 加 `step_details_json` 列 + 新建 `makeup_registrations` 表（双方言同名同文件数） |
| `backend/app/write_ops.py` | `register_makeup(db, student_id, course_code)` 纯写逻辑 + `PendingActionStore`（内存、TTL、一次性 pop、属主校验） |
| `backend/app/api/confirm.py` | `POST /confirm`：pop 待确认动作 → 执行写操作 |
| `backend/app/api/replay.py` | `POST /replay`：返回最近一次执行的 steps/step_details/参数/耗时 |
| `backend/app/agent/nodes/grader.py` | 条件分支节点：阈值/LLM 双模式、失败降级、then/else/degraded 三分支 |
| `backend/app/agent/nodes/confirm_preparer.py` | 写意图 → 待确认动作 + `confirm_card` SSE 事件 |
| `backend/tests/test_orchestration.py` | grader 双模式、降级、循环守卫、旗舰全链路 |
| `backend/tests/test_write_ops.py` | 写服务幂等/状态翻转、PendingActionStore、/confirm API、/replay API |
| `frontend/src/components/chat/ConfirmCard.vue` | 确认卡（课程摘要 + 确认按钮 + 内联结果） |
| `frontend/tests/confirmCard.test.ts` | 确认卡交互（点击 → POST /confirm → 成功/失败内联展示） |

**修改：** `backend/app/agent/state.py`（新字段 + tool_results 合并）、`backend/app/agent/plan.py`（编排模型）、`backend/app/llm/{base,fake,openai_compat}.py`（`plan()`/`judge()`）、`backend/app/agent/nodes/{router,sql_executor,tool_executor,generator}.py`（step_details、phase 处理）、`backend/app/agent/graph.py`（五节点与条件边）、`backend/app/api/chat.py`（initial_state、落库 step_details）、`backend/app/db/repository.py`（`record_exchange` 加参 + `latest_trace`）、`backend/app/main.py`（pending store + 两个新 router）、`scripts/seed_academic.py`（旗舰数据）、`frontend/src/{types.ts,composables/useChatStream.ts}`、`frontend/src/components/chat/{ChatBox,MessageBubble,MessageList}.vue`、`k6/tests/authz.js`、`k6/tests/sse_chat.js`。

---

### Task 1: 迁移 0004（step_details_json + makeup_registrations）与旗舰 seed 数据

**Files:**
- Create: `backend/app/db/migrations/sqlite/0004_step_details_and_registrations.sql`
- Create: `backend/app/db/migrations/mysql/0004_step_details_and_registrations.sql`
- Modify: `scripts/seed_academic.py`（ENROLLMENTS 与 makeups 两列表头数据）
- Test: `backend/tests/test_database.py`（扩展现有用例即可，见 Step 2）

**Interfaces:**
- Consumes: 迁移器按文件名排序执行、`assert_current_schema` 校验列集合（既有机制不动）。
- Produces: `tool_calls.step_details_json TEXT NOT NULL`（代码侧 INSERT 永远写 `'[]'` 或 JSON，不靠 DDL 默认值）；`makeup_registrations(id, student_id, course_code, course_name, kind, created_at)` 带 `UNIQUE(student_id, course_code)`。

- [ ] **Step 1: 写双方言迁移文件**

`backend/app/db/migrations/sqlite/0004_step_details_and_registrations.sql`：

```sql
ALTER TABLE tool_calls ADD COLUMN step_details_json TEXT NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS makeup_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL,
    course_name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '补考',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, course_code)
);
```

`backend/app/db/migrations/mysql/0004_step_details_and_registrations.sql`：

```sql
ALTER TABLE tool_calls ADD COLUMN step_details_json TEXT NOT NULL;
CREATE TABLE IF NOT EXISTS makeup_registrations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NOT NULL,
    course_code VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT '补考',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_makeup_reg (student_id, course_code)
);
```

注意：MySQL 8.4 的 `TEXT` 不能用字面 DEFAULT（语法限制），所以 `step_details_json` 的默认值 `'[]'` 只放 SQLite 侧，MySQL 侧由代码保证永远显式写入（Task 2 的 repository 修改落实）。`makeup_registrations` 双方言**都不**建外键（与 MySQL 侧 `tool_calls` 等表一致，S2 已裁决 MySQL 迁移不带 FK）。

- [ ] **Step 2: 先跑契约与现有库测试，确认红**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_database.py -q`
Expected: 现有用例 PASS（0004 还没被任何测试引用），契约脚本稍后 Step 5 跑。

- [ ] **Step 3: 改 seed——高等数学（下）56 分 + 对应补考条目**

`scripts/seed_academic.py` 的 `ENROLLMENTS` 里找 `("20230001", "MATH2041", ...)`：已存在就把分数改成 56、学期确保为 `2026 春`；不存在就新增一行：

```python
("20230001", "MATH2041", "高等数学（下）", "2026 春", 5, 56, "王建国"),
```

`makeups` 列表新增（字段顺序与既有三条完全一致：student_id, course_name, course_code, kind, reason, scheduled_at, place, status, seats_left, seats_total）：

```python
("20230001", "高等数学（下）", "MATH2041", "补考", "期末 56 分，未达 60 分线",
 dt(15, 9), "主楼 A302", "报名中", 40, 80),
```

`dt(15, 9)` 与既有写法一致（本月 15 日 09:00 之类，读文件头部确认 `dt` 定义后照抄用法）。「报名中」状态是关键：它是唯一可被 `/confirm` 翻转成「已报名」的状态，旗舰演示与写测试都靠它。

- [ ] **Step 4: 重建本地 SQLite 并灌库，验证数据形状**

Run:
```bash
cd backend && rm -f data/dev.db && DB_BACKEND=sqlite ./.venv/Scripts/python.exe ../scripts/seed_academic.py
cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('data/dev.db'); print(c.execute(\"SELECT course_name, score, term FROM enrollments WHERE student_id='20230001' AND course_code='MATH2041'\").fetchall()); print(c.execute(\"SELECT course_name, status FROM makeup_items WHERE student_id='20230001' AND course_code='MATH2041'\").fetchall()); print(c.execute('PRAGMA table_info(tool_calls)').fetchall())"
```
Expected: `[('高等数学（下）', 56, '2026 春')]`；`[('高等数学（下）', '报名中')]`；`tool_calls` 列里能看到 `step_details_json`。

- [ ] **Step 5: 跑全量后端测试，处理被 seed 变更钉住的断言**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: 若有失败是旧测试把 20230001 的分数/行数写死了——按新 seed 更新断言（这是裁决 5 认可的测试数据变更），在任务报告里逐条列出改了哪些断言。

- [ ] **Step 6: 跑契约脚本**

Run: `cd backend && ./.venv/Scripts/python.exe ../scripts/check_routes_contract.py`
Expected: OK（迁移文件名集合双方言一致被自动覆盖）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/migrations/sqlite/0004_step_details_and_registrations.sql backend/app/db/migrations/mysql/0004_step_details_and_registrations.sql scripts/seed_academic.py backend/tests/
git commit -m "feat(db): 0004 迁移——tool_calls.step_details_json 与 makeup_registrations 表；seed 补旗舰演示数据"
```

---

### Task 2: State 扩展、编排模型与 step_details 埋点

**Files:**
- Create: `backend/app/agent/plan.py`
- Modify: `backend/app/agent/state.py`
- Modify: `backend/app/llm/base.py`
- Modify: `backend/app/agent/nodes/router.py`、`backend/app/agent/nodes/sql_executor.py`、`backend/app/agent/nodes/tool_executor.py`、`backend/app/agent/nodes/generator.py`
- Modify: `backend/app/db/repository.py`
- Test: `backend/tests/test_graph.py`（扩展现有断言）

**Interfaces:**
- Consumes: Task 1 的 `step_details_json` 列。
- Produces（后续任务全靠这些名字）：
  - `OrchestrationPlan(BaseModel)`: `condition: ThresholdCondition | LlmCondition`、`followup_user_input: str | None`
  - `ThresholdCondition`: `mode="threshold"`, `column: str`, `op: Literal["lt","le","gt","ge","eq","ne"] = "lt"`, `value: float`
  - `LlmCondition`: `mode="llm"`, `condition_text: str`
  - `WriteIntent(BaseModel)`: `action: Literal["makeup_register"] = "makeup_register"`, `course_code: str`, `course_name: str = ""`, `summary: str = ""`
  - `PlanBundle(BaseModel)`: `orchestration: OrchestrationPlan | None = None`, `write: WriteIntent | None = None`
  - `LLMProvider` 协议新增：`async def plan(self, user_input: str, route: str) -> PlanBundle` 与 `async def judge(self, condition_text: str, evidence: dict) -> bool`
  - `AgentState` 新字段：`orchestration`、`write`、`orchestration_phase: Literal["followup"] | None`、`branch: str | None`、`next_query: str | None`、`confirm_card: dict | None`、`sql_history: list[dict]`、`step_details: list[dict]`；`tool_results` 改为 `Annotated[dict, _merge_results]`
  - `record_exchange(..., step_details: list[dict] | None = None)`；Protocol 同步加签名。

- [ ] **Step 1: 写编排模型 `backend/app/agent/plan.py`**

```python
from typing import Literal

from pydantic import BaseModel, Field


class ThresholdCondition(BaseModel):
    mode: Literal["threshold"] = "threshold"
    column: str
    op: Literal["lt", "le", "gt", "ge", "eq", "ne"] = "lt"
    value: float


class LlmCondition(BaseModel):
    mode: Literal["llm"] = "llm"
    condition_text: str


class OrchestrationPlan(BaseModel):
    """grader 的输入：怎么判、判中了再干什么。followup 为空 = 纯分支无后续。"""

    condition: ThresholdCondition | LlmCondition = Field(discriminator="mode")
    followup_user_input: str | None = None


class WriteIntent(BaseModel):
    action: Literal["makeup_register"] = "makeup_register"
    course_code: str
    course_name: str = ""
    summary: str = ""


class PlanBundle(BaseModel):
    orchestration: OrchestrationPlan | None = None
    write: WriteIntent | None = None
```

- [ ] **Step 2: 写失败测试——tool_results 累加与 step_details 记录**

`backend/tests/test_graph.py` 追加（现有 fixture 复用，名字按文件里既有风格）：

```python
def test_tool_results_累加不被覆盖():
    # 两次 executor 结果同在：第二次返回的 dict 与第一次合并，不是覆盖
    ...

def test_每节点都留step_details():
    # 跑一条 query 链路，断言 final_state["step_details"] 里
    # node 依次含 router/sql_executor/generator，且每个都有 latency_ms(int) 与 detail(dict)
    ...
```

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_graph.py -q`
Expected: FAIL（`_merge_results` / `step_details` 不存在）。

- [ ] **Step 3: 扩展 `state.py`**

```python
import operator
from typing import Annotated, Any, Literal, TypedDict

from .plan import OrchestrationPlan, WriteIntent


def _merge_results(a: dict | None, b: dict | None) -> dict:
    """tool_results 跨节点累加：同 key 后者覆盖（同工具重跑），异 key 并集。"""
    return {**(a or {}), **(b or {})}


class AgentState(TypedDict):
    user_input: str
    student_id: str
    history: list[dict[str, str]]
    intent: str | None
    route: Literal["navigate", "query", "answer", "write"] | None
    orchestration: OrchestrationPlan | None     # grader 的判定计划（Task 5 消费）
    write: WriteIntent | None                   # 待确认的写意图（Task 6 消费）
    orchestration_phase: Literal["followup"] | None  # grader 已放行 followup 的标记
    branch: str | None                          # grader 结果：then/else/degraded
    next_query: str | None                      # followup 问句，sql_executor 优先于 user_input
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_results: Annotated[dict[str, Any], _merge_results]
    answer: str
    nav_card: dict[str, Any] | None
    needs_clarification: bool
    clarification: dict[str, Any] | None
    sql: dict[str, Any] | None
    sql_history: Annotated[list[dict], operator.add]   # 每一轮查数的 sql_state 快照
    confirm_card: dict[str, Any] | None                # 待用户点击的确认卡
    step_details: Annotated[list[dict], operator.add]  # 每步 {node, latency_ms, detail}
    steps: Annotated[list[str], operator.add]
    error: str | None
```

- [ ] **Step 4: 扩展 `llm/base.py` 协议**

```python
from ..agent.plan import PlanBundle

class LLMProvider(Protocol):
    async def route(self, user_input: str, tools: list[ToolSpec]) -> RouteDecision: ...
    async def generate_sql(self, user_input: str, schema_json: str) -> str: ...
    async def plan(self, user_input: str, route: str) -> PlanBundle:
        """编排二次判断：route 已定后，问「这句要不要条件分支/写确认」。
        默认实现返回空 PlanBundle（无编排）；命中触发词的 query/answer 才可能非空。"""
        ...
    async def judge(self, condition_text: str, evidence: dict) -> bool:
        """LLM 模式条件判断：evidence 含 columns/rows，只许回答布尔。"""
        ...
    def stream_answer(self, user_input: str, state: AgentState) -> AsyncIterator[str]: ...
```

- [ ] **Step 5: 四个既有节点补 step_details（sql_history 累加在 sql_executor）**

每个节点函数开头 `start = time.perf_counter()`，return 的字典里统一带：

```python
"step_details": [{"node": "<节点名>",
                  "latency_ms": int((time.perf_counter() - start) * 1000),
                  "detail": {...}}],
```

`detail` 内容（刻意小，回放给人看）：
- `router`：`{"tool_name": decision.tool_name}`（幻觉拦截分支用实际值）
- `tool_executor`：`{"tool_name": name, "ok": result.ok}`
- `sql_executor`：`{"sql": raw_sql[:200], "row_count": sql_state["row_count"], "refused_code": sql_state["refused_code"]}`
- `generator`：`{"answer_chars": len(answer)}`（流式循环结束后算）

`sql_executor_node` 额外：return 前把本轮 `sql_state` 追加 `"sql_history": [sql_state]`（澄清提前 return 的分支同样要追加）。

`router.py` 的 `_route_of` 保持三态不动——write 路由在 Task 6 加。

- [ ] **Step 6: `repository.py` 落库 step_details**

`ConversationRepository` Protocol 与 `DbConversationRepository` 的 `record_exchange` 加关键字参数 `step_details: list[dict] | None = None`；`tool_calls` 的 INSERT 语句加一列：

```python
"""INSERT INTO tool_calls
   (conversation_id, tool_name, args_json, ok, error, latency_ms, steps_json, step_details_json)
   VALUES (?,?,?,?,?,?,?,?)""",
(conv_id, tool_call.tool_name, tool_call.args_json,
 int(tool_call.ok), tool_call.error, tool_call.latency_ms,
 json.dumps(steps, ensure_ascii=False),
 json.dumps(step_details or [], ensure_ascii=False)),
```

- [ ] **Step 7: `api/chat.py` 的 initial_state 与 persist 适配**

`initial_state` 字典补：`"orchestration": None, "write": None, "orchestration_phase": None, "branch": None, "next_query": None, "sql_history": [], "confirm_card": None, "step_details": []`。

`persist()` 里 `record_exchange(..., step_details=state.get("step_details") or [])`。

- [ ] **Step 8: 跑测试**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: 全 PASS（新增两条 + 既有全部；既有 steps 断言不受影响，step_details 是纯增量）。

- [ ] **Step 9: Commit**

```bash
git add backend/app/agent/plan.py backend/app/agent/state.py backend/app/llm/base.py backend/app/agent/nodes/ backend/app/db/repository.py backend/app/api/chat.py backend/tests/test_graph.py
git commit -m "feat(agent): state 扩展——编排计划字段、tool_results 累加合并、step_details 每步埋点"
```

---

### Task 3: 写操作服务 + PendingActionStore + POST /confirm

**Files:**
- Create: `backend/app/write_ops.py`
- Create: `backend/app/api/confirm.py`
- Modify: `backend/app/main.py`（挂 store 与 router）
- Test: `backend/tests/test_write_ops.py`

**Interfaces:**
- Consumes: Task 1 的 `makeup_registrations` 表与 seed 的「报名中」条目。
- Produces:
  - `async def register_makeup(db, student_id: str, course_code: str) -> dict` → `{"status": "registered"|"already", "course": str, "kind": str}`
  - `class WriteOpError(Exception)`
  - `class PendingActionStore`: `create(student_id, action, params) -> str`、`pop(action_id, student_id) -> PendingAction | None`
  - `POST /confirm` 请求体 `{"action_id": str}`（extra="forbid"）；200 `{"ok": true, "result": {...}}`；404 动作不存在/过期/不属本用户；400 写操作业务失败（如无此课程）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_write_ops.py`：

```python
"""写操作服务与 /confirm 端点：幂等、属主校验、鉴权。"""
import pytest

from ..conftest import *  # 复用既有 app/client fixture（按既有测试文件的引法）


@pytest.mark.asyncio
async def test_报名中课程可注册并翻转状态(client, db):
    # 20230001 的 MATH2041 seed 为「报名中」
    r = await _confirm(client, course_code="MATH2041")
    assert r.status_code == 200 and r.json()["result"]["status"] == "registered"
    r2 = client.get("/api/makeup")
    item = next(i for i in r2.json()["items"] if i["code"] == "MATH2041")
    assert item["status"] == "已报名"


@pytest.mark.asyncio
async def test_重复确认幂等返回already(client):
    ...  # 第一次 registered，第二次（动作已 pop，404）≠ 幂等场景；
        # 幂等指 register_makeup 直接调两次：第二次 already 且 makeup_items 无重复行


@pytest.mark.asyncio
async def test_已报名课程再报返回already(client):
    ...  # 大学物理 PHY1031 seed 已「已报名」→ already


@pytest.mark.asyncio
async def test_无此课程返回400(client):
    ...  # register_makeup 抛 WriteOpError → HTTP 400


@pytest.mark.asyncio
async def test_无Cookie打confirm返回401(client):
    ...


@pytest.mark.asyncio
async def test_动作不存在或属主不符返回404(client):
    ...  # 先登录 20230001 拿合法 action_id，再登录 20230002 pop 它 → 404
```

fixture 名字以既有 `backend/tests/` 里 API 测试的实际 fixture 为准（读 `test_academic_api.py` 头部照抄 client 构造）。`_confirm`  helper 直接调 `app.state.pending_actions.create(...)` 造合法 action_id 再 POST——本任务不依赖图的写意图链路（那是 Task 6）。

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_write_ops.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 2: 实现 `write_ops.py`**

```python
"""写操作与待确认动作。写一律先经 PendingActionStore 确认（spec §4 /confirm 语义）。"""
import time
import uuid
from dataclasses import dataclass, field

from .db.base import Database


class WriteOpError(Exception):
    """写操作业务失败（如无对应课程、状态不允许），映射 HTTP 400。"""


async def register_makeup(db: Database, student_id: str, course_code: str) -> dict:
    """补考/重修报名：幂等（UNIQUE(student_id, course_code) 语义用先查后写实现，
    单用户演示无并发写者；不堆方言分支）。报名中→已报名，其余状态只登记不翻转。"""
    rows = await db.fetch_all(
        "SELECT course_name, kind, status FROM makeup_items"
        " WHERE student_id = ? AND course_code = ?", (student_id, course_code))
    if not rows:
        raise WriteOpError(f"没有课程 {course_code} 的补考或重修条目")
    item = rows[0]
    existing = await db.fetch_all(
        "SELECT id FROM makeup_registrations WHERE student_id = ? AND course_code = ?",
        (student_id, course_code))
    if existing:
        return {"status": "already", "course": item["course_name"], "kind": item["kind"]}
    await db.execute(
        "INSERT INTO makeup_registrations (student_id, course_code, course_name, kind)"
        " VALUES (?,?,?,?)",
        (student_id, course_code, item["course_name"], item["kind"]))
    if item["status"] == "报名中":
        await db.execute(
            "UPDATE makeup_items SET status = '已报名'"
            " WHERE student_id = ? AND course_code = ? AND status = '报名中'",
            (student_id, course_code))
    return {"status": "registered", "course": item["course_name"], "kind": item["kind"]}


@dataclass
class PendingAction:
    action_id: str
    student_id: str
    action: str
    params: dict
    expires_at: float


@dataclass
class PendingActionStore:
    """内存待确认动作：TTL 默认 600s，pop 一次性（确认即焚），
    属主校验（student_id 不匹配返回 None）。重启即清空——确认卡随之失效，
    与 SessionStore 同为内存语义（spec2 §1 已确认可接受）。"""

    ttl_seconds: int = 600
    _items: dict = field(default_factory=dict)

    def create(self, student_id: str, action: str, params: dict) -> str:
        self._sweep()
        action_id = uuid.uuid4().hex
        self._items[action_id] = PendingAction(
            action_id, student_id, action, params,
            time.monotonic() + self.ttl_seconds)
        return action_id

    def pop(self, action_id: str, student_id: str) -> PendingAction | None:
        self._sweep()
        item = self._items.pop(action_id, None)  # 无论成败先 pop：一次性语义
        if item is None or item.student_id != student_id:
            return None
        return item

    def _sweep(self) -> None:
        now = time.monotonic()
        dead = [k for k, v in self._items.items() if v.expires_at < now]
        for k in dead:
            del self._items[k]
```

- [ ] **Step 3: 实现 `api/confirm.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth.deps import require_student
from ..auth.students import Student
from ..write_ops import WriteOpError, PendingActionStore, register_makeup

router = APIRouter()


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=64)


@router.post("/confirm")
async def confirm(request: ConfirmRequest, req: Request,
                  student: Student = Depends(require_student)):
    store: PendingActionStore = req.app.state.pending_actions
    action = store.pop(request.action_id, student.student_id)
    if action is None:
        # 不区分「不存在」「过期」「别人的」：三种都不该告诉请求者细节
        raise HTTPException(status_code=404, detail="确认请求不存在或已过期")
    if action.action == "makeup_register":
        try:
            result = await register_makeup(req.app.state.db, student.student_id,
                                           action.params["course_code"])
        except WriteOpError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "result": result}
    raise HTTPException(status_code=400, detail=f"未知动作: {action.action}")
```

- [ ] **Step 4: `main.py` 装配**

lifespan 里 `app.state.sessions = ...` 之后加 `app.state.pending_actions = PendingActionStore()`；`create_app` 里 `app.include_router(confirm_router)`（import 与现有三行同款）。

- [ ] **Step 5: 跑测试**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests/test_write_ops.py -q`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/app/write_ops.py backend/app/api/confirm.py backend/app/main.py backend/tests/test_write_ops.py
git commit -m "feat(confirm): 补考报名写操作 + 待确认动作存储 + POST /confirm"
```

---

### Task 4: provider 编排能力（fake 规则 + 真模型 plan/judge）

**Files:**
- Modify: `backend/app/llm/fake.py`
- Modify: `backend/app/llm/openai_compat.py`
- Test: `backend/tests/test_orchestration.py`（本任务只测 fake.plan/judge 纯规则）

**Interfaces:**
- Consumes: Task 2 的 `PlanBundle`/`OrchestrationPlan`/`WriteIntent` 与协议签名。
- Produces:
  - `FakeProvider.plan(user_input, route) -> PlanBundle`：触发词「不及格/低于/如果…就」且 route=="query" → `OrchestrationPlan(ThresholdCondition(column="score", op="lt", value=60), followup_user_input="我的补考和重修时间安排")`；「报名」+ 已知课程名且 route=="answer" → `WriteIntent`。
  - `FakeProvider.judge(condition_text, evidence)`：evidence rows 里任一数值 < 60 → True（LLM 模式的 fake 兜底实现）。
  - `FakeProvider.generate_sql` 新增分支：`"补考" in user_input → "SELECT course, kind, scheduled_at, place, status FROM v_makeup"`。
  - `OpenAICompatProvider.plan/judge`：JSON 调用。

- [ ] **Step 1: 写失败测试（fake 规则）**

`backend/tests/test_orchestration.py`（文件创建，后续 Task 5 继续往里加）：

```python
"""S4 编排：fake 规则、grader、降级、循环守卫。"""
from app.agent.plan import ThresholdCondition
from app.llm.fake import FakeProvider


class TestFakePlan:
    async def test_不及格触发阈值编排(self):
        bundle = await FakeProvider().plan("查我上学期高数成绩，不及格就告诉我补考时间", "query")
        assert bundle.orchestration is not None
        assert bundle.orchestration.condition == ThresholdCondition(column="score", value=60)
        assert bundle.orchestration.followup_user_input

    async def test_纯取数不触发编排(self):
        bundle = await FakeProvider().plan("我这学期平均分多少", "query")
        assert bundle.orchestration is None and bundle.write is None

    async def test_报名触发写意图(self):
        bundle = await FakeProvider().plan("帮我报名大学物理（上）的补考", "answer")
        assert bundle.write is not None and bundle.write.course_code == "PHY1031"

    async def test_judge对分数行给布尔(self):
        assert await FakeProvider().judge("是否有不及格", {"columns": ["score"], "rows": [[91], [56]]}) is True
        assert await FakeProvider().judge("是否有不及格", {"columns": ["score"], "rows": [[91]]}) is False


class TestFakeSql补考分支:
    async def test_补考问句查v_makeup(self):
        sql = await FakeProvider().generate_sql("我的补考和重修时间安排", "[]")
        assert "v_makeup" in sql and "v_grades" not in sql
```

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestration.py -q`
Expected: FAIL（`plan`/`judge`/补考分支都不存在）。

- [ ] **Step 2: 实现 `FakeProvider.plan/judge` 与补考 SQL 分支**

`fake.py` 头部加常量：

```python
from ..agent.plan import (OrchestrationPlan, PlanBundle, ThresholdCondition,
                          WriteIntent)

# 报名意图：课程短语 → 课程代码（fake 的确定性词典，与 _SQL_KEYWORDS 同风格）
_REGISTER_COURSES = {"大学物理": "PHY1031", "高等数学": "MATH2041",
                     "体育": "PE1011", "概率论": "MATH2042"}
_ORCHESTRATE_HINTS = ("不及格", "低于", "如果", "就告诉", "就提醒")
```

`FakeProvider` 加两个方法：

```python
    async def plan(self, user_input: str, route: str) -> PlanBundle:
        """编排二次判断（裁决 1：route 之后的独立方法）。
        只有 query 才可能挂条件分支、只有 answer 才可能藏写意图——
        navigate 与纯取数走这条路零开销。"""
        if route == "query" and any(h in user_input for h in _ORCHESTRATE_HINTS):
            return PlanBundle(orchestration=OrchestrationPlan(
                condition=ThresholdCondition(column="score", op="lt", value=60),
                followup_user_input="我的补考和重修时间安排"))
        if route == "answer" and "报名" in user_input:
            for phrase, code in _REGISTER_COURSES.items():
                if phrase in user_input:
                    return PlanBundle(write=WriteIntent(
                        course_code=code, course_name=phrase,
                        summary=f"为「{phrase}」提交补考/重修报名"))
        return PlanBundle()

    async def judge(self, condition_text: str, evidence: dict) -> bool:
        """LLM 模式的 fake 兜底：行里任一数值低于 60 即 True。"""
        for row in evidence.get("rows") or []:
            if any(isinstance(v, (int, float)) and v < 60 for v in row):
                return True
        return False
```

`generate_sql` 在构造 SQL 前加分支（放在 kw 提取之前）：

```python
        if "补考" in user_input:
            return "SELECT course, kind, scheduled_at, place, status FROM v_makeup"
```

- [ ] **Step 3: 实现 `OpenAICompatProvider.plan/judge`**

```python
PLAN_SYSTEM = (
    "你是编排规划器。判断这句用户输入是否需要：a) 条件分支（先查数，满足条件再追加一个取数问题）；"
    "b) 写操作确认（补考/重修报名）。只输出 JSON："
    '{"orchestration": {"condition": {"mode": "threshold", "column": "score", "op": "lt", "value": 60}'
    ' | {"mode": "llm", "condition_text": "..."}, "followup_user_input": "..."} | null, '
    '"write": {"course_code": "...", "course_name": "...", "summary": "..."} | null}。'
    "没有把握就全 null。阈值条件只用于分数类列。"
)

JUDGE_SYSTEM = "你是条件判定器。只回答 true 或 false，不要任何其他字符。"


async def plan(self, user_input: str, route: str) -> PlanBundle:
    if route not in ("query", "answer"):
        return PlanBundle()
    if not any(h in user_input for h in ("不及格", "低于", "如果", "报名", "重修", "补考")):
        return PlanBundle()   # 触发词闸：无关消息零额外调用
    resp = await self.client.chat.completions.create(
        model=self.model,
        messages=[{"role": "system", "content": PLAN_SYSTEM},
                  {"role": "user", "content": user_input}],
        response_format={"type": "json_object"},
    )
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
        return PlanBundle(
            orchestration=OrchestrationPlan(**data["orchestration"])
            if data.get("orchestration") else None,
            write=WriteIntent(**data["write"]) if data.get("write") else None)
    except (json.JSONDecodeError, KeyError, ValueError):
        return PlanBundle()   # 计划坏了就当没有：降级为单轮，不阻断对话


async def judge(self, condition_text: str, evidence: dict) -> bool:
    resp = await self.client.chat.completions.create(
        model=self.model,
        messages=[{"role": "system", "content": JUDGE_SYSTEM},
                  {"role": "user", "content": f"条件：{condition_text}\n"
                    f"数据：{json.dumps(evidence, ensure_ascii=False)}"}],
    )
    return (resp.choices[0].message.content or "").strip().lower().startswith("true")
```

- [ ] **Step 4: 跑测试**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestration.py -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/fake.py backend/app/llm/openai_compat.py backend/tests/test_orchestration.py
git commit -m "feat(llm): provider 编排能力——fake 规则与真模型 plan/judge 双实现"
```

---

### Task 5: grader 节点 + 图重构 + 降级与循环守卫

**Files:**
- Create: `backend/app/agent/nodes/grader.py`
- Modify: `backend/app/agent/graph.py`
- Modify: `backend/app/agent/nodes/router.py`（挂 plan 到 state）
- Modify: `backend/app/agent/nodes/sql_executor.py`（phase/next_query/sql_history）
- Modify: `backend/app/llm/fake.py`（stream_answer 读 sql_history）
- Modify: `backend/app/llm/openai_compat.py`（stream_answer 同样改）
- Test: `backend/tests/test_orchestration.py`（图级用例）

**Interfaces:**
- Consumes: Task 2 的 state 字段与协议；Task 4 的 `plan()`。
- Produces:
  - `grader_node(state, provider, writer)`：三分支 `then/else/degraded`；then 且有 followup 时返回 `{"orchestration_phase": "followup", "next_query": ...}`；发 `("grader", {"branch": ...})` 自定义事件。
  - 图边：`router→{navigate:tool_executor, query:sql_executor, answer:generator, write:generator(Task 6 前暂指 generator), None:generator}`；`sql_executor→{有 orchestration 且 phase 空:grader, 否则:generator}`；`grader→{phase=="followup":sql_executor, 否则:generator}`；`tool_executor→generator` 不变。
  - 旗舰 steps 序列钉死：`[router, sql_executor, grader, sql_executor, generator]`。

- [ ] **Step 1: 写失败测试——旗舰 then 分支全链路**

`backend/tests/test_orchestration.py` 追加（fixture 复用 `test_graph.py` 的 InMemory 注册表 + FakeProvider 跑真图的既有写法）：

```python
class Test旗舰编排:
    async def test_then分支走grader再查补考(self, graph_with_fake):
        # InMemory 注册表里 run_sql 按 SQL 内容返回 v_grades / v_makeup 两类行
        final = await run_graph(graph_with_fake, "查我上学期高数成绩，不及格就告诉我补考时间")
        assert final["steps"] == ["router", "sql_executor", "grader",
                                  "sql_executor", "generator"]
        assert final["branch"] == "then"
        assert len(final["sql_history"]) == 2           # 两轮查数都在
        assert "grader" in final["steps"]
        assert "已报名" in final["answer"] or "补考" in final["answer"]

    async def test_else分支不进grader后续(self, graph_with_fake):
        # 全部及格的行 → then 不成立：steps 无第二个 sql_executor
        final = await run_graph(graph_with_fake, "查我上学期高数成绩，及格就告诉我奖学金")
        assert final["branch"] == "else"
        assert final["steps"] == ["router", "sql_executor", "grader", "generator"]

    async def test_失败降级保留已成功结果(self, graph_with_fake, monkeypatch):
        # 第二个工具（run_sql 的 v_makeup 查询）抛错：timed_call 已包成 ok=False，
        # grader 在前半段已放行 followup——降级发生在 followup executor：
        # 答案里既有第一轮的分数，又有失败说明，steps 正常收尾到 generator
        ...

    async def test_循环守卫_grader只放行一次(self, graph_with_fake):
        # plan.followup 本身又含触发词（「不及格」），若无守卫会无限循环。
        # 守卫 = orchestration_phase 标记：followup 轮不再回 grader。
        # 构造：monkeypatch FakeProvider.plan 让 followup 问句也命中编排，
        # 断言 steps 里 grader 恰好一次、序列有限长、正常收尾。
        ...
```

`graph_with_fake`/`run_graph` 的确切写法按 `test_graph.py` 既有 helper 照抄（InMemoryRegistry 里 `run_sql` 的实现按 SQL 里含 `v_grades`/`v_makeup` 分流返回行；`describe_schema` 返回四个视图的空 schema 即可）。

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestration.py -q`
Expected: 新增用例 FAIL（grader/图边不存在）。

- [ ] **Step 2: 实现 `grader.py`**

```python
import logging
import operator
import time

from langgraph.types import StreamWriter

from ...llm.base import LLMProvider

logger = logging.getLogger("campus-agent.grader")

_OPS = {"lt": operator.lt, "le": operator.le, "gt": operator.gt,
        "ge": operator.ge, "eq": operator.eq, "ne": operator.ne}


async def grader_node(state, provider: LLMProvider, writer: StreamWriter):
    """spec §4 条件分支：阈值/LLM 双模式；工具失败走 degraded，已成功结果不丢
    （它们在 sql_history / tool_results 里，generator 照常读）。"""
    start = time.perf_counter()
    plan = state["orchestration"]
    latest = state.get("sql") or {}

    branch, detail = "else", {"mode": plan.condition.mode}
    if state.get("error"):
        branch = "degraded"
        detail["reason"] = state["error"]
    elif plan.condition.mode == "threshold":
        cond = plan.condition
        columns = latest.get("columns") or []
        if cond.column in columns:
            idx = columns.index(cond.column)
            vals = [r[idx] for r in latest.get("rows") or []
                    if idx < len(r) and isinstance(r[idx], (int, float))]
            hit = bool(vals) and any(_OPS[cond.op](v, cond.value) for v in vals)
        else:
            hit = False   # 列不在结果里：判不出 → 走 else，不瞎猜 then
        branch = "then" if hit else "else"
        detail.update({"column": cond.column, "hit_rows": len(vals) if cond.column in columns else 0})
    else:  # llm
        hit = await provider.judge(plan.condition.condition_text,
                                   {"columns": latest.get("columns"),
                                    "rows": latest.get("rows")})
        branch = "then" if hit else "else"

    writer(("grader", {"branch": branch}))
    logger.info("grader branch=%s detail=%s", branch, detail)

    out = {"branch": branch, "steps": ["grader"],
           "step_details": [{"node": "grader",
                             "latency_ms": int((time.perf_counter() - start) * 1000),
                             "detail": detail}]}
    # 循环守卫：phase 标记保证 grader 全图只放行一次 followup，
    # 结构上不存在第二次回到 grader 的边（验收 5「死循环被截断」的图级防线；
    # recursion_limit=10 只是兜底，正常路径根本到不了）
    if branch == "then" and plan.followup_user_input \
            and not state.get("orchestration_phase"):
        out["orchestration_phase"] = "followup"
        out["next_query"] = plan.followup_user_input
    return out
```

- [ ] **Step 3: sql_executor 支持 phase/next_query**

`sql_executor_node` 三处改动：

1. 函数开头：`phase = state.get("orchestration_phase")`；`query_text = state.get("next_query") or _sql_input(state)`。
2. `resolve_page` 补跑包一层 `if phase != "followup":`（followup 轮不重复出导航卡）。
3. `generate_sql(_sql_input(state), ...)` 改为 `generate_sql(query_text, ...)`。
4. `_maybe_clarify` 只在 `phase != "followup"` 时调用（followup 是计划内追问，结果跨学期也不该再问——否则编排链被澄清打断，验收 1 的「同时含分数与补考提示」出不齐）。

return 里已有 `sql_history`（Task 2 加的）保持不变。

- [ ] **Step 4: router 把 plan 挂进 state**

`router_node` 里 `route = _route_of(...)` 算好后（两个 return 分支都要）调用：

```python
    bundle = await provider.plan(state["user_input"], route)
```

两个分支的返回字典都加 `"orchestration": bundle.orchestration, "write": bundle.write`。幻觉拦截分支同样挂（它 route 可能是 query，编排信息不丢）。

- [ ] **Step 5: 图重构 `graph.py`**

```python
def build_graph(provider: LLMProvider, registry: ToolRegistry,
                pending_actions=None):          # Task 6 用，本任务恒为 None
    ...
    workflow.add_node("grader", grader)
    ...
    workflow.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {"navigate": "tool_executor", "query": "sql_executor",
         "answer": "generator", "write": "confirm_preparer" if False else "generator",
         None: "generator"},                    # Task 6 把 write 指向 confirm_preparer
    )
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
    return workflow.compile().with_config(recursion_limit=10)
```

（write 分支 Task 6 前暂时指 generator——本任务不存在 write 路由，留位即可。）

- [ ] **Step 6: 两个 provider 的 stream_answer 读 sql_history**

fake.py：error/sql 分支改为先看 `sql_history`——

```python
        history = state.get("sql_history") or ([state["sql"]] if state.get("sql") else [])
        if error:
            parts = [f"这次调用没有成功（{error}）。你可以换个说法再试一次，"
                     f"或者直接前往对应栏目手动查询。"]
            for s in history:
                if "score" in (s.get("columns") or []):
                    parts.append("已查到的分数：" + _read_scores(s))
            text = "".join(parts)
        elif history:
            parts = []
            for s in history:
                cols = s.get("columns") or []
                if "score" in cols:
                    parts.append(_read_scores(s))
                elif "scheduled_at" in cols:
                    parts.append(_read_makeup(s))
            text = "；".join(parts) if parts else "没有查到符合条件的记录。"
        elif nav:
            ...  # 既有分支不动
```

`_read_scores(sql_state)`：`course`/`score` 列在行里的读数串，形如 `「高等数学（上）」91 分、「高等数学（下）」56 分`；`_read_makeup(sql_state)`：`「{course}」{kind} {scheduled_at} {place}，状态 {status}` 逗号连接。空 rows 返回空串，由调用处兜底。

openai_compat.py：`stream_answer` 里把现有 `sql` 单块 tool_note 改成循环：

```python
        history = state.get("sql_history") or ([sql] if sql else [])
        for i, s in enumerate(history):
            if s.get("columns"):
                tool_note += (f"\n查询结果#{i + 1}"
                              + json.dumps({"columns": s.get("columns"),
                                            "rows": s.get("rows") or [],
                                            "row_count": s.get("row_count")},
                                           ensure_ascii=False))
```

- [ ] **Step 7: 跑测试**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: 全 PASS（含既有 117；旗舰链路 InMemory 的 `run_sql` 分流按新测试实现）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/nodes/grader.py backend/app/agent/graph.py backend/app/agent/nodes/router.py backend/app/agent/nodes/sql_executor.py backend/app/llm/fake.py backend/app/llm/openai_compat.py backend/tests/test_orchestration.py
git commit -m "feat(agent): grader 条件分支（阈值/LLM 双模式）+ 失败降级 + 循环守卫"
```

---

### Task 6: write 路由 + confirm_preparer + 旗舰确认链路

**Files:**
- Create: `backend/app/agent/nodes/confirm_preparer.py`
- Modify: `backend/app/agent/graph.py`（write 边指向 confirm_preparer）
- Modify: `backend/app/agent/nodes/router.py`（write 路由判定）
- Modify: `backend/app/agent/nodes/generator.py`（confirm_card 话术分支）
- Modify: `backend/app/llm/fake.py`（stream_answer confirm 分支）
- Modify: `backend/app/api/chat.py`（build_graph 传 pending_actions）
- Test: `backend/tests/test_write_ops.py`（端到端：聊天 → confirm_card → POST /confirm → 状态翻转）

**Interfaces:**
- Consumes: Task 3 的 `PendingActionStore`/`register_makeup`；Task 4 的 `WriteIntent`。
- Produces:
  - `confirm_preparer_node(state, store, writer)`：创建待确认动作，发 `("confirm_card", {"action_id", "action", "title", "summary"})`，返回 `{"confirm_card": card, ...}`。
  - SSE 新事件 `confirm_card`；generator 在 `state["confirm_card"]` 非空时话术引导用户点击。
  - 验收 2 全链路：发「帮我报名大学物理（上）的补考」→ 流里出现 `confirm_card` 事件且**未**执行写（makeup 状态不变）→ POST /confirm → 状态翻转「已报名」。

- [ ] **Step 1: 写失败测试——端到端确认链路**

`backend/tests/test_write_ops.py` 追加：

```python
class Test确认链路端到端:
    async def test_写意图出确认卡且未执行(self, client):
        events = await _chat_events(client, "帮我报名大学物理（上）的补考")
        card = next((e["data"] for e in events if e["event"] == "confirm_card"), None)
        assert card is not None and card["action"] == "makeup_register"
        # 未点确认：库里状态没变
        items = client.get("/api/makeup").json()["items"]
        assert next(i for i in items if i["code"] == "PHY1031")["status"] == "已报名"  # seed 本来就是已报名
        # 换报名中的课程再验「未执行」
        ...

    async def test_点确认后执行并翻转(self, client):
        events = await _chat_events(client, "帮我报名高等数学（下）的补考")
        card = next(e["data"] for e in events if e["event"] == "confirm_card")
        r = client.post("/confirm", json={"action_id": card["action_id"]})
        assert r.status_code == 200 and r.json()["result"]["status"] == "registered"
        items = client.get("/api/makeup").json()["items"]
        assert next(i for i in items if i["code"] == "MATH2041")["status"] == "已报名"

    async def test_重复点同一卡第二次404(self, client):
        ...  # 一次性语义：pop 已焚，第二次 404，状态不叠行
```

`_chat_events(client, text)`  helper：POST /chat 读 SSE 全文解析成 `[{event, data}]`（k6 的 sse_chat.js 或既有 python 测试里若已有解析 helper 就复用；没有用 30 行内的极简解析器：按 `\n\n` 切段、`event:`/`data:` 分行 `json.loads`）。用「高等数学（下）」做报名目标（seed 报名中）；「未执行」断言选报名中的课程，确认前后 GET /api/makeup 对比。

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_write_ops.py -q`
Expected: 新用例 FAIL（confirm_card 事件不存在）。

- [ ] **Step 2: `router.py` 加 write 路由判定**

`_route_of` 改签名 `_route_of(user_input, tool_name, write) -> str`：开头加 `if write is not None: return "write"`；`router_node` 里先取 bundle 再算 route（Task 5 已调 plan，把它提前到 route 计算之前，一次调用两用）。

- [ ] **Step 3: 实现 `confirm_preparer.py`**

```python
import time

from langgraph.types import StreamWriter

from ...write_ops import PendingActionStore


async def confirm_preparer_node(state, store: PendingActionStore,
                                writer: StreamWriter):
    """写意图 → 待确认动作 + confirm_card 事件。本节点不执行任何写——
    执行只发生在 POST /confirm（spec §4「用户点确认才继续」）。"""
    start = time.perf_counter()
    intent = state["write"]
    action_id = store.create(state["student_id"], intent.action,
                             {"course_code": intent.course_code})
    card = {"action_id": action_id, "action": intent.action,
            "title": "确认报名",
            "summary": intent.summary
            or f"为「{intent.course_name or intent.course_code}」提交补考/重修报名"}
    writer(("confirm_card", card))
    return {"confirm_card": card, "steps": ["confirm_preparer"],
            "step_details": [{"node": "confirm_preparer",
                              "latency_ms": int((time.perf_counter() - start) * 1000),
                              "detail": {"action": intent.action,
                                         "course_code": intent.course_code}}]}
```

- [ ] **Step 4: graph 接线 + chat.py 传 store**

`graph.py`：`workflow.add_node("confirm_preparer", confirm_preparer)`；write 边改成 `"write": "confirm_preparer"`（Task 5 的占位 `if False else` 表达式删掉）；`build_graph` 的 `pending_actions=None` 默认参数保留，节点闭包里 `store = pending_actions`，若 None 用模块级 `PendingActionStore()` 兜底（图测试不传 store 也能跑）。`add_edge("confirm_preparer", "generator")`。

`chat.py`：`graph = build_graph(provider, registry, req.app.state.pending_actions)`。

- [ ] **Step 5: generator 与 fake 话术**

`generator.py`：`stream_state = {**state, "nav_card": nav_card}` 已带 confirm_card（state 全量透传）——确认分支只影响 answer 文案，事件已由 confirm_preparer 发出，generator 无需再发。无代码改动，**但要确认 clarify 分支不受 confirm_card 干扰**（write 路由不会带 clarification，天然隔离，测试钉住即可）。

`fake.py` `stream_answer`：error 分支之后、sql 分支之前加：

```python
        elif state.get("confirm_card"):
            c = state["confirm_card"]
            text = (f"{c['summary']}。请点击下方确认卡片上的「确认报名」按钮完成操作，"
                    f"不点击则不会提交。")
```

- [ ] **Step 6: 跑测试**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: 全 PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/nodes/confirm_preparer.py backend/app/agent/graph.py backend/app/agent/nodes/router.py backend/app/agent/nodes/generator.py backend/app/llm/fake.py backend/app/api/chat.py backend/tests/test_write_ops.py
git commit -m "feat(agent): write 路由与 confirm_preparer——写操作先确认后执行"
```

---

### Task 7: POST /replay 执行回放

**Files:**
- Create: `backend/app/api/replay.py`
- Modify: `backend/app/db/repository.py`（`latest_trace`）
- Modify: `backend/app/main.py`（挂 router）
- Test: `backend/tests/test_write_ops.py`（或新建 `test_replay.py`，跟写文件的人定，单文件别超 400 行）

**Interfaces:**
- Consumes: Task 2 落库的 `step_details_json`。
- Produces:
  - `ConversationRepository.latest_trace(*, student_id) -> dict | None`：`{"steps": list[str], "step_details": list[dict], "tool_name": str, "args": dict, "ok": bool, "latency_ms": int, "created_at": str}`
  - `POST /replay`（require_student）→ 200 上述 dict；404 无记录。

- [ ] **Step 1: 写失败测试**

```python
class Test回放:
    async def test_回放与刚跑的对话一致(self, client):
        events = await _chat_events(client, "我这学期平均分多少")
        done = next(json.loads(e["data"]) for e in events if e["event"] == "done")
        r = client.post("/replay")
        assert r.status_code == 200
        body = r.json()
        assert body["steps"] == done["steps"]            # 与 steps_json 一致（验收 3）
        assert [s["node"] for s in body["step_details"]] == done["steps"]
        assert all(isinstance(s["latency_ms"], int) for s in body["step_details"])

    async def test_无记录返回404(self, client):
        ...  # 全新库（fixture 里还没跑过对话的学生）
```

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_write_ops.py -q`
Expected: FAIL（端点 404/405）。

- [ ] **Step 2: `repository.py` 加 `latest_trace`**

Protocol 与实现都加：

```python
    async def latest_trace(self, *, student_id: str) -> dict | None: ...

    async def latest_trace(self, *, student_id: str) -> dict | None:
        rows = await self._db.fetch_all(
            "SELECT t.tool_name, t.args_json, t.ok, t.latency_ms,"
            " t.steps_json, t.step_details_json, t.created_at"
            " FROM tool_calls t JOIN conversations c ON c.id = t.conversation_id"
            " WHERE c.student_id = ? ORDER BY t.id DESC LIMIT 1", (student_id,))
        if not rows:
            return None
        r = rows[0]
        return {"steps": json.loads(r["steps_json"]),
                "step_details": json.loads(r["step_details_json"] or "[]"),
                "tool_name": r["tool_name"],
                "args": json.loads(r["args_json"]),
                "ok": bool(r["ok"]),
                "latency_ms": int(r["latency_ms"]),
                "created_at": str(r["created_at"])}
```

- [ ] **Step 3: `api/replay.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.deps import require_student
from ..auth.students import Student

router = APIRouter()


@router.post("/replay")
async def replay(req: Request, student: Student = Depends(require_student)):
    """回放展示（裁决 2：不重执行节点——写操作双写与 /confirm 一次性语义冲突）。
    返回最近一次执行的节点序列、每步参数/耗时，与 tool_calls.steps_json 同源。"""
    trace = await req.app.state.repository.latest_trace(student_id=student.student_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="还没有可回放的执行记录")
    return trace
```

`main.py` 挂 router。

- [ ] **Step 4: 跑测试**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/replay.py backend/app/db/repository.py backend/app/main.py backend/tests/
git commit -m "feat(replay): POST /replay 回放最近一次执行的节点序列与每步参数耗时"
```

---

### Task 8: 前端——确认卡、useChatStream 扩展、回放面板

**Files:**
- Create: `frontend/src/components/chat/ConfirmCard.vue`
- Modify: `frontend/src/types.ts`、`frontend/src/composables/useChatStream.ts`
- Modify: `frontend/src/components/chat/MessageBubble.vue`、`frontend/src/components/chat/MessageList.vue`、`frontend/src/components/chat/ChatBox.vue`
- Test: `frontend/tests/confirmCard.test.ts` + 更新 `frontend/tests/useChatStream.test.ts`

**Interfaces:**
- Consumes: SSE `confirm_card` 事件（Task 6）；`POST /confirm`（Task 3）；`POST /replay`（Task 7）。
- Produces:
  - `ConfirmCardEvent { action_id: string; action: string; title: string; summary: string }`（types.ts）
  - `ChatMessage` 加 `confirmCard: ConfirmCardEvent | null`、`confirmResult: { ok: boolean; text: string } | null`
  - `ConfirmCard.vue` props `{ card: ConfirmCardEvent }`，内联确认按钮 → `POST /confirm` → 成功显示 result，失败/401 显示错误文案。
  - ChatBox 顶部「回放上次执行」按钮 → `POST /replay` → `<details>` 面板列 steps + 每步 latency_ms。

- [ ] **Step 1: 写失败测试**

`frontend/tests/confirmCard.test.ts`：

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import ConfirmCard from '../src/components/chat/ConfirmCard.vue'

describe('ConfirmCard', () => {
  beforeEach(() => vi.resetAllMocks())

  it('点击确认后 POST /confirm 并展示结果', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200,
      json: async () => ({ ok: true, result: { status: 'registered', course: '高等数学（下）' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ConfirmCard, { props: { card: {
      action_id: 'abc', action: 'makeup_register', title: '确认报名',
      summary: '为「高等数学（下）」提交补考/重修报名' } } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/confirm', expect.objectContaining({ method: 'POST' }))
    expect(wrapper.text()).toContain('报名成功')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()  // 一次性：确认后禁点
  })

  it('失败时展示错误文案', async () => {
    ...  // 404 → 「确认请求不存在或已过期，请重新发起」
  })
})
```

`useChatStream.test.ts` 追加：feed 含 `confirm_card` 帧 → assistant message 的 `confirmCard` 字段被赋值。`flushPromises` 从 `@vue/test-utils` 导入（既有测试的引法照抄）。

Run: `cd frontend && npx vitest run tests/confirmCard.test.ts`
Expected: FAIL（组件不存在）。

- [ ] **Step 2: types.ts + useChatStream**

types.ts 加 `ConfirmCardEvent`（形状见 Interfaces）；`DoneEvent` 不动。

useChatStream：`ChatMessage` 加两个字段（`send()` 里两处 push 的对象都补 `confirmCard: null, confirmResult: null`）；帧处理加：

```ts
          } else if (frame.event === 'confirm_card') {
            assistant.confirmCard = JSON.parse(frame.data) as ConfirmCardEvent
          }
```

- [ ] **Step 3: ConfirmCard.vue**

```vue
<script setup lang="ts">
import { ref } from 'vue'
import type { ConfirmCardEvent } from '../../types'

const props = defineProps<{ card: ConfirmCardEvent }>()
const state = ref<'idle' | 'loading' | 'done' | 'error'>('idle')
const resultText = ref('')

async function confirm() {
  if (state.value !== 'idle') return
  state.value = 'loading'
  try {
    const resp = await fetch('/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ action_id: props.card.action_id }),
    })
    if (resp.status === 401) {
      resultText.value = '登录已过期，请重新登录'
    } else if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      resultText.value = body?.detail ?? '确认失败，请重新发起对话'
    } else {
      const body = await resp.json()
      const r = body.result
      resultText.value = r.status === 'already' ? '这门课之前已报名，无需重复提交'
        : `报名成功：${r.course}（${r.kind}）`
    }
    state.value = resp?.ok ? 'done' : 'error'
  } catch {
    resultText.value = '网络异常，请稍后重试'
    state.value = 'error'
  }
}
</script>

<template>
  <div class="confirm-card" data-testid="confirm-card">
    <p class="confirm-card__summary">{{ card.summary }}</p>
    <button type="button" :disabled="state !== 'idle'" @click="confirm">
      {{ state === 'loading' ? '确认中…' : '确认报名' }}
    </button>
    <p v-if="resultText" class="confirm-card__result" data-testid="confirm-result">{{ resultText }}</p>
  </div>
</template>

<style scoped>
/* 视觉细节跟 NavigationCard.vue 的卡片语言走：读它再写，别发明第二套 */
</style>
```

- [ ] **Step 4: MessageBubble / MessageList 挂确认卡**

`MessageBubble.vue`：`import ConfirmCard from './ConfirmCard.vue'`；模板里在 navCard/clarify 同层加：

```vue
    <ConfirmCard v-if="message.confirmCard && !message.confirmResult" :card="message.confirmCard" />
```

（`confirmResult` 字段本任务暂不写值——组件内联展示结果，state 保持简单；字段留给 Task 10 手测时若需要再启用，不实现就是 YAGNI，别画蛇添足加进 ChatMessage。）

`useChatStream.ts` 的 `ChatMessage` **不加** `confirmResult`，只加 `confirmCard: ConfirmCardEvent | null`（Step 2 那行写成两个字段的以本步为准：只加一个）。

- [ ] **Step 5: ChatBox 回放面板**

`ChatBox.vue`（读现有结构后加，约 30 行）：头部工具区加按钮「回放上次执行」+ 本地 state：

```ts
const replayOpen = ref(false)
const replayTrace = ref<{ steps: string[]; step_details: { node: string; latency_ms: number }[] } | null>(null)

async function replay() {
  const resp = await fetch('/replay', { method: 'POST', credentials: 'include' })
  if (resp.status === 404) { replayTrace.value = { steps: [], step_details: [] } } // 面板显示「还没有可回放的记录」
  else if (resp.ok) { replayTrace.value = await resp.json() }
  replayOpen.value = true
}
```

模板：`<details v-if="replayOpen">` 里表格两列——节点名、耗时 ms——行序即 `replayTrace.step_details`；空数组时一句提示文案。样式跟 ChatBox 既有面板走。

- [ ] **Step 6: 跑前端测试与类型检查**

Run: `cd frontend && npx vitest run && npx vue-tsc --noEmit`
Expected: 全 PASS（22 既有 + 新增；既有快照/结构断言若因 ChatMessage 新字段报错，按新形状更新）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types.ts frontend/src/composables/useChatStream.ts frontend/src/components/chat/ frontend/tests/
git commit -m "feat(front): 确认卡组件、confirm_card 事件接线与执行回放面板"
```

---

### Task 9: k6 扩展——/confirm、/replay 鉴权与旗舰编排序列

**Files:**
- Modify: `k6/tests/authz.js`
- Modify: `k6/tests/sse_chat.js`
- Test: `bash scripts/run_k6.sh`（全量四门）

**Interfaces:**
- Consumes: Task 3 的 `/confirm`、Task 7 的 `/replay`、Task 5 的旗舰编排 steps。
- Produces: authz.js 新增两组断言；sse_chat.js 新增旗舰用例断言 `steps` 含 `grader`。

- [ ] **Step 1: authz.js 加 /confirm 与 /replay**

在既有「无 Cookie → 401」分组照抄风格加：

```js
  group('confirm 无 Cookie', () => {
    const r = http.post(`${BASE_URL}/confirm`, JSON.stringify({ action_id: 'x'.repeat(32) }), { headers: JSON_HEADERS })
    check(r, { 'confirm 401': (r) => r.status === 401 })
  })
  group('replay 无 Cookie', () => {
    const r = http.post(`${BASE_URL}/replay`, null, { headers: JSON_HEADERS })
    check(r, { 'replay 401': (r) => r.status === 401 })
  })
```

再在「登录后」分组加（cookie jar 用既有惰性 `ensureJar()` 模式）：

```js
  group('confirm 不存在动作', () => {
    loginOnce()                       // 既有 helper：每 VU 只登录一次
    const r = http.post(`${BASE_URL}/confirm`, JSON.stringify({ action_id: '0'.repeat(32) }), { headers: authHeaders() })
    check(r, { 'confirm 404': (r) => r.status === 404 })
  })
```

helper 名字以 `k6/lib/helpers.js` 既有为准，别新造。

- [ ] **Step 2: sse_chat.js 加旗舰编排用例**

新 default 函数内一个 `group`（fake provider 下全程本地、无 LLM 调用）：

```js
  group('旗舰编排：不及格→补考', () => {
    loginOnce()
    const steps = chatAndCollectSteps('查我上学期高数成绩，不及格就告诉我补考时间')
    check(steps, {
      '含 grader': (s) => s.includes('grader'),
      '两轮 sql_executor': (s) => s.filter((x) => x === 'sql_executor').length === 2,
    })
  })
```

`chatAndCollectSteps`：若文件里已有 SSE 收集 helper 就复用（读现有 `sse_chat.js` 按它的 parser 写法）；没有就抽一个 20 行内的：POST /chat → 读 body → 按行扫 `event: done` 后 `data:` 的 `steps` 数组 `JSON.parse`。

- [ ] **Step 3: 全量跑 k6**

Run: `bash scripts/run_k6.sh`
Expected: 四门全过（脚本自身会起 fake+sqlite 后端在 8300 端口；本地 8000/5173 若占着不影响）。

- [ ] **Step 4: Commit**

```bash
git add k6/tests/authz.js k6/tests/sse_chat.js
git commit -m "test(k6): /confirm /replay 鉴权断言与旗舰编排 SSE 序列"
```

---

### Task 10: 全量回归 + 验收五条逐条核对 + 文档回填

**Files:**
- Modify: 本计划文件（勾选回填）
- Test: 全部既有测试 + k6 + 手测

- [ ] **Step 1: 后端全量**

Run: `cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: 全 PASS（117 既有 + S4 新增）。

- [ ] **Step 2: 前端全量 + 类型**

Run: `cd frontend && npx vitest run && npx vue-tsc --noEmit`
Expected: 全 PASS。

- [ ] **Step 3: 契约脚本**

Run: `cd backend && ./.venv/Scripts/python.exe ../scripts/check_routes_contract.py`
Expected: OK。

- [ ] **Step 4: k6 全量**

Run: `bash scripts/run_k6.sh`
Expected: 全过。

- [ ] **Step 5: 验收五条逐条核对（每条给出证据位置）**

1. **旗舰编排**：问「查我上学期高数成绩，不及格就告诉我补考时间」→ 答案同时含分数与补考提示 + 跳转卡片；steps 含 grader。证据：`test_orchestration.py::Test旗舰编排`（图级）+ `sse_chat.js` 旗舰 group（HTTP 级）+ 手测（起真前后端，浏览器看卡片与补考文本同在）。
2. **写操作未确认不执行 / 无 Cookie 401**：`test_write_ops.py::Test确认链路端到端` + `authz.js` confirm 401/404 两组。
3. **replay 一致**：`test_write_ops.py::Test回放`（`body["steps"] == done["steps"]`，与 `steps_json` 同源自证）。
4. **降级**：`test_orchestration.py::test_失败降级保留已成功结果`——第二个工具 ok=False，答案含第一轮分数 + 失败说明，steps 收尾 generator。
5. **死循环截断**：`test_orchestration.py::test_循环守卫_grader只放行一次`——构造 followup 自触发编排的输入，断言 grader 恰好一次、序列有限、正常收尾；`recursion_limit=10` 为兜底。

- [ ] **Step 6: 手测三项（起真服务，fake 与真模型各一遍旗舰问句）**

```bash
# 终端 1（main 仓库根）
cd backend && DB_BACKEND=sqlite ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# 终端 2
cd frontend && npm run dev
```

- 浏览器登录 20230001/demo1234 → 聊「查我上学期高数成绩，不及格就告诉我补考时间」→ 截图：分数文本 + 补考时间 + 跳转卡片同框。
- 聊「帮我报名高等数学（下）的补考」→ 确认卡出现 → **不点**，刷新补考页确认状态仍「报名中」→ 回聊窗点「确认报名」→ 卡片显示报名成功 → 补考页状态变「已报名」→ 截图。
- 点 ChatBox「回放上次执行」→ 面板列出五步序列与每步耗时 → 截图。
- 真模型（`LLM_PROVIDER=openai_compat`，Key 在 backend/.env）：同一旗舰问句再跑一遍，答案措辞不同但语义一致（含分数与补考信息）；截图存证。

- [ ] **Step 7: 回填计划勾选与执行记录**

把本文所有 `- [ ]` 勾成 `- [x]`；在本文件末尾追加「## 执行记录」：逐任务的提交哈希、测试计数、评审结论与裁决引用（含本计划 Header 的五条裁决是否在执行中被修订）。

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/plans/2026-09-26-campus-s4-orchestration-confirm-replay.md
git commit -m "docs(plan): S4 计划回填勾选与执行记录"
```

---

## Self-Review 记录

1. **Spec 覆盖**（roadmap §4 范围逐条 → 任务）：grader+双模式→Task 4/5；tool_results 累加→Task 2（`_merge_results`）；失败降级→Task 5（grader degraded + `timed_call` 既有语义）；recursion_limit 截断→Task 5（守卫）+graph.py 10；POST /confirm→Task 3/6；POST /replay→Task 7；写操作 API→Task 3（补考报名）；明确不做（Page Agent/rewriter/多会话）→无任务，正确。
2. **验收五条 → 任务**：见 Task 10 Step 5 的逐条映射，每条至少一个自动化证据 + 手测兜底。
3. **占位符扫描**：任务内代码块均为完整实现或完整测试骨架；`...` 只出现在「按既有 fixture/helper 照抄」处（此类必须在执行时先读被引用的文件再写，不许留空函数体）。
4. **类型一致性**：`PlanBundle/OrchestrationPlan/WriteIntent/ThresholdCondition/LlmCondition` 定义于 Task 2 Step 1，Task 4/5/6 引用同名；`PendingActionStore.create/pop` 定义 Task 3，Task 6 confirm_preparer 与 chat.py 使用同名同签名；`record_exchange(step_details=...)` Task 2 定，chat.py Task 2 Step 7 用；`latest_trace` Task 7 定，replay.py 用。`grader` SSE 事件 Task 5 发，前端不消费（信息已进 step_details 回放面板）——一致，无孤儿事件。
5. **已知风险**：seed 变更可能钉住旧断言（Task 1 Step 5 专门处理）；`followup` 轮跨学期结果不再澄清（Task 5 Step 3，裁决记录：编排内追问打断链路比歧义代价大）；真模型 `plan()` 多一次调用仅触发词命中时发生（Task 4）。
