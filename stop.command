#!/usr/bin/env bash
# Остановка панели двойным кликом (macOS открывает .command в Terminal)
cd "$(dirname "$0")"
./run.sh stop
echo
read -r -p "Enter, чтобы закрыть окно... "
