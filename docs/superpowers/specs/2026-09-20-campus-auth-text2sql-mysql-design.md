# 校园 Agent — 身份会话、MySQL 数据层与自然语言查数 设计文档

**日期**：2026-09-20
**状态**：待用户评审
**范围**：在 `2026-09-18-campus-agent-mvp-design.md`（下称 MVP spec）已交付的链路上，新增三件事并合并为一份 spec：登录与会话、教务数据落库（MySQL + Docker）、助手由"只给跳转卡片"升级为"自己判断该跳转还是该查数"。
**前置**：MVP spec 的 M1–M6 已合入 `main`（`ae005d9`），前端视觉系统已合入（`ce31b2f`）。

---

## 0. 本文与既有文档的关系

MVP spec 第 6.1 节立了一条规矩并留了空位：`student_id` 只能从会话取，绝不从请求体接受；当时用 `config.fake_student_id = "20230001"` 占位，且**全仓无人读取**。第 10 节把"MySQL / Redis"列为后续接入点，第 6.2 节写明"Docker 全程不参与本切片，阶段四再走 wsl docker compose"。

本文就是那个"阶段四"，但它同时补一件 MVP spec 没做的事：**把身份接缝从占位变成实现**。因为一旦助手要回答"我的高等数学成绩"，"我的"三个字必须有可信来源，否则查数能力越强，越权面越大。

对 `方案.md` 的关系：`方案.md` 设想的 5 个 MCP Server 中，本文只落 `academic` 一个，且把它的形态从"预定义查询工具"改成了"受约束的自然语言转 SQL"（理由见第 3 节）。

---

## 1. 已确认的前提决策

| 议题 | 决策 | 说明 |
|---|---|---|
| 登录的目的 | **把身份接缝做真**，不做真账号体系 | seed 固定账号，无注册、无找回密码 |
| 保护范围 | **全站挡门** | 未登录访问任何教务页与 `/chat` 一律拒绝 |
| 会话载体 | **HttpOnly Cookie** | 客户端 JS 读不到、改不了 |
| 顶栏身份 | **读 `/auth/me` 真值** | 不再用前端常量 |
| 查数方式 | ~~参数化工具~~ → **受约束 Text-to-SQL** | 用户在评审阶段改口，见第 2 节 |
| 上下文来源 | **服务端回读会话历史** | 前端只发当前这句 |
| 工具实现位置 | **新建 `mcp_servers/academic`（stdio）** | 与 navigation 同构 |
| 数据库 | **MySQL 8.4，Docker 起**；SQLite 作降级 | 见第 5、6 节 |

### 1.1 一处被推翻的决策，以及它带来的新风险

评审过程中用户先选了"参数化工具"，随后改口"AI 可以把自然语言翻译成 SQL 返回数据"。本文按后者设计，但必须写明代价：参数化工具的安全性来自"模型只能选工具、只能填几个字段"；Text-to-SQL 把表结构、连接方式、过滤条件全部交给模型输出，**越权与注入的责任从工具签名转移到了 SQL 校验层**。因此第 4 节是本文的核心风险段，不是附录。

---

## 2. 设计原则（本文特有）

1. **身份只有一个来源**：HTTP 会话。任何请求体、查询串、工具参数里出现的 `student_id` 都是不可信输入，一律丢弃后由服务端重写。
2. **模型永远看不到"别人的行"**：不是靠提示词嘱咐它加 `WHERE student_id=...`，而是靠"它引用的每个关系都已经被替换成只含自己行的子查询"。模型不需要守规矩，它没有不守规矩的能力。
3. **能看见机器在做什么**：改写后真正执行的 SQL 回传前端展示。这既是演示价值，也是唯一能让人发现"查错了"的证据。
4. **降级不留死角**：无 Docker 时 SQLite 能跑通全链路，但 MySQL 独有的行为（大小写、`ONLY_FULL_GROUP_BY`、字符集）不得成为功能正确性的前提。

---

## 3. 架构总览

```
浏览器 (:5173)
  ├─ 未登录 → LoginView（学号 + 密码）
  ├─ Cookie: sid (HttpOnly, SameSite=Lax)
  ├─ 路由守卫：bootstrap GET /auth/me，失败跳登录
  └─ 教务四页 / 聊天面板  ── fetch(credentials:'include') ──┐
                                                            │
FastAPI (:8000)                                             │
  ├─ /auth/login  /auth/logout  /auth/me                    │
  ├─ require_student 依赖 ──► request.state.student          │
  ├─ /api/grades /api/schedule /api/makeup /api/loans        │
  ├─ /chat  (SSE)                                            │
  │    ├─ 1. 会话回读 history（最近 6 轮）                     │
  │    ├─ 2. LangGraph: START → router ──(navigate)→ nav_executor ─┐                                       │
  │    │                                ├─(query)───→ sql_executor ─┤→ generator → END                      │
  │    │                                └─(answer)──────────────────┘                                       │
  │    │        └─ 任一 executor 可置 needs_clarification → generator 只输出问句 + 选项                       │
  │    └─ 3. 落库 conversations/messages/tool_calls/sql_queries                                             │
  ├─ SessionStore（进程内 dict + TTL）                        │
  └─ Database 协议 ──► MySQL(aiomysql) | SQLite(aiosqlite)    │
                                                            │
stdio 子进程                                                │
  ├─ mcp_servers/navigation  （已有：list_pages / resolve_page）
  └─ mcp_servers/academic    （新增：run_sql / describe_schema）
```

前后端契约仍是 MVP spec 5.5 的 SSE 事件表，本文新增两个事件（第 7 节）。

---

## 4. 自然语言查数的安全模型

### 4.1 语义层：模型能引用什么

模型只看得到四张**语义关系**，由迁移脚本创建为视图，字段刻意收窄、命名口语化：

```sql
CREATE VIEW v_grades (student_id, course, term, credits, score, points, teacher) AS
  SELECT student_id, course_name, term, credits, score, grade_points, teacher
  FROM enrollments;

CREATE VIEW v_schedule (student_id, course, weekday, start_period, end_period, room, teacher, weeks) AS
  SELECT student_id, course_name, weekday, start_period, end_period, room, teacher,
         CONCAT(weeks_from, '-', weeks_to)
  FROM course_sections;

CREATE VIEW v_makeup (student_id, course, kind, reason, scheduled_at, place, status, seats_left) AS
  SELECT student_id, course_name, kind, reason, scheduled_at, place, status, seats_left
  FROM makeup_items;

CREATE VIEW v_loans (student_id, title, call_no, due_at, days_left, shelf) AS
  SELECT student_id, title, call_no, due_at, DATEDIFF(due_at, CURDATE()), shelf
  FROM library_loans;
```

`student_id` 是视图的**第一列但不出现在给模型的 schema 提示里**：改写器需要它做过滤，模型不需要知道它存在。提示词只声明其余列名与中文含义，因此模型既不会被要求"记得加学号条件"，也就无从绕过（第 4.3 条第 4 款会把胆敢写出 `student_id` 的 SQL 直接拒掉）。

### 4.2 强制隔离：关系替换而非追加条件

后端拿到模型 SQL 后，用 `sqlglot` 解析并改写：**把每一个对白名单关系的引用，替换成一个已按当前学号过滤的内联子查询**。

```sql
-- 模型输出
SELECT course, score FROM v_grades WHERE course LIKE '%高等数学%' ORDER BY term;

-- 改写后实际执行（? 是绑定参数，绝不字符串拼接；见 6.4 方言归一）
SELECT course, score
FROM (SELECT * FROM v_grades WHERE student_id = ?) AS v_grades
WHERE course LIKE '%高等数学%'
ORDER BY term
LIMIT 50;
```

选"替换关系"而不是"在最外层加 WHERE"，是因为后者对 `UNION`、子查询、CTE、`JOIN 另一张表` 全都无效——只要模型写出一条复合语句，追加在最外层的条件就漏了。替换发生在每个引用点上，结构再复杂也绕不过去。

执行顺序固定为**先校验（4.3）再改写（4.2）**：校验针对模型原文，任何身份列、越界关系、多语句在改写前就被拒；改写只负责把通过校验的白名单关系换成带过滤的子查询。顺序颠倒会让"改写后再校验"误伤自己注入的 `student_id`，从而诱导出"把注入条件也去掉"的错误修法。

实现约束：凡 `FROM`/`JOIN` 出现白名单之外的关系名 → 直接拒绝，不做"尽力而为"。

### 4.3 校验清单（任一不过即拒绝执行）

| # | 规则 | 拒绝理由文案 |
|---|---|---|
| 1 | 单条语句 | 一次只允许一条查询 |
| 2 | 语句类型必须是 `SELECT` | 只能查询，不能修改数据 |
| 3 | 引用关系全在白名单内 | 该数据不在可查询范围 |
| 4 | 不得出现 `student_id` 等身份列 | 无需指定身份，系统已按你的账号过滤 |
| 5 | 无用户变量与系统变量（`@x`、`CONNECTION()`、`DATABASE()` 等） | 不支持变量 |
| 6 | 无 `INTO OUTFILE/DUMPFILE`、`LOAD_FILE`、`FOR UPDATE`、`LOCK IN SHARE MODE` | 不支持 |
| 7 | 无 `SLEEP`/`BENCHMARK`/`GET_LOCK` | 不支持 |
| 8 | 无 `information_schema` / `mysql` / `performance_schema` | 该数据不在可查询范围 |
| 9 | 无 LIMIT 则强制 `LIMIT 50`，有则取 `min(n, 200)` | — |
| 10 | 解析失败即拒绝，不降级执行原文 | 查询语句无法解析 |

拒绝时**不执行任何 SQL**，把拒绝原因回给 generator 转成人话，并把原始模型输出与拒绝码写进 `sql_queries` 表供复盘。

### 4.4 数据库侧纵深（假设第 4.2、4.3 全被绕过）

- 连接账号 `agent_ro`：`GRANT SELECT ON campus.v_grades, campus.v_schedule, campus.v_makeup, campus.v_loans TO 'agent_ro'@'%'`，无 `FILE`、无 `SUPER`、对基表**无直接权限**（只能读视图）。
- 语句级超时：连接建立后 `SET SESSION MAX_EXECUTION_TIME = 5000`（毫秒，仅对只读 SELECT 生效），并设 `SET SESSION TRANSACTION READ ONLY`。
- 连接池 `pool_recycle=600`，每查询独占一个 cursor，不复用会话状态。
- **纵深含义**：即便改写层被绕过，`agent_ro` 也读不到基表、读不到别的库、写不了数据、拿不到文件。

### 4.5 未验证项（必须先做 spike，不许直接实现）

MySQL 是否允许在视图定义中调用 `CONNECTION_ID()`，从而做"视图自带会话过滤"（可省掉 SQL 改写层）。本文**不采用**该方案，因为它依赖未确认的 MySQL 限制，且连接池复用会让"连接级身份"与"请求级身份"错配。写在此处是为了说明取舍理由，实现者不要顺手采用。

---

## 5. 数据模型

### 5.1 表（MySQL 方言为准，SQLite 方言等价）

```
students        (student_id PK, name, password_hash, major, class_name, college, enrolled_year)
courses         (course_code PK, course_name, credits, teacher, college)
enrollments     (id PK, student_id FK, course_code FK, course_name, term, credits,
                 score, grade_points, teacher,
                 UNIQUE(student_id, course_code, term))
course_sections (id PK, student_id FK, course_code FK, course_name, weekday,
                 start_period, end_period, room, teacher, weeks_from, weeks_to, term)
makeup_items    (id PK, student_id FK, course_name, kind, reason, scheduled_at,
                 place, status, seats_left, term)
library_loans   (id PK, student_id FK, title, call_no, due_at, shelf, returned_at NULL)
conversations   (id PK, student_id FK, session_id, created_at)          ← 已有，新增 student_id
messages        (id PK, conversation_id FK, role, content, created_at)   ← 已有
tool_calls      (id PK, conversation_id FK, tool_name, args_json, ok,
                 error, latency_ms, steps_json, created_at)              ← 已有
sql_queries     (id PK, conversation_id FK, student_id FK, sql_raw,
                 sql_scoped, refused_code, row_count, latency_ms, created_at)  ← 新增
```

要点：
- `conversations` 加 `student_id` 并建索引；历史回读按 `student_id + 最近活跃` 定位，不看客户端传的任何 id。
- `due_at`/`scheduled_at` 用 `DATETIME`，`days_left` 由查询时计算（视图里 `DATEDIFF(due_at, CURDATE())`），不存冗余天数——MVP 阶段前端 `seed.ts` 用"相对今天推导"的技巧，落库后必须换成真日期，否则数据会随时间失真。
- 密码哈希格式 `pbkdf2_sha256$600000$<salt_b64>$<hash_b64>`，`hashlib.pbkdf2_hmac` + 16 字节随机 salt，无新依赖。比较用 `hmac.compare_digest`。

### 5.2 seed 数据

`scripts/seed_academic.py` 幂等灌库，三个账号：

| 学号 | 姓名 | 密码 | 数据特征 |
|---|---|---|---|
| 20230001 | 周晓楠 | `demo1234` | 现前端 seed 全量（含 1 门不及格、1 本逾期） |
| 20230002 | 陈默 | `demo1234` | 课程完全不同（建筑学），无挂科 |
| 20230007 | 林知远 | `demo1234` | 与周晓楠**有同名课程但分数不同**（越权用例的靶子） |

密码明文写进 seed 脚本是刻意的：这是本地仿真环境，且 spec 明确不做注册。生产化时必须换掉，写进第 11 节"明确不做"旁边的告警。

---

## 6. 数据库接入与 Docker

### 6.1 环境现实（2026-09-20 实测）

- Windows 侧 Docker CLI `29.8.1` 可用，`docker context` 当前激活 `wsl → tcp://127.0.0.1:2375`。
- **该端口当前无人监听**：WSL 内 dockerd 或端口转发未启动。
- 仓库里已有未跟踪脚本 `scripts/wsl-docker-tcp/{install.sh,setup-windows.ps1,verify.ps1,uninstall.sh}`（**非本文产物，不改动**），其作用正是在 WSL 内起 dockerd 并把 2375 转发到 Windows。

因此 S2 的第一步不是写代码，是把引擎跑起来并留下可验证判据：

```bash
# 1) WSL 内（一次性）
cd /mnt/c/Users/houyunlong/Desktop/campusProject && sudo bash scripts/wsl-docker-tcp/install.sh
# 2) Windows 侧确认
docker info --format '{{.ServerVersion}}'   # 期望非空
```

若第 2 步仍连不上，S2 停止并报告环境阻塞，**不许**擅自改成"直接用 SQLite 交付"来绕过——那是降级路径，不是绕过阻塞的借口。

### 6.2 Compose

新增 `deploy/docker-compose.yml`：

```yaml
services:
  mysql:
    image: mysql:8.4
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --default-time-zone=+08:00
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: campus
      MYSQL_USER: agent_ro
      MYSQL_PASSWORD: ${AGENT_RO_PASSWORD}
    ports: ["3306:3306"]
    volumes: [campus-mysql:/var/lib/mysql]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 5s
      timeout: 5s
      retries: 20
volumes:
  campus-mysql: {}
```

- 密码只进 `deploy/.env`（gitignored），`deploy/.env.example` 进仓库。
- `agent_ro` 的 `SELECT` 授权与视图创建放在迁移脚本里，不放 compose（compose 里塞一次性 SQL 初始化文件会在数据卷已存在时静默不执行，是个坑）。
- 2375 是明文 TCP，仅绑回环；文档写明**不要**把它转发到局域网。

### 6.3 迁移

不引入 ORM 与 Alembic（项目全是裸 SQL，加 ORM 是第二次大转向）。自建极简迁移器：

- `backend/app/db/migrations/mysql/0001_init.sql`、`0002_semantic_views.sql` …；`migrations/sqlite/` 同名文件。
- 表 `schema_version(version PK, applied_at)`，启动时按序执行未应用的文件，单个文件一个事务。
- 迁移器在 `lifespan` 里跑，**仅当 `DB_BACKEND=mysql`**；SQLite 模式同样跑（用 sqlite 方言目录），保证两条路径的 schema 演进不脱节。
- 校验：CI/本地一条命令断言两个方言目录**文件名集合相同**，防止只改一边。

### 6.4 双驱动抽象

```python
# backend/app/db/base.py
class Database(Protocol):
    dialect: Literal["mysql", "sqlite"]
    async def fetch_all(self, sql: str, args: Sequence[Any] = ()) -> list[dict]: ...
    async def execute(self, sql: str, args: Sequence[Any] = ()) -> int: ...
    async def execute_script(self, sql: str) -> None: ...
```

差异集中在三处，别处不许出现方言判断：
1. 参数占位符：MySQL `%s`（aiomysql）vs SQLite `?`（aiosqlite）——由 `Database` 实现在发送前统一转换，调用方一律写 `?`。
2. DDL 方言：分文件，不在代码里拼。
3. `AUTOINCREMENT` vs `AUTO_INCREMENT`、`DATETIME` 默认值写法：同上。

`DB_BACKEND` 默认 `mysql`；`sqlite` 用于无 Docker 的机器与自动化测试（测试全跑 SQLite，MySQL 方言差异由迁移文件集合校验 + 一次真库冒烟覆盖）。

---

## 7. 认证、会话与 `/chat` 契约变更

### 7.1 端点

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/auth/login` | `{student_id, password}` | 200 `{student_id,name,major,class_name,college}` + `Set-Cookie: sid=…`；失败 401 `{code:"bad_credentials", message:"学号或密码不正确"}` |
| POST | `/auth/logout` | — | 204，`Set-Cookie: sid=; Max-Age=0` |
| GET | `/auth/me` | — | 200 同上 / 401 `{code:"unauthenticated"}` |

- 登录失败不区分"账号不存在"与"密码错"，两者同一句话——否则等于提供账号枚举接口。
- 限速：进程内计数，同一学号连续失败 5 次锁 60 秒，返回 429 `{code:"too_many_attempts"}`。
- 会话：`SessionStore` 进程内 `dict[sid, Session]`，`sid = secrets.token_urlsafe(32)`，TTL 12 小时固定（不做滑动续期，避免"永远不过期"的演示状态）。重启即全部失效，前端拿到 401 自动回登录页，行为可接受且已在第 1 节确认。
- Cookie：`HttpOnly; SameSite=Lax; Path=/; Max-Age=43200`，本地 http 不带 `Secure`；`config.py` 增 `cookie_secure: bool = False`，部署 https 时置真。
- CORS：`allow_credentials=True`，源仍是显式白名单（MVP spec 6.1 的约束不变，`*` 与 credentials 本就互斥）。

### 7.2 `/chat` 契约变更（破坏性，必须同步前端）

```python
class ChatRequest(BaseModel):
    message: str          # 仅此一个字段
    # 删除 session_id：会话上下文由 sid 派生，客户端不再提供任何身份/会话标识
    # 新增字段一律拒绝：model_config = ConfigDict(extra="forbid")
```

SSE 事件表在 MVP spec 5.5 基础上**新增两个**：

| event | data | 前端处理 |
|---|---|---|
| `clarify` | `{"question":"你要查哪个学期？","options":[{"label":"2025 秋"},{"label":"2026 春"}]}` | 渲染成可点选项条，点击 = 把该 label 作为下一句 `message` 发送 |
| `sql_result` | `{"sql":"改写后实际执行的 SQL","columns":[…],"rows":[…],"row_count":n,"truncated":bool}` | 折叠的"数据"面板：表格 + 可展开的 SQL 原文 |

`done` 事件不变，新增 `conversation_id`。`error` 事件码表新增：`unauthenticated`、`sql_refused`、`db_unavailable`。

前端收到 `unauthenticated` 或任何 401 → 清登录态、跳 `/login?next=<当前路由>`。

### 7.3 图与节点

```python
class AgentState(TypedDict):
    user_input: str
    student_id: str                 # 新增，由依赖注入，非请求体
    history: list[dict[str, str]]   # 新增，服务端回读
    intent: Literal["navigate","query","answer"] | None
    ...
    needs_clarification: bool
    clarification: dict | None
    sql: dict | None                # {raw, scoped, columns, rows}
```

`RouteDecision` 增 `intent` 判别，router 节点规则：
1. 命中 `resolve_page` 且未要求具体数值 → `navigate`（保持 MVP 行为，跳转卡片仍出）。
2. 涉及"我的 + 成绩/分数/绩点/课表/在借/补考"这类**取数意图** → `query`。
3. 两者都像（"我这学期成绩怎么样，去成绩页看看"）→ `query` 优先，generator 在答案末尾附跳转卡片（两个 executor 结果可共存，`nav_card` 逻辑不变）。
4. 都不像 → `answer`。

`sql_executor` 调 `mcp_servers/academic` 的 `run_sql`，失败/拒绝时置 `error` 并流向 `generator` 出降级话术，与 MVP 的 `tool_executor` 同构。

**歧义澄清**：`sql_executor` 发现结果跨多个 `term` 且用户未指定学期时，置 `needs_clarification=True` 并给出选项，generator 只出 `clarify` 事件、不出 `token`。下一轮用户点选项 → 该文本进 `user_input`，`history` 里上一句就是那个问句，模型据此收敛。FakeProvider 的确定性规则见第 9 节。

### 7.4 `mcp_servers/academic`

```python
server = MCPServer("academic")

@server.tool()
async def describe_schema() -> list[SchemaTable]:
    """返回可查询的语义视图与列含义，供模型写 SQL。"""
@server.tool()
async def run_sql(sql: str, student_id: str) -> SqlResult:
    """执行只读查询。student_id 由调用方服务端注入，不出现在给模型的 schema 中。"""
```

`run_sql` 在 server 侧完成第 4.2 的改写与第 4.3 的校验（与数据库同侧，避免把校验逻辑分散在 backend 与 server 两处），返回 `SqlResult{ok, columns, rows, scoped_sql, refused_code, row_count, latency_ms}`。

`describe_schema` 必须**显式剔除 `student_id` 列**再返回。视图里留着这一列（4.1）与模型能看见这一列（此处）是两件事：前者是改写器的抓手，后者会直接教模型"这里有身份列，我可以拿它做过滤"，从而触发 4.3 第 4 款的拒绝、把可用查询变成失败，甚至诱使它去猜别人的学号。该剔除要有对应单测：`describe_schema()` 的返回值里任何地方都不出现字符串 `student_id`。

**关键接缝**：backend 侧 `ToolSpec.input_schema` 喂给模型时必须**剔除 `student_id`**，`call_tool` 前由 backend 强制写入。实现方式：`tools/base.py` 增

```python
TRUSTED_ARGS: dict[str, set[str]] = {"run_sql": {"student_id"}}

async def call_tool(self, name, args):
    args = {k: v for k, v in args.items() if k not in TRUSTED_ARGS.get(name, set())}  # 丢弃模型/客户端塞的
    args |= {"student_id": current_student_id}                                        # 服务端注入
```

同时把 MVP 遗留的 `validate_args` **未知字段宽松** 改成拒绝（`extra="forbid"`）。这两条是同一条防线的两面：一面丢弃，一面拒绝，缺一个就有洞。

---

## 8. 前端

### 8.1 新增登录页 `LoginView.vue`

沿用已交付的视觉系统（墨蓝 `--ink` / 冷白 `--paper` / 朱红 `--seal`，Bahnschrift 数字与标签）。布局：整页居中一张 380px 表单卡，上方是既有标识牌（复用 `App.vue` 的 `.signplate`，登录页不显示导航），卡内学号、密码两个字段 + 主按钮。

- 错误态：卡内顶部一条朱红左边框提示"学号或密码不正确"，不清空已输学号。
- 429：提示"尝试次数过多，60 秒后再试"，按钮禁用并倒计时。
- 登录成功 → 跳 `next` 参数或 `/`。
- 不做"记住我"、不做找回密码（第 11 节）。
- 无障碍：`<label for>`、错误文案 `role="status" aria-live="polite"`、Enter 提交、焦点顺序正确。

### 8.2 会话状态与守卫

新增 `composables/useAuth.ts`（模块级单例，与 `useChatStream`/`useAssistant` 同风格）：`user`、`status: 'unknown'|'authed'|'anonymous'`、`login()`、`logout()`、`bootstrap()`。

`router.beforeEach`：`status==='unknown'` 时先 `bootstrap()`；非 `/login` 且未登录 → `/login?next=…`；已登录访问 `/login` → `/`。

`App.vue` 顶栏姓名/学号改读 `useAuth().user`；新增"退出"入口（放在姓名右侧，文字按钮，与"收起"同层级）。

### 8.3 四个教务页改读 API

`GET /api/grades`、`/api/schedule`、`/api/makeup`、`/api/loans`（均 `require_student`），返回结构与前端现有类型对齐，页面只换数据源、不动版式。三态必须实现：loading 骨架、空态（沿用 `.empty` 样式，文案给下一步动作）、错误态（含"重试"）。

`frontend/src/data/seed.ts` **降级**为：仅保留作息表 `periods`、`weekdays`、日期格式化等展示常量；`student`、`courses`、`grades`、`makeup`、`loans` 全部删除，改由 API 提供。灌库脚本 `scripts/seed_academic.py` 自带数据常量，不 import 前端文件（Python 读 TS 是耦合陷阱）。

### 8.4 聊天面板

- `useChatStream` 的 fetch 加 `credentials: 'include'`，删除 `session_id`。
- 新事件 `clarify` → 复用 `NavigationCard` 的"单据"视觉做选项条，点击即 `send(option.label)`。
- 新事件 `sql_result` → 表格（列头 + 行），下方 `<details>` 展开显示实际执行的 SQL；`truncated` 时提示"仅显示前 50 行"。
- 401/`unauthenticated` → 调 `useAuth().signOut()` 并跳登录。

---

## 9. 测试策略

### 9.1 越权用例（本文的主角）

| # | 场景 | 期望 |
|---|---|---|
| A1 | 以 20230001 登录，问"陈默的高数成绩" | 只返回周晓楠自己的行；`sql_queries` 有记录且 `sql_scoped` 含 `student_id = ?` |
| A2 | 以 20230001 登录，问"林知远 2025 秋 数据结构多少分"（20230007 有同名课不同分） | 返回周晓楠的分数，不返回林知远的 |
| A3 | 模型生成 `SELECT * FROM v_grades WHERE student_id='20230007'` | 第 4.3 条 4 拒绝，`refused_code='identity_column'`，不执行 |
| A4 | 模型生成 `SELECT … FROM enrollments`（基表） | 白名单拒绝；且 `agent_ro` 对基表无权限，双重 |
| A5 | 模型生成两条语句 `SELECT 1; DROP TABLE students` | 单语句拒绝 |
| A6 | 模型生成 `SELECT SLEEP(30)` | 拒绝，且不占用连接 |
| A7 | 客户端在 `/chat` 请求体塞 `student_id`/`session_id` | 422（`extra="forbid"`） |
| A8 | 无 Cookie 打 `/chat`、`/api/*` | 401 `unauthenticated` |
| A9 | 会话过期后打 `/chat` | 401，前端跳登录 |
| A10 | 同一学号连续错 5 次 | 第 6 次 429，60 秒后恢复 |

A1–A6 用**真 SQL 生成路径**跑（`FakeProvider` 的固定 SQL 脚本 + 真 academic server + 真 SQLite），不是 mock 校验函数——校验层和被测代码之间隔一层 mock 就测不出绕过。

### 9.2 其余

- **单测**：`sqlglot` 改写器（单表、JOIN、子查询、CTE、UNION、别名遮蔽、反引号、大小写混排各一例）；校验清单 10 条逐条；`pbkdf2` 哈希与比较；`SessionStore` TTL 与过期；`TRUSTED_ARGS` 注入与丢弃。
- **集成测**：登录 → `/auth/me` → `/chat` 全链路（`InMemoryRegistry` + `FakeProvider` + SQLite 临时库）；澄清两轮闭环（选项点击 → 收敛到单一学期）；`history` 回读只取本会话且不超过 6 轮。
- **契约测**：现有 `check_routes_contract.py` 保留并扩展——新增断言 `PAGE_REGISTRY` 四条路径与 `/api/*` 四个端点一一对应（页面与数据源不许长期错位）；新增断言 `migrations/mysql` 与 `migrations/sqlite` 文件名集合相同。
- **前端测**：`useAuth` 状态机（unknown→authed/anonymous、401 登出）；守卫重定向；`clarify`/`sql_result` 事件解析；登录页错误态渲染。
- **真库冒烟**（手动，S2 验收）：`docker compose up -d` → 迁移 → seed → `mysql -u agent_ro -p -e "SELECT COUNT(*) FROM campus.enrollments"` 期望 1142 拒绝；`/api/grades` 返回与 SQLite 模式逐字段一致。
- **手测**：第 10 节每条里程碑的验收列。

---

## 10. 里程碑

| # | 内容 | 验收（可执行、可判定） |
|---|---|---|
| S1 | 身份与会话：`students` 表 + 哈希、`/auth/*`、`SessionStore`、`require_student`、CORS credentials、`ChatRequest` 去 `session_id` + `extra="forbid"`、`validate_args` 严格化、前端登录页 + 守卫 + 顶栏真值 | 未登录访问 `/` 跳 `/login`；`curl -i POST /chat`（无 Cookie）→ 401；带 Cookie → 完整事件序列；A7/A8/A9/A10 全过；`/auth/me` 返回的姓名与顶栏一致 |
| S2 | 数据落库：`deploy/docker-compose.yml` + MySQL 起来、极简迁移器、双方言 DDL、`Database` 协议 + `aiomysql`/`aiosqlite`、`scripts/seed_academic.py`、`/api/*` 四端点、四个教务页改读 API | `docker info` 有版本号；迁移幂等（跑两次无变化）；`DB_BACKEND` 两种取值下 `/api/grades` 返回 JSON **逐字段相同**；页面三态可见；`seed.ts` 里不再有业务数据 |
| S3 | 查数能力：`mcp_servers/academic`、改写器 + 校验清单、`TRUSTED_ARGS` 注入、router 三态分流、`history` 回读、`clarify`/`sql_result` 事件、前端选项条与数据表 + SQL 折叠 | 问"我的高等数学成绩"→ 返回分数表格（不是跳转卡片）；跨学期时收到 `clarify`，点选项后收敛；A1–A6 全过；前端能看到实际执行的 SQL |

估时：S1 半天、S2 一天（含 Docker 环境排障）、S3 一天半。合计约三个工作日，比 MVP 那一晚大一圈，**不要塞进一个晚上**。

**风险排序**：S2 的 Docker 环境是唯一"卡住即整体停"的环节（当前 2375 无人监听，见 6.1），所以 S2 的第一步就是把它跑绿并留下判据；S3 的改写器是安全核心，测试优先级最高，任何一条绕过路径没测到就当作还有。

---

## 11. 明确不做（本文范围外）

注册与找回密码、JWT 与无状态令牌、角色与权限体系（教师/管理员）、真实教务系统对接、数据同步、Page Agent 与 iframe 注入、向量语义路由、`news`/`knowledge`/`page-control` 其余 MCP Server、Redis 会话存储、生产级 TLS 与 `Secure` Cookie、审计合规、并发多标签页会话互踢。

**一句告警**：`scripts/seed_academic.py` 里的明文密码 `demo1234` 只因本地仿真而成立。任何把这套代码搬到公网环境之前，必须先换掉 seed 账号并强制 `cookie_secure=True`。

---

## 12. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| WSL docker 引擎起不来（当前即如此） | S2 整体阻塞 | 6.1 的先决判据；失败即停下报告，不用 SQLite 冒充交付 |
| `sqlglot` 改写漏掉某种引用形态（如 lateral、`USING` 别名遮蔽） | 越权读到他人数据 | A1–A6 用例 + 改写器单测覆盖 8 种形态；`agent_ro` 只读视图作为第二层；SQL 外显让人能发现异常 |
| 视图里能否用 `CONNECTION_ID()` 未验证 | 若误采用会走错架构 | 第 4.5 明确禁用该方案 |
| SQLite 与 MySQL 行为漂移（大小写、`ONLY_FULL_GROUP_BY`、排序规则） | 测试全绿、真库出错 | 迁移文件名集合契约测 + S2 真库冒烟 + 页面 JSON 逐字段比对 |
| `FakeProvider` 规则随意图分流膨胀，变成第二套"假 NLU" | 维护成本、与真模型行为背离 | 规则只写"取数/跳转/澄清"三类最小判定，其余交给真模型；集成测显式标注哪些用例仅在真模型下有效 |
| 会话在进程内，重启即失效 | 演示中途重启要重登 | 已在第 1 节确认可接受；`/login` 保留学号只输密码 |
| 历史回读把 token 撑大 | 真模型成本与延迟 | 固定 6 轮上限 + 每条截断 200 字，写进 `config.history_limit` |

---

## 13. 完成定义

以下每条都能被一条命令或现场演示验证，缺一不算完成：

1. 未登录打开 `http://localhost:5173/academic/grades` → 落到 `/login`，登录后回到原页面。
2. 顶栏姓名与学号来自 `/auth/me`，用 20230002 登录时显示"陈默"，不再是常量。
3. 问"我的高等数学成绩" → 聊天面板出现数据表（课程/学期/分数/绩点），并附"查看用到的查询"折叠区能看到改写后的 SQL。
4. 同名课程跨学期时收到 `clarify` 选项条，点"2025 秋"后直接返回该学期结果，不重复追问。
5. A1–A10 十条越权与鉴权用例全部通过，其中 A3/A4/A5 能在 `sql_queries` 表里查到 `refused_code`。
6. `DB_BACKEND=sqlite` 与 `DB_BACKEND=mysql` 两种模式下，四个 `/api/*` 端点返回 JSON 逐字段一致。
7. `docker compose ps` 显示 mysql healthy；`agent_ro` 直接 `SELECT * FROM campus.enrollments` 被拒。
8. 后端 pytest、前端 vitest、契约脚本、`npm run build` 全绿；`git status` 干净，`deploy/.env` 与 `backend/data/*.db` 未被跟踪。
