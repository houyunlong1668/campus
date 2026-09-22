#!/usr/bin/env bash
# k6 HTTP 门禁唯一入口。四条硬契约见 spec §3.2。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8300
DB_PATH="$ROOT/backend/data/k6-smoke.db"
BACKEND_PY="$ROOT/backend/.venv/Scripts/python.exe"
LOG="$(mktemp)"

# 契约：k6 缺失必须红，不许跳过（exit 127 = 命令未找到，语义一致）
if ! command -v k6 >/dev/null 2>&1; then
  echo "k6 未安装。安装：winget install GrafanaLabs.k6（装不上改 choco install k6）" >&2
  exit 127
fi

SERVER_PID=""
cleanup() {
  local rc=$?
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  exit "$rc"   # 显式带出原退出码：k6 阈值违反是 99，吞掉它等于没测
}
trap cleanup EXIT INT TERM

# 契约：临时库每次重建，绝不降级去连真库
rm -f "$DB_PATH"
if ! DB_BACKEND=sqlite SQLITE_PATH="$DB_PATH" \
     "$BACKEND_PY" "$ROOT/scripts/seed_academic.py"; then
  echo "seed 失败，拒绝降级到真库" >&2
  exit 1
fi

# 契约：进程 env 覆盖 backend/.env（pydantic-settings 进程 env 优先于 dotenv）
cd "$ROOT/backend"
DB_BACKEND=sqlite SQLITE_PATH="$DB_PATH" LLM_PROVIDER=fake \
  "$BACKEND_PY" -m uvicorn app.main:app --port "$PORT" >"$LOG" 2>&1 &
SERVER_PID=$!

# 契约：等 /health，超时就红并带出日志
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  echo "/health 轮询 30s 超时，uvicorn 尾部日志：" >&2
  tail -40 "$LOG" >&2
  exit 1
fi

# 契约：k6 的退出码（阈值违反 = 99）由 trap 原样带出。
# `k6 run` 只接受一个脚本——多传一个就报
#   accepts 1 arg(s), received 2
# 并退 127。所以逐个文件跑，任一失败就把它第一个非零码带出去。
# 先 cd 进 k6/tests 再用相对路径：k6 是 Windows 原生 exe，直接传 `/c/Users/...`
# 这种 POSIX 路径要靠 MSYS 自动转换，能出岔子；相对路径不经过它。
cd "$ROOT/k6/tests"
rc=0
for f in ./*.js; do
  echo ""
  echo "=== k6 run $f ==="
  K6_BASE_URL="http://127.0.0.1:$PORT" k6 run "$f" || {
    one=$?
    if [ "$rc" -eq 0 ]; then rc=$one; fi
  }
done
exit "$rc"
