#!/usr/bin/env bash
# 让 WSL 内的 dockerd 额外监听 127.0.0.1:2375, 供 Windows 侧原生工具直连。
#   安装: sudo bash install.sh
#   回滚: sudo bash uninstall.sh
#
# 为什么走 systemd drop-in, 而不是往 /etc/docker/daemon.json 加 "hosts":
#   本机 docker.service 的 ExecStart 带 "-H fd://"(socket 激活)。若 daemon.json 里
#   再写 hosts, dockerd 会因"同一指令同时出现在命令行与配置文件"直接启动失败。
#   本脚本完全不触碰 daemon.json, 其中现有的 registry-mirrors 与 cgroup 配置保持原样。
#
# 为什么绑 127.0.0.1 而不是 0.0.0.0:
#   实测 NAT 模式下 WSL 内绑 127.0.0.1 的端口, Windows 用 localhost 依然可达;
#   而绑 0.0.0.0 会额外暴露到 WSL 的 vEthernet 网段(eth0), 属无必要的面扩大。
#
# 若报 "$'\r'" 说明本文件被 Windows 编辑器改成了 CRLF, 先执行:
#   sed -i 's/\r$//' install.sh
set -euo pipefail

BIND="${BIND:-127.0.0.1}"
PORT="${PORT:-2375}"
CONF_DIR=/etc/systemd/system/docker.service.d
CONF="$CONF_DIR/10-windows-tcp.conf"
UNIT=/lib/systemd/system/docker.service

[ "$(id -u)" -eq 0 ] || { echo "!! 需要 root: sudo bash install.sh" >&2; exit 1; }
[ -f "$UNIT" ] || { echo "!! 找不到 $UNIT (docker.service 可能不是 apt 装的)" >&2; exit 1; }

# 重启 docker 会中断正在运行的容器, 先挡一道
RUNNING=$(docker ps -q 2>/dev/null | wc -l)
if [ "${1:-}" != "--force" ] && [ "$RUNNING" != "0" ]; then
  echo "!! 当前有 $RUNNING 个容器在运行, 重启会中断它们:"
  docker ps
  echo "!! 确认无妨后用: sudo bash install.sh --force"
  exit 1
fi

BASE=$(grep -m1 '^ExecStart=' "$UNIT")
[ -n "$BASE" ] || { echo "!! $UNIT 中没找到 ExecStart" >&2; exit 1; }
NEW="${BASE} -H tcp://${BIND}:${PORT}"

if [ -f "$CONF" ]; then
  BAK="$CONF.bak.$(date +%Y%m%d%H%M%S)"
  cp -a "$CONF" "$BAK"
  echo "-> 旧 drop-in 已备份: $BAK"
fi

mkdir -p "$CONF_DIR"
{
  echo "# 由 scripts/wsl-docker-tcp/install.sh 生成; 回滚: sudo bash uninstall.sh"
  echo "[Service]"
  echo "ExecStart="
  echo "$NEW"
} > "$CONF"
echo "-> 写入 $CONF"
echo "   $NEW"

systemctl daemon-reload
systemctl restart docker
sleep 2

echo
echo "=== 验证 ==="
ss -ltnp | grep ":$PORT" || { echo "!! 端口未监听, 排查: journalctl -u docker -n 50" >&2; exit 1; }
if docker -H "tcp://${BIND}:${PORT}" version --format 'OK Docker 引擎 {{.Server.Version}} 已通过 TCP 响应'; then
  :
else
  echo "!! TCP API 无响应, 排查: journalctl -u docker -n 50" >&2
  exit 1
fi
echo "本地 unix socket 仍正常: $(docker info --format '{{.ServerVersion}}')"

echo
echo "=== 下一步(在 Windows PowerShell 里) ==="
echo "  pwsh -File scripts/wsl-docker-tcp/setup-windows.ps1"
