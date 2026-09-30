# 后端镜像：FastAPI 应用 + 两个 MCP server（stdio 子进程在镜像内拉起）。
#
# 目录布局必须满足 config.py 的默认值：
#   navigation_server_dir = <仓库根>/mcp_servers/navigation
#   academic_server_dir   = <仓库根>/mcp_servers/academic
# 即镜像内保持 /repo/{backend,mcp_servers,scripts}——config.py 位于
# /repo/backend/app/config.py，parent³ 正好是 /repo。也可用环境变量
# NAVIGATION_SERVER_DIR / ACADEMIC_SERVER_DIR 覆盖（pydantic-settings）。
#
# 解释器选择（tools/stdio_mcp.py::_server_python）：
#   academic 有自己的 .venv（sqlglot/aiosqlite 只在其中）→ 镜像内 uv sync 建出
#   /repo/mcp_servers/academic/.venv/bin/python；navigation 不建 venv → 回落
#   sys.executable（即 backend venv，mcp 包在 backend 依赖里）——与本地行为一致。

FROM python:3.13-slim

# 构建期用 uv 装依赖（运行期直接用 .venv/bin/python，镜像里不需要 uv 常驻）
RUN pip install --no-cache-dir uv

WORKDIR /repo

# --- 依赖层（先锁文件后代码，充分利用层缓存）---
# --python 显式用镜像自带解释器：否则 uv 可能去 github 下托管 Python（国内网络必卡）。
# 同一 RUN 内删 uv 缓存与 __pycache__——分层删不减体积（字节还在下层），同层删才瘦身。
COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-install-project --python /usr/local/bin/python \
    && rm -rf /root/.cache \
    && find . -type d -name __pycache__ -prune -exec rm -rf {} +

COPY mcp_servers/academic/pyproject.toml mcp_servers/academic/uv.lock mcp_servers/academic/
RUN cd mcp_servers/academic && uv sync --frozen --no-install-project --python /usr/local/bin/python \
    && rm -rf /root/.cache \
    && find . -type d -name __pycache__ -prune -exec rm -rf {} +

# --- 代码层 ---
COPY backend/app backend/app
COPY mcp_servers/navigation mcp_servers/navigation
COPY mcp_servers/academic/*.py mcp_servers/academic/
# seed 脚本随镜像带：compose/容器内可直接灌库（run_migrations 在其 main 里）
COPY scripts/seed_academic.py scripts/seed_academic.py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# 运行期数据库由环境注入：DB_BACKEND / MYSQL_HOST / MYSQL_PORT / MYSQL_PASSWORD…
# 默认值见 backend/app/config.py（mysql），compose 场景传 MYSQL_HOST=mysql。

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["./.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

WORKDIR /repo/backend
CMD ["./.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
