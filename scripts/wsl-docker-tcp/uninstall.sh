#!/usr/bin/env bash
# 回滚 install.sh 的全部改动: 删除 drop-in, 让 dockerd 回到只监听 unix socket。
#   用法: sudo bash uninstall.sh
# daemon.json 从未被本方案改动, 因此无需恢复。
set -euo pipefail

CONF_DIR=/etc/systemd/system/docker.service.d
CONF="$CONF_DIR/10-windows-tcp.conf"
PORT="${PORT:-2375}"

[ "$(id -u)" -eq 0 ] || { echo "!! 需要 root: sudo bash uninstall.sh" >&2; exit 1; }

RUNNING=$(docker ps -q 2>/dev/null | wc -l)
if [ "${1:-}" != "--force" ] && [ "$RUNNING" != "0" ]; then
  echo "!! 当前有 $RUNNING 个容器在运行, 重启会中断它们。确认后用: sudo bash uninstall.sh --force"
  docker ps
  exit 1
fi

if [ -f "$CONF" ]; then
  rm -f "$CONF"
  echo "-> 已删除 $CONF"
  # 顺带清掉本方案留下的备份, 只保留最新 0 份(备份内容就是被删的这份, 无信息量)
  rm -f "$CONF".bak.* 2>/dev/null || true
else
  echo "-> 没有 drop-in, 幂等跳过"
fi

systemctl daemon-reload
systemctl restart docker
sleep 2

echo
echo "=== 验证 ==="
if ss -ltn | grep -q ":$PORT"; then
  echo "!! $PORT 仍在监听, 可能有别处也配了 hosts:"
  ss -ltnp | grep ":$PORT"
  echo "   排查: systemctl cat docker | grep -E 'ExecStart|drop-in'"
  exit 1
fi
echo "OK $PORT 已释放"
docker info --format 'OK 引擎仍正常工作( unix socket ): {{.ServerVersion}}'
