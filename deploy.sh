#!/bin/bash
# Deploy Race the Sun replacement server to a remote VPS
# Usage:
#   ./deploy.sh           — sync code, restart service
#   ./deploy.sh --setup   — first-time VPS setup (systemd unit, nginx hint)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$SCRIPT_DIR/deploy.conf"

if [ ! -f "$CONF" ]; then
  echo "Error: deploy.conf not found."
  echo "  cp deploy.conf.example deploy.conf   # then edit VPS_HOST"
  exit 1
fi

# shellcheck source=deploy.conf
source "$CONF"

if [ -z "${VPS_HOST:-}" ] || [ "$VPS_HOST" = "user@your-vps-hostname" ]; then
  echo "Error: Set VPS_HOST in deploy.conf first."
  exit 1
fi

echo "==> Deploying to $VPS_HOST:$VPS_APP_DIR"

# ---- Sync source code ----
echo "==> Syncing source code..."
rsync -avz --delete \
  --exclude='logs/' \
  --exclude='captured_requests/' \
  --exclude='deploy.conf' \
  --exclude='decompiled/' \
  --exclude='Assembly-CSharp.dll' \
  --exclude='game_capture*.pcap' \
  --exclude='__pycache__/' \
  "$SCRIPT_DIR/" \
  "$VPS_HOST:$VPS_APP_DIR/"

# ---- First-time setup ----
if [ "${1:-}" = "--setup" ]; then
  echo "==> Running first-time setup on VPS..."
  ssh "$VPS_HOST" bash -s "$VPS_APP_DIR" "$VPS_PORT" "${RESET_TIMEZONE:-America/Chicago}" << 'SETUP_EOF'
    set -euo pipefail
    APP_DIR="${1/#\~/$HOME}"
    VPS_PORT="$2"
    RESET_TIMEZONE="$3"

    echo "--- Creating directories ---"
    mkdir -p "$APP_DIR/logs"

    echo "--- Verifying Python 3 ---"
    python3 --version

    echo "--- Installing systemd user service ---"
    mkdir -p "$HOME/.config/systemd/user"

    cat > "$HOME/.config/systemd/user/racethesun.service" << EOF
[Unit]
Description=Race the Sun — replacement game server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PORT=$VPS_PORT
Environment=LOG_DIR=$APP_DIR/logs
Environment=NEWS_FILE=$APP_DIR/news.json
Environment=RESET_TIMEZONE=$RESET_TIMEZONE
ExecStart=/usr/bin/python3 $APP_DIR/mock_server.py
StandardOutput=journal
StandardError=journal
Restart=on-failure
RestartSec=5

# Resource limits
MemoryMax=128M
CPUQuota=25%

# Sandboxing
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=tmpfs
BindPaths=$APP_DIR
ReadWritePaths=$APP_DIR/logs

[Install]
WantedBy=default.target
EOF

    echo "--- Enabling lingering (services survive logout) ---"
    loginctl enable-linger "$(whoami)" 2>/dev/null || true

    echo "--- Enabling and starting service ---"
    systemctl --user daemon-reload
    systemctl --user enable --now racethesun.service

    echo ""
    echo "--- Setup complete ---"
    echo "Server running on port $VPS_PORT"
    echo ""
    echo "To expose via nginx, install the config:"
    echo "  sudo cp $APP_DIR/nginx-racethesun.conf /etc/nginx/sites-available/racethesun"
    echo "  sudo ln -s /etc/nginx/sites-available/racethesun /etc/nginx/sites-enabled/"
    echo "  sudo nginx -t && sudo systemctl reload nginx"
    echo ""
    echo "Then point DNS for tech.flippfly.com and monkeytech.flippfly.com to this VPS."
    echo ""
    systemctl --user status racethesun.service --no-pager || true
SETUP_EOF

# ---- Regular deploy ----
else
  echo "==> Restarting service on VPS..."
  ssh "$VPS_HOST" bash -s "$VPS_APP_DIR" << 'DEPLOY_EOF'
    set -euo pipefail
    APP_DIR="${1/#\~/$HOME}"

    systemctl --user restart racethesun.service

    echo "--- Deploy complete ---"
    systemctl --user status racethesun.service --no-pager || true
DEPLOY_EOF
fi

echo "Done!"
