# k6 HTTP 稳定与安全断言门禁 设计文档

**日期**：2026-09-22
**状态**：待用户评审
**范围**：为本项目引入 k6 环境与 k6 测试套件（纯 JS），从**真实 HTTP** 这一层补上 Python 测试的盲区。覆盖 S1（身份会话）与 S2（数据层）已交付的表面。

---

## 0. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| `2026-09-22-campus-roadmap-s4-s7-design.md` | **§5 与 §10 把「压测」列为明确不做**。本 spec 在其边界内工作，**不修改它的文字**，见下方裁决 |
| `2026-09-20-campus-auth-text2sql-mysql-design.md`（spec2） | 提供本 spec 要测的端点与鉴权行为：`/auth/*`、`/chat` 的 `extra="forbid"`、`require_student`、登录限速（错 5 次锁 60 秒） |
| `plans/2026-09-20-campus-s2-mysql-data-layer.md` | 提供四端点响应形状与三账号 seed 数据的权威计数 |
| `plans/2026-09-22-campus-s3-text2sql.md`（**尚未执行**） | S3 落地后本套件才加其事件断言，见第 7 节接入点 |

### 0.1 一条边界裁决（必须先写死，否则与 roadmap spec 自相矛盾）

roadmap spec §5（S5 明确不做）写「RAGAS、**并发/压测**、模型幻觉评测…」，§10 写「不做与面试演示无关的性能与可用性工程（**压测**、灰度、多活）」。本 spec 对"压测"的读法是：

> **"压测" = 性能容量压测**，即找 p95 拐点、QPS 上限、用 `arrival-rate`/`rps` 场景定吞吐目标的那类测试。

据此：

- 本套件**不含任何吞吐目标**：没有 `constant-arrival-rate` / `constant-rps` 场景，只有 `constant-vus` 与 `shared-iterations`，**VU ≤ 2**。四文件里唯一带时长的是 `session_isolation.js` 的 `duration: '5s'`，其余三个是 `shared-iterations`（1 VU × 1 轮，没有 duration）；`sse_chat` 的 15s 是**阈值**不是时长。→ 不触发红线。
- `session_isolation.js` 用 2 个 VU **不是压测**，是**功能正确性断言**（验证会话隔离这一安全属性），归 roadmap §5 里 S5 的「越权防护有效性」维度，不归「性能」。
- **将来要做真压测 = 另一份 spec + 先修订 roadmap §5/§10**，不在本 spec 内顺手扩展。

---

## 1. 已确认的前提决策

| 议题 | 决策 | 说明 |
|---|---|---|
| 测试工具 | **k6**（用户 2026-09-22 指定，此后接口/稳定性/并发测试优先 k6） | 与 Python 测试**互补**，不是替代 |
| 脚本语言 | **纯 JS（ES module），不用 TS** | k6 跑在自带 Go+JS 运行时（goja），**不执行 TypeScript**；上 TS 必须引入 esbuild/vite 打包链，与"轻量互补"相悖 |
| 测什么层 | **HTTP 稳定 + 安全行为断言** | 走真实网络；不测业务逻辑（pytest 的活）、不测 UI（Playwright 的活） |
| 测哪些表面 | **仅 S1 + S2** | 这些现在就跑得起来；S3 事件等 S3 落地 |
| 执行方式 | 独立一条命令 `scripts/run_k6.sh` | **不进 pytest 门禁**——避免在 pytest 进程里起子进程，两个测试体系耦死 |
| 模型 | **强制 `LLM_PROVIDER=fake`** | 真模型要 Key、延迟不可控，会让阈值抖动 |
| 数据库 | **强制 `DB_BACKEND=sqlite` + 临时库**，每次跑前重建 | 绝不碰 MySQL 真库 |

---

## 2. 目标与非目标

### 2.1 与既有 Python 测试的互补分工

| 关注点 | pytest（既有 15 文件） | k6（本套件） |
|---|---|---|
| 业务逻辑、SQL 校验清单、改写器八形态 | ✅ | ❌ |
| **真实 HTTP 网络**（`fastapi.testclient` 不经过网络与 uvicorn） | ❌ | ✅ |
| 真实 Cookie 头经网络传递 | ❌（ASGI 内存） | ✅ |
| SSE 经真实连接收完整流 | ❌ | ✅（只断最终 body） |
| **并发下会话不串** | ❌（串行执行） | ✅ 2 VU |
| 429 走真端点的时序 | 部分（只单测 `LoginGuard`） | ✅ |
| A1–A6 真 SQL 越权路径 | ✅ | ❌（k6 不扫描） |
| UI 行为 | ❌ | ❌（Playwright，S5 收口） |

**结论**：pytest 证"逻辑对不对"，k6 证"真的过了一层网络之后还对不对"。两边断言互不重复。

### 2.2 非目标（明确不做）

1. **不做漏洞扫描**（SQLi / XSS / CSRF 主动探测）。本套件的"安全"是**断言已有行为**（401/422/429、会话隔离），不是找未知漏洞。要扫描是另一件事、另选工具。
2. **不断言 SSE 逐帧时序与首 token 延迟**——k6 的 `http.request` 默认收完整响应才返回。
3. **不测前端 UI**（Playwright 归 S5）、**不测真模型**（强制 fake provider）。
4. **不进 pytest / 契约脚本门禁**。
5. **不覆盖 S3 事件**（`sql_result`/`clarify`/`sql_refused`），见第 7 节。
6. **不做性能容量压测**，见 0.1。

---

## 3. 架构：目录与运行契约

### 3.1 文件结构

```
k6/
  lib/
    env.js        # BASE_URL、三账号常量、密码（**本套件**唯一一处写 demo1234；仓库其它处已有，见 spec2 §11 告警）
    helpers.js    # 模块级 http.cookieJar()；login(sid)、json()、expect()
  tests/
    api_smoke.js          # 四端点 200 + 响应形状
    authz.js              # 401 / 422 / 429
    session_isolation.js  # 2 VU 并发，断言数据不串
    sse_chat.js           # /chat 完整事件序列（FakeProvider）
scripts/
  run_k6.sh               # 唯一入口
```

**唯一入口契约**：

```bash
bash scripts/run_k6.sh            # 起后端 → 等 /health → k6 run 全部文件 → 关 → 透传退出码
```

### 3.2 `run_k6.sh` 的四条硬契约

| # | 契约 | 为什么 |
|---|---|---|
| 1 | 固定端口 **8300** | 避开 8000（开发）、8100/8200（S2 双后端比对），不撞车 |
| 2 | 进程环境强制 `LLM_PROVIDER=fake`、`DB_BACKEND=sqlite`、`SQLITE_PATH=backend/data/k6-smoke.db` | `backend/.env` 现在是 `openai_compat` + deepseek-flash；pydantic-settings **进程 env 优先于 dotenv**，所以 shell 里 export 能盖住 |
| 3 | 跑前 `rm -f` 临时库 + 重跑 seed；跑完不碰真库 | 幂等、可复现；绝不污染 MySQL |
| 4 | `trap` 兜底 `kill` + 轮询 `/health`（30s 超时）+ **透传 k6 退出码** | 8300 不许悬着（S2 踩过 8100/8200 悬空）；起不来必须红；阈值违反时 k6 退 **99**，吞掉它等于没测 |

### 3.3 环境与安装

```bash
winget install GrafanaLabs.k6     # 2026-09-22 实测 winget 源存在，版本 2.2.0；装不上改 choco install k6
k6 version                         # 验收：输出版本号
```

脚本第一步 `command -v k6` 检查，缺失则打印上面第一条命令并 **exit 127**——不跳过、不降级。

---

## 4. 四个测试文件：断言与阈值

> **单位**：`http_req_duration` 阈值单位是**毫秒**（k6 默认）——下文 `p(95)<1000` 即 1 秒，`p(95)<15000` 即 15 秒。

### 4.0 两个会翻车的坑（写死，别在实现时"优化"掉）

1. **k6 把 4xx/5xx 计入 `http_req_failed`**。`authz.js` 故意打 401/422/429——给它设 `http_req_failed: rate===0` 会**必红且红得莫名其妙**。故按文件分阈值：成功路径文件设 `http_req_failed: rate===0`，`authz.js` **只看 `checks`**。
2. **429 会锁学号**（同号错 5 次锁 60 秒，按 `student_id` 计数且不区分账号是否存在）。拿真账号测就把 `20230001` 锁了，后续文件全 429。**用炮灰学号 `20239999`**（不在 seed 里 → 本来就 401 → 同样计数）；且 `run_k6.sh` 每次起**新进程**，`LoginGuard` 是进程内计数 → 每轮归零，可复现。

**Cookie 显式用 per-VU jar**：`helpers.js` 模块级 `const jar = http.cookieJar()`（k6 模块代码按 VU 求值 → 每 VU 一个 jar），`login()` 与后续请求一律传 `{ jar }`。这样"会话隔离"测的是真实隔离，不是碰巧。

### 4.1 `api_smoke.js` — 1 VU × 1 轮

断言：`GET /health` 200 → `POST /auth/login`（20230001）200 → 四端点各 200，且响应键集合精确匹配：`grades`→`{grades}`、`schedule`→`{courses}`、`makeup`→`{items}`、`loans`→`{items}`；`grades.length === 13`、`schedule.courses.length === 12`、`loans.items.length === 4`。

阈值：`http_req_failed: ['rate===0']`、`checks: ['rate===1']`、`http_req_duration: ['p(95)<1000']`。

### 4.2 `authz.js` — 1 VU × 1 轮

断言：未登录 `GET /api/grades`→**401**；未登录 `POST /chat`→**401**；登录后请求体塞 `student_id`→**422**；塞 `session_id`→**422**；炮灰号 `20239999` 连错密码 5 次后第 6 次→**429**。

阈值：**不设 `http_req_failed`**；仅 `checks: ['rate===1']`。

### 4.3 `session_isolation.js` — **2 VU** × `duration: '5s'`

按 `__VU % 2` 分配账号（20230001 / 20230002），各自 `login()` 后轮打 `/api/grades`，断言：20230001 必含 `数据结构（暑期补习）` 且 `length === 13`；20230002 必为 `length === 6` 且**课程码集合与前者不相交**。

阈值：`http_req_failed: ['rate===0']`、`checks: ['rate===1']`、`http_req_duration: ['p(95)<1000']`。

### 4.4 `sse_chat.js` — 1 VU × 1 轮

断言：登录后 `POST /chat`（`{ timeout: '30s' }`，消息 `这学期上什么课`）：body 含 `event: token`、`event: nav_card`、`event: done`、`"conversation_id"`，且**不含 `event: error`**。

阈值：`http_req_failed: ['rate===0']`、`checks: ['rate===1']`、`http_req_duration: ['p(95)<15000']`（留流式余量）。

> 只断最终 body，不断首 token 时延——那是 k6 做不到的（见 2.2 第 2 条）。

---

## 5. 错误处理：全部 fail-loud，绝不降级

| 情况 | 行为 |
|---|---|
| k6 未安装 | 打印 `winget install GrafanaLabs.k6` → **exit 127**，不跳过 |
| `/health` 轮询超时（30s） | 打印 uvicorn 尾部日志 → **exit 1** |
| k6 阈值违反 | k6 退 **99**，脚本**原样透传**（绝不 `\|\| true`） |
| Ctrl+C 或任何提前退出 | `trap` 杀 uvicorn——8300 不许悬着 |
| 临时库创建或 seed 失败 | 立即退出，**不许降级去连真库** |

---

## 6. 后续接入点

本切片刻意留下的接缝，使后续工作是增量而非重写：

| 后续工作 | 接入方式 |
|---|---|
| **S3 事件断言** | S3 落地后新增 `k6/tests/s3_events.js`：`sql_result` 含 `student_id = ?` 的 `sql`、`clarify` 选项条、`sql_refused` 错误码。`run_k6.sh` 用 `k6 run k6/tests/*.js`，新文件自动纳入，无需改脚本 |
| **S5 五维测试体系** | roadmap §5 的「任务完成度」「越权防护有效性」两维可引用本套件的 `checks` 作为 HTTP 层证据；路径合规/工具选择那三维仍属 pytest 域 |
| **Playwright E2E** | UI 层归它（S5 收口），与 k6 不重叠 |
| **真压测** | 需先修订 roadmap §5/§10，另立 spec（见 0.1） |

---

## 7. 验收判据（可跑、可判定）

| # | 判据 | 命令 | 期望 |
|---|---|---|---|
| 1 | k6 可用 | `k6 version` | 输出版本号，非空 |
| 2 | 一条命令全绿 | `bash scripts/run_k6.sh` | **exit 0** |
| 3 | 四文件真跑了 | 上一条的输出 | 含 4 个文件名，各自 `checks` 汇总 `100.00%` |
| 4 | **故意破坏必须变红** | 把 `api_smoke.js` 的 `grades.length===13` 改成 `===14` 后重跑 | exit **99**；改回后恢复 0 |
| 5 | 429 不污染真账号 | 跑完后 20230001 登录 | 仍 200（与执行顺序无关） |
| 6 | 不留进程 | 结束后 `curl -s 127.0.0.1:8300/health` | 拒绝连接 |
| 7 | 不碰真库 | 跑前跑后比对 | 只写 `backend/data/k6-smoke.db`；MySQL 中 `messages`/`sql_queries` 行数不变 |
| 8 | 不越压测红线 | `rg "constant-arrival-rate\|constant-rps" k6/`；`rg "vus:" k6/` | 前者零命中（那两个正是 k6 定吞吐目标的场景类型）；后者全部 ≤ 2 |

---

## 8. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| k6 版本升级改了默认 Cookie 行为 | 隔离测试静默失效 | 显式 `http.cookieJar()` 传参，不依赖默认（4.0） |
| 阈值写太严，Windows/WSL 抖动偶发红 | 误报让人开始忽略红 | `p(95)<1000ms` 是本地回环 + SQLite + FakeProvider 的宽松值；真红要先看是不是阈值问题 |
| `authz.js` 被后人补上 `http_req_failed` 阈值 | 必红且难懂 | 4.0 第 1 条写死理由，实现时在文件头注释再钉一次 |
| 有人为"快"把 `LLM_PROVIDER` 改回真模型 | 阈值抖动、烧 Key、结果不可复现 | `run_k6.sh` 强制 export，不读 `.env` 的该字段 |
| S3 落地后没人回来加事件断言 | 套件覆盖落后于功能 | 第 6 节接入点写明"新文件自动纳入"，S3 收口时按 spec §10 验收一并做 |
