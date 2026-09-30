# 云效 Flow CI/CD 接入指南（选型 D，2026-09-30）

> **为什么是云效**：CD 曾在 GitHub Actions 上三跑三败——托管 runner（美西）→ 杭州 ACR
> 的跨境推送链路超时/假死（run #1–#4 全记录在案）；self-hosted 本机 runner 方案依赖
> Clash 常开 + 机器常亮 + run.cmd 窗口，弃用。最终架构：**代码源 Codeup（阿里云同账号）
> → 云效公共构建集群（杭州/北京）→ 近源直推 ACR**，全链路国内，GitHub Actions 只留三门禁**。

## 0. 仓库侧已完成的准备（无需再动）

| 项 | 状态 |
|---|---|
| `codeup` remote + **main 上游指向 codeup/main** | ✅ 裸 `git push` 即同步触发源（三分支 main/campus-s4/campus-mvp 已全量推入） |
| `backend/Dockerfile`（含 navigation/academic 两个 MCP 子进程的 venv 布局） | ✅ 本地构建+运行实测过（容器内 MCP 四工具拉起） |
| `frontend/Dockerfile` + `frontend/nginx.conf`（静态 + 同源七路径反代 + SPA 回退 + SSE `proxy_buffering off`） | ✅ 本地级联冒烟过 |
| `.dockerignore`（.venv/`*.db`/`**/.env` 全部挡在构建上下文外） | ✅ |
| `.github/workflows/ci-cd.yml` 收敛为纯门禁（name: CI，三 job） | ✅ self-hosted deploy 已摘除 |

## 1. 控制台接入（一次性，约 10 分钟）

1. **开通**：访问 <https://devops.aliyun.com>（flow.aliyun.com 会跳登录）——个人版免费。
   额度在「组织 → 套餐信息」看**月度构建核分**；用量明细在「资源用量」页。
2. **新建流水线**：流水线 Flow → 新建 → 代码源选 **Codeup**（阿里云账号直接授权）→
   仓库 `campus`（`6635d6460696b76220927393/campus`）→ 默认分支 **main** → 保存。
   云效会自动在 Codeup 建 Webhook，**push 即触发**（投递记录在代码源页可查）。
3. **构建集群**：任务配置里选 **cn-hangzhou 或 cn-beijing**（集群系数 1；香港系数 2
   = 同样时长双倍核分，且离 ACR 更远，别选）。
4. **阶段一：后端镜像**（任务类型选「镜像构建」/「构建并推送镜像」，以控制台实际名称为准）：
   - 首次会要求**授权镜像仓库**：跳控制台授权，实例=个人版，命名空间 `hou_yun_long`，
     仓库 `campus`（若 ACR 控制台还没建这个仓库，先去建——参考文档步骤里那种建法）；
   - Dockerfile 路径：`backend/Dockerfile`；**构建上下文（Context）= 仓库根目录 `/`**
     （必须是根——`.dockerignore` 与 `COPY backend/...` 路径都按根布局写死）；
   - 镜像名：`registry.cn-hangzhou.aliyuncs.com/hou_yun_long/campus`；
   - Tag：用控制台的**变量插入按钮**选执行序号/构建号，形如 `backend-${执行序号}`
     （没有变量按钮就填 `backend-build`——固定 tag 会覆盖，可追溯性差，仅应急）。
5. **阶段二：前端镜像**——同上，Dockerfile `frontend/Dockerfile`，Tag `frontend-…`。
   两阶段串行或并列均可（都只依赖代码源）。
6. **触发验证**：本机 `git push`（去 codeup）→ 看流水线日志 → ACR 控制台确认两个 tag。

## 2. 推送拓扑（本机 git 习惯的一处变化）

- `git push` → **codeup**（上游已切）→ 触发云效流水线 = 自动出镜像；
- `git push github main` → 只跑 GitHub 三门禁（pytest+契约 / vitest+build / k6 四门）；
  **推镜像前想让门禁把关，就先跑一遍它**（或本地 `uv run pytest` + `npx vitest run`，
  见 CLAUDE.md 常用命令）；
- `git push gitee main` / `git push origin main` → 备份镜像（gitee / gitcode）。

> 后续迭代（阶段 B）：把测试门禁搬进流水线第 0 阶段（公共集群任务里装 uv + node 跑
> 三门禁），实现「门禁拦镜像」全自动。先跑通镜像交付，再补这步。

## 3. 用量与计费

- 单位「核分」= 任务时长(分钟) × CPU 核数 × 集群系数（杭州/北京 = 1）；
- 本流水线一次双镜像构建约 3–6 分钟（免费额度具体数值在「组织 → 套餐信息」确认）；
- **不跑任务零成本**；当月核分用尽后新任务会失败（可开按量计费兜底）。

## 4. 排障

| 症状 | 查什么 |
|---|---|
| push 不触发 | Codeup 仓库 → 云效代码源页的 Webhook 投递记录 |
| 镜像推送失败 | 「授权镜像仓库」是否过期；ACR 仓库 `hou_yun_long/campus` 是否已建；tag 是否冲突 |
| 任务排队 | 免费版并发上限，等前序任务；或减两阶段并行 |
| 构建上下文报错（COPY 找不到文件） | Context 必须是仓库根 `/`，不是 `backend/` |
| GitHub 侧 run #5 的 deploy 一直 queued | 那是旧 self-hosted 方案遗骸，**手动 Cancel 即可**（deploy job 已从工作流摘除） |

## 5. 关联背景（历史决策存档）

- run #1：k6 安装步 `.zip` URL 404（linux 官方资产是 `.tar.gz`，官方 API 实锤）；
- run #2：`mcp_servers/academic` 依赖未同步（sqlglot 缺失会把 A1–A6 挂到超时）；
- run #3/#4：跨境推送超时（结构性问题，催生本指南）；
- 本机 runner 包（若曾下载）位于 `C:\gh-runner\campus\`，选型 D 后不再需要，可删。
