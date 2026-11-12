#!/usr/bin/env bash
set -euo pipefail

: "${APP_DIR:=/opt/property-hunt}"
: "${REPO_URL:=https://github.com/guofeng201507/property-hunt.git}"
: "${BASIC_AUTH_USER:?BASIC_AUTH_USER is required}"
: "${BASIC_AUTH_PASS:?BASIC_AUTH_PASS is required}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run bootstrap.sh as root on the server." >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  nginx apache2-utils rsync git python3 python3-venv python3-pip ca-certificates curl

echo "==> Ensuring 2GB swap"
if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Ensuring service user"
if ! id property >/dev/null 2>&1; then
  useradd -r -s /usr/sbin/nologin -d "$APP_DIR" property
fi

echo "==> Updating code"
if [ ! -d "$APP_DIR/.git" ]; then
  mkdir -p "$(dirname "$APP_DIR")"
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

echo "==> Installing Python dependencies"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/pip" install --no-cache-dir -e "$APP_DIR"

echo "==> Fixing permissions"
mkdir -p "$APP_DIR/db" "$APP_DIR/data/geo" "$APP_DIR/.streamlit"
chown -R property:property "$APP_DIR/db" "$APP_DIR/data" "$APP_DIR/.streamlit"
if [ -f "$APP_DIR/.env" ]; then
  chown property:property "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

echo "==> Writing systemd service"
cat >/etc/systemd/system/property-hunt.service <<EOF
[Unit]
Description=Property Hunt Streamlit
After=network.target

[Service]
Type=simple
User=property
Group=property
WorkingDirectory=$APP_DIR
Environment=HOME=$APP_DIR
Environment=PROPERTY_HUNT_DB=$APP_DIR/db/property.db
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/.venv/bin/streamlit run src/property_hunt/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Writing Nginx site + Basic Auth"
htpasswd -bc /etc/nginx/.htpasswd "$BASIC_AUTH_USER" "$BASIC_AUTH_PASS" >/dev/null
cat >/etc/nginx/sites-available/property-hunt <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    auth_basic "Property Hunt";
    auth_basic_user_file /etc/nginx/.htpasswd;
    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
        proxy_buffering off;
    }
}
EOF
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/property-hunt /etc/nginx/sites-enabled/property-hunt
nginx -t

echo "==> Starting services"
systemctl daemon-reload
systemctl enable --now nginx
systemctl reload nginx
systemctl enable property-hunt
systemctl restart property-hunt
sleep 3

systemctl is-active property-hunt
curl -fsS -o /dev/null "http://127.0.0.1:8501" && echo "Streamlit local check: OK"
curl -fsS -u "$BASIC_AUTH_USER:$BASIC_AUTH_PASS" -o /dev/null "http://127.0.0.1/" && echo "Nginx auth check: OK"
echo "Bootstrap complete."
