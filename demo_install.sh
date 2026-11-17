#!/bin/bash
# 安装 / 更新 演示版（与正式版分开：独立目录、独立资料库、独立端口）
# 用法（在伺服器上）：bash /opt/ydd-support/demo_install.sh
# 每次正式版更新后再执行一次，演示版就会同步成最新程式并重置示范资料。
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${DEMO_DIR:-/opt/ydd-demo}"
PORT="${DEMO_PORT:-8081}"
if [ "$SRC" = "$DST" ]; then echo "请在正式版目录执行本脚本"; exit 1; fi

echo "== 复制程式：$SRC → $DST"
mkdir -p "$DST/static"
cp "$SRC"/*.py "$DST"/
cp "$SRC"/static/* "$DST"/static/
if [ ! -f "$DST/config.json" ]; then
  cat > "$DST/config.json" <<EOF
{"port": $PORT, "demo": true, "daily_backup": false, "db_path": "data/demo.db", "demo_keys_from": "$SRC/data/support.db"}
EOF
fi
grep -q '"demo": *true' "$DST/config.json" || { echo "$DST/config.json 不是演示版设定，已停止"; exit 1; }
# 旧的演示版设定补上「从正式版套用金钥」
python3 - "$DST/config.json" "$SRC/data/support.db" <<'PY'
import json, sys
p, src = sys.argv[1], sys.argv[2]
c = json.load(open(p, encoding="utf-8"))
if not c.get("demo_keys_from"):
    c["demo_keys_from"] = src
    json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False)
PY

if [ -z "$NO_SYSTEMD" ]; then
  cat > /etc/systemd/system/ydd-demo.service <<EOF
[Unit]
Description=YDD support hours (DEMO)
After=network.target
[Service]
WorkingDirectory=$DST
ExecStart=/usr/bin/python3 server.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl stop ydd-demo 2>/dev/null || true
fi

echo "== 建立示范资料"
(cd "$DST" && python3 demo_seed.py)

if [ -z "$NO_SYSTEMD" ]; then
  # 每天凌晨 4 点重置示范资料
  cat > /etc/cron.d/ydd-demo <<EOF
0 4 * * * root systemctl stop ydd-demo; cd $DST && /usr/bin/python3 demo_seed.py >> /var/log/ydd-demo-reset.log 2>&1; systemctl start ydd-demo
EOF
  systemctl enable --now ydd-demo >/dev/null 2>&1
  systemctl restart ydd-demo
  sleep 1
  systemctl is-active ydd-demo >/dev/null && echo "== 演示版已启动：http://$(curl -s --max-time 3 ifconfig.me || echo 伺服器IP):$PORT" || { echo "演示版启动失败："; journalctl -u ydd-demo -n 20 --no-pager; exit 1; }
fi
