#!/usr/bin/env bash
# setup.sh — первичная установка StalZone Builder на Linux-сервере
# Запуск: bash setup.sh
set -euo pipefail

APP_DIR="/opt/stalzonebuilder"
SERVICE="stalzonebuilder"
PORT="${PORT:-8080}"
REPO_URL="https://github.com/serg-lebovski/stalzonebuilder.git"

echo "=== StalZone Builder — установка ==="

# Python 3
if ! command -v python3 &>/dev/null; then
  echo "Установка Python 3..."
  apt-get update -q && apt-get install -y -q python3 python3-pip git
fi

echo "Python: $(python3 --version)"

# Clone or update repo
if [ -d "$APP_DIR/.git" ]; then
  echo "Обновление репозитория..."
  git -C "$APP_DIR" pull --ff-only
else
  echo "Клонирование репозитория..."
  git clone "$REPO_URL" "$APP_DIR"
fi

# Systemd service
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=StalZone Builder Web App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
Environment="PORT=${PORT}"
Environment="SERVER_MODE=1"
ExecStart=/usr/bin/python3 -m app.main --server --port ${PORT}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

sleep 2
if systemctl is-active --quiet "$SERVICE"; then
  echo ""
  echo "✓ Сервис запущен: http://$(hostname -I | awk '{print $1}'):${PORT}"
else
  echo "✗ Ошибка запуска:"
  systemctl status "$SERVICE" --no-pager -l
  exit 1
fi
