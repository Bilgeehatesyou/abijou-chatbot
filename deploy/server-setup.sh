#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04/24.04 server. Run as root:
#   bash /opt/ajilt/deploy/server-setup.sh bot.example.com
# Without a domain it uses <server-ip>.sslip.io, which still gets real HTTPS.
set -euo pipefail

APP_DIR=/opt/ajilt
DOMAIN="${1:-$(curl -s https://api.ipify.org | tr . -).sslip.io}"

sed -i 's/\r$//' "$APP_DIR/.env"  # .env copied from Windows
if ! grep -q '^DASHBOARD_PASSWORD=.\+' "$APP_DIR/.env"; then
  echo "Set DASHBOARD_PASSWORD in $APP_DIR/.env first - the dashboard shows customer names and phones." >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv debian-keyring debian-archive-keyring apt-transport-https curl gnupg

# Caddy: reverse proxy with automatic HTTPS (Meta webhooks require HTTPS)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi

id ajilt >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin ajilt
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R ajilt:ajilt "$APP_DIR"
chmod 600 "$APP_DIR/.env" "$APP_DIR"/secrets/* 2>/dev/null || true

cp "$APP_DIR/deploy/ajilt.service" /etc/systemd/system/ajilt.service
sed "s/{DOMAIN}/$DOMAIN/" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now ajilt
systemctl reload caddy || systemctl restart caddy

echo
echo "Done. Bot + dashboard: https://$DOMAIN"
echo "  Dashboard:   https://$DOMAIN/dashboard"
echo "  Meta webhook: https://$DOMAIN/webhook"
echo "  Logs:        journalctl -u ajilt -f"
