#!/usr/bin/env bash
# setup.sh — установка StalZone Builder на Linux-сервере
# Использование: bash setup.sh [--port PORT]
set -euo pipefail

APP_DIR="/opt/stalzonebuilder"
SERVICE="stalzonebuilder"
PORT="${PORT:-8080}"
REPO_URL="https://github.com/serg-lebovski/stalzonebuilder.git"
DB_NAME="stalzonebuilder"
DB_USER="szbuilder"
DB_PASS="SzBuilder2025!"

echo "╔══════════════════════════════════════╗"
echo "║    StalZone Builder — установка      ║"
echo "╚══════════════════════════════════════╝"

# ── Зависимости ─────────────────────────────────────────────────
echo "[1/6] Установка зависимостей..."
apt-get update -q
apt-get install -y -q python3 python3-pip git postgresql postgresql-contrib

# ── Venv + psycopg2 ─────────────────────────────────────────────
echo "[2/6] Создание виртуального окружения..."
apt-get install -y -q python3-venv
python3 -m venv /opt/szbuilder-venv
/opt/szbuilder-venv/bin/pip install psycopg2-binary -q
PYTHON_BIN="/opt/szbuilder-venv/bin/python3"

# ── PostgreSQL ──────────────────────────────────────────────────
echo "[3/6] Настройка PostgreSQL..."
systemctl start postgresql
systemctl enable postgresql

# Создать базу и пользователя, если не существуют
su -c "psql -tc \"SELECT 1 FROM pg_user WHERE usename='${DB_USER}'\" | grep -q 1 || \
       psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}'\"" postgres

su -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\" | grep -q 1 || \
       psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}\"" postgres

DB_URL="postgresql://${DB_USER}:${DB_PASS}@localhost/${DB_NAME}"

# ── Репозиторий ─────────────────────────────────────────────────
echo "[4/6] Обновление кода..."
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" reset --hard origin/main
else
  git clone "$REPO_URL" "$APP_DIR"
fi

# ── Systemd-сервис ──────────────────────────────────────────────
echo "[5/6] Настройка systemd..."
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=StalZone Builder Web App
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
Environment="PORT=${PORT}"
Environment="SERVER_MODE=1"
Environment="DB_URL=${DB_URL}"
ExecStart=/opt/szbuilder-venv/bin/python3 -m app.main --server --port ${PORT}
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

# ── Firewall ─────────────────────────────────────────────────────
echo "[6/6] Открытие порта ${PORT}..."
if command -v ufw &>/dev/null; then
  ufw allow "${PORT}/tcp" || true
fi

sleep 3
echo ""
if systemctl is-active --quiet "$SERVICE"; then
  IP=$(hostname -I | awk '{print $1}')
  echo "✓ Сервис запущен!"
  echo "  URL:       http://${IP}:${PORT}"
  echo "  Лог:       journalctl -u ${SERVICE} -f"
  echo "  Перезапуск: systemctl restart ${SERVICE}"
  echo ""
  echo "  Администратор: admin / 12345678 (смените пароль после входа!)"
else
  echo "✗ Ошибка запуска:"
  systemctl status "$SERVICE" --no-pager -l
  exit 1
fi
