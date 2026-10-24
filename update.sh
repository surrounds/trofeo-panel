#!/usr/bin/env bash
# Обновление установки из git: pull + зависимости + перезапуск.
# Конфиг панели (backend/data/) в git не входит и переживает обновление.
set -euo pipefail
cd "$(dirname "$0")"

echo "== git pull"
git pull --ff-only
git submodule update --init

echo "== Зависимости"
./install.sh

# Перезапуск: systemd-сервис, если установлен, иначе фоновый run.sh
if systemctl list-unit-files trofeo-panel.service >/dev/null 2>&1 \
   && systemctl is-enabled trofeo-panel >/dev/null 2>&1; then
    echo "== Перезапуск systemd-сервиса (нужен пароль sudo)"
    sudo systemctl restart trofeo-panel
    systemctl --no-pager -l status trofeo-panel | head -5
else
    echo "== Перезапуск демона"
    ./run.sh restart
fi
echo "Готово."
