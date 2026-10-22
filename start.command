#!/usr/bin/env bash
# Запуск панели двойным кликом (macOS открывает .command в Terminal)
cd "$(dirname "$0")"
./run.sh start
echo
read -r -p "Enter, чтобы закрыть окно... "
