#!/bin/bash
# 为伺服器 IP 申请免费 HTTPS 证书（Let's Encrypt 6 天短效 IP 证书），并设定自动续期
# 用法（在伺服器上，以 root 执行）：bash /opt/ydd-support/https_setup.sh
# 之后重复执行也安全：会检查、补齐设定、重新启动服务。
set -e
APP="$(cd "$(dirname "$0")" && pwd)"
DEMO="${DEMO_DIR:-/opt/ydd-demo}"
NAME="ydd-ip"
IP="${1:-$(curl -s --max-time 5 ifconfig.me || true)}"
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "取不到伺服器公网 IP，请这样执行：bash $0 47.95.151.115"; exit 1; }
echo "== 伺服器公网 IP：$IP"

echo "== 1/5 检查系统版本（需要 v1.2.6 以上，才能提供证书验证档）"
curl -s --max-time 5 "http://127.0.0.1/.well-known/acme-challenge/ping-check-0000" -o /dev/null -w "%{http_code}" | grep -q "404" \
  || { echo "系统没有在 80 端口运行，请先完成 v1.2.6 更新并确认 systemctl status ydd-support 为 running"; exit 1; }
grep -q 'acme_dir' "$APP/server.py" || { echo "目前程式版本太旧，请先更新到 v1.2.6"; exit 1; }

echo "== 2/5 安装新版 certbot（需要 5.4 以上才支援 IP 证书）"
if ! command -v snap >/dev/null; then apt-get update -qq && apt-get install -y -qq snapd; fi
if ! snap list certbot >/dev/null 2>&1; then
  apt-get remove -y -qq certbot >/dev/null 2>&1 || true
  snap install --classic certbot
fi
snap refresh certbot >/dev/null 2>&1 || true
ln -sf /snap/bin/certbot /usr/bin/certbot
certbot --version

echo "== 3/5 申请证书"
mkdir -p "$APP/data/acme/.well-known/acme-challenge"
certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --preferred-profile shortlived --webroot -w "$APP/data/acme" \
  --ip-address "$IP" --cert-name "$NAME" --keep-until-expiring
CERT="/etc/letsencrypt/live/$NAME/fullchain.pem"
KEY="/etc/letsencrypt/live/$NAME/privkey.pem"
[ -f "$CERT" ] || { echo "申请失败：请确认阿里云防火墙已开放 80 和 443 端口"; exit 1; }
# 6 天证书：剩 3 天就续期（certbot 每天自动检查两次）
sed -i '/^renew_before_expiry/d' "/etc/letsencrypt/renewal/$NAME.conf"
sed -i "1i renew_before_expiry = 3 days" "/etc/letsencrypt/renewal/$NAME.conf"

echo "== 4/5 续期后自动重启服务"
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/ydd-restart.sh <<'EOF'
#!/bin/bash
systemctl restart ydd-support
systemctl is-enabled ydd-demo >/dev/null 2>&1 && systemctl restart ydd-demo || true
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/ydd-restart.sh
systemctl list-timers 2>/dev/null | grep -q certbot || echo "（注意：找不到 certbot 自动续期排程，请把这段画面截图给维护者）"

echo "== 5/5 启用 HTTPS 并重启"
python3 - "$APP/config.json" "$CERT" "$KEY" 443 <<'PY'
import json, os, sys
p, cert, key, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
c = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
c.update({"tls_cert": cert, "tls_key": key, "https_port": port})
c.setdefault("port", 80)
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已更新", p)
PY
if [ -f "$DEMO/config.json" ]; then
python3 - "$DEMO/config.json" "$CERT" "$KEY" <<'PY'
import json, sys
p, cert, key = sys.argv[1], sys.argv[2], sys.argv[3]
c = json.load(open(p, encoding="utf-8"))
c.update({"tls_cert": cert, "tls_key": key, "https_port": c.get("port", 8081)})
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已更新", p)
PY
fi
systemctl restart ydd-support
systemctl is-enabled ydd-demo >/dev/null 2>&1 && systemctl restart ydd-demo || true
sleep 2
if curl -s --max-time 5 "https://$IP/healthz" | grep -q '"ok"'; then
  echo ""
  echo "完成！请用手机打开：https://$IP"
  [ -f "$DEMO/config.json" ] && echo "演示版：https://$IP:8081"
else
  echo "HTTPS 还连不上：请确认阿里云防火墙已开放 443 端口，然后执行 systemctl status ydd-support --no-pager 截图"
fi
