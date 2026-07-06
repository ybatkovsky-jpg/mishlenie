#!/bin/bash
# ============================================================
# 🧠 Mishlenie — скрипт деплоя на сервер (Ubuntu/Debian)
# Запуск: bash deploy.sh
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="/opt/mishlenie"
SERVICE_NAME="mishlenie"
REPO_URL="https://github.com/ybatkovsky-jpg/mishlenie.git"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════╗"
echo "║   🧠 Тренажер Мышления — Деплой         ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"

# --- 1. Системные зависимости ---
echo -e "${YELLOW}[1/8] Установка системных пакетов...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git redis-server postgresql postgresql-client

# --- Redis: ensure running ---
echo -e "${YELLOW}[1a/8] Настройка Redis...${NC}"
if ! systemctl is-active --quiet redis-server; then
    systemctl enable redis-server
    systemctl start redis-server
fi
echo -e "${GREEN}[.] Redis запущен${NC}"

# --- PostgreSQL: ensure running and create DB ---
echo -e "${YELLOW}[1b/8] Настройка PostgreSQL...${NC}"
if ! systemctl is-active --quiet postgresql; then
    systemctl enable postgresql
    systemctl start postgresql
fi
# Create user and database if not exist
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='mishlenie'\" | grep -q 1 || createuser mishlenie -P" || true
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='mishlenie'\" | grep -q 1 || createdb mishlenie -O mishlenie" || true
echo -e "${GREEN}[.] PostgreSQL запущен${NC}"

# --- 2. Клонирование / обновление проекта ---
if [ -d "$PROJECT_DIR" ]; then
    echo -e "${YELLOW}[2/8] Проект существует, обновляю...${NC}"
    cd "$PROJECT_DIR"
    git pull origin main
else
    echo -e "${YELLOW}[2/8] Клонирование проекта...${NC}"
    git clone "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# --- 3. Виртуальное окружение ---
echo -e "${YELLOW}[3/8] Настройка виртуального окружения...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# --- 4. Миграции БД ---
echo -e "${YELLOW}[4/8] Применение миграций Alembic...${NC}"
alembic upgrade head || echo -e "${YELLOW}[!] Миграции не применены (возможно БД уже актуальна)${NC}"

# --- 5. Проверка .env ---
if [ ! -f ".env" ]; then
    echo -e "${RED}[!] Файл .env не найден!${NC}"
    echo ""
    echo "Создайте .env файл со следующим содержимым:"
    echo "----------------------------------------"
    echo "TELEGRAM_BOT_TOKEN=ваш_токен"
    echo "DEEPSEEK_API_KEY=ваш_ключ"
    echo "DATABASE_URL=sqlite+aiosqlite:///mishlenie.db"
    echo "# Для продакшена (PostgreSQL):"
    echo "# DATABASE_URL=postgresql+asyncpg://mishlenie:пароль@localhost:5432/mishlenie"
    echo "REDIS_URL=redis://localhost:6379"
    echo "LOG_LEVEL=INFO"
    echo "----------------------------------------"
    echo ""
    read -p "Вставить содержимое сейчас? (y/n): " answer
    if [ "$answer" = "y" ]; then
        echo "Вставьте содержимое .env и нажмите Ctrl+D:"
        cat > .env
        echo -e "${GREEN}.env создан${NC}"
    else
        echo "Создайте .env вручную и перезапустите скрипт."
        exit 1
    fi
else
    echo -e "${GREEN}[.] .env найден${NC}"
fi

# --- 6. Systemd-сервис ---
echo -e "${YELLOW}[6/8] Настройка systemd-сервиса...${NC}"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Mishlenie Thinking Trainer Bot
After=network.target redis-server.service postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/venv/bin/python -m bot.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# --- 7. Перезапуск сервиса ---
echo -e "${YELLOW}[7/8] Запуск бота...${NC}"
systemctl restart "$SERVICE_NAME"
sleep 3

# --- 8. Проверка ---
echo -e "${YELLOW}[8/8] Проверка статуса...${NC}"
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "${GREEN}✅ Бот запущен и работает!${NC}"
    echo ""
    echo -e "Полезные команды:"
    echo -e "  статус:         ${CYAN}systemctl status ${SERVICE_NAME}${NC}"
    echo -e "  логи:           ${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}"
    echo -e "  перезапуск:     ${CYAN}systemctl restart ${SERVICE_NAME}${NC}"
    echo -e "  остановка:      ${CYAN}systemctl stop ${SERVICE_NAME}${NC}"
else
    echo -e "${RED}❌ Бот НЕ запустился. Проверьте логи:${NC}"
    echo -e "  ${CYAN}journalctl -u ${SERVICE_NAME} -n 30${NC}"
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   🎉 Деплой завершён!                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
