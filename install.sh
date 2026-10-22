#!/usr/bin/env bash
# Установка: python-venv с зависимостями + сборка фронтенда (если есть npm).
# Повторный запуск безопасен. Затем: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "== Python-окружение =="
if [ ! -x backend/.venv/bin/python ]; then
    python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install -q --upgrade -r backend/requirements.txt
# Библиотека панели (протокол + USB) живёт отдельным пакетом trofeo-lcd
# (git-сабмодуль; при клоне без --recurse-submodules подтягиваем сами)
if [ ! -f trofeo-lcd/pyproject.toml ] && command -v git >/dev/null 2>&1; then
    git submodule update --init
fi
backend/.venv/bin/pip install -q -e trofeo-lcd
echo "   ok: $(backend/.venv/bin/python --version)"

echo "== Фронтенд =="
if command -v npm >/dev/null 2>&1; then
    (cd frontend && npm install --silent && npm run build --silent)
    echo "   ok: собран frontend/dist"
elif [ -d frontend/dist ]; then
    echo "   npm не найден, используется готовая сборка frontend/dist"
else
    echo "   [warn] npm не найден и frontend/dist отсутствует:"
    echo "          API будет работать, веб-интерфейс - нет"
fi

echo
echo "Готово. Команды:"
echo "  ./run.sh start        запуск в фоне"
echo "  ./run.sh stop         остановка"
echo "  ./run.sh status       статус"
echo "  ./run.sh              передний план (Ctrl+C для выхода)"
echo "  PANEL_NO_USB=1 ./run.sh start   dev-режим без панели"
echo "  PORT=8080 ./run.sh start        другой порт (по умолчанию 8888)"
if [ "$(uname)" = "Linux" ]; then
    echo
    echo "Linux: для доступа к USB без root установите udev-правило:"
    echo "  sudo cp deploy/99-trofeo.rules /etc/udev/rules.d/"
    echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
    echo "Автозапуск как сервис: см. deploy/trofeo-panel.service"
fi
