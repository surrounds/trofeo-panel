#!/usr/bin/env bash
# Управление демоном панели (API + веб-интерфейс + отправка кадров).
#
#   ./run.sh            запуск на переднем плане (Ctrl+C для остановки)
#   ./run.sh start      запуск в фоне (PID-файл + лог в backend/data/)
#   ./run.sh stop       остановить фоновый процесс
#   ./run.sh restart    перезапустить фоновый процесс
#   ./run.sh status     статус
#
# Переменные: PORT (по умолчанию 8888), PANEL_NO_USB=1 (dev без панели),
# TV_VID / TV_PID (нестандартные ID устройства).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
PIDFILE="$ROOT/backend/data/panel.pid"
LOGFILE="$ROOT/backend/data/panel.log"
PORT="${PORT:-8888}"

if [ ! -x backend/.venv/bin/uvicorn ]; then
    echo "Окружение не найдено, сначала выполните ./install.sh" >&2
    exit 1
fi

pid_alive() {
    [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

# IP в локальной сети (macOS: ipconfig, Linux: hostname -I), иначе localhost
lan_ip() {
    local ip=""
    if command -v ipconfig > /dev/null 2>&1; then
        local ifc
        ifc="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
        for i in "$ifc" en0 en1 en2; do
            [ -n "$i" ] && ip="$(ipconfig getifaddr "$i" 2>/dev/null)" && break
        done
    fi
    [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "${ip:-localhost}"
}
ADDR="$(lan_ip)"

do_start() {
    if pid_alive; then
        echo "Уже запущено (pid $(cat "$PIDFILE")): http://$ADDR:$PORT"
        exit 0
    fi
    mkdir -p backend/data
    (
        cd backend
        nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
            >> "$LOGFILE" 2>&1 &
        echo $! > "$PIDFILE"
    )
    sleep 2
    if pid_alive; then
        echo "Запущено в фоне (pid $(cat "$PIDFILE")): http://$ADDR:$PORT"
        echo "Лог: $LOGFILE"
    else
        rm -f "$PIDFILE"
        echo "Не запустилось, последние строки лога:" >&2
        tail -5 "$LOGFILE" >&2 || true
        exit 1
    fi
}

do_stop() {
    local stopped=0
    if pid_alive; then
        local pid
        pid="$(cat "$PIDFILE")"
        kill "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
        echo "Остановлено (pid $pid)"
        stopped=1
    fi
    rm -f "$PIDFILE"
    # Подстраховка: копии, запущенные без PID-файла (старым способом)
    if pkill -f "uvicorn app.main:app" 2>/dev/null; then
        echo "Остановлены копии без PID-файла"
        stopped=1
    fi
    [ "$stopped" = 1 ] || echo "Не запущено"
}

case "${1:-fg}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 1; do_start ;;
    status)
        if pid_alive; then
            echo "Работает (pid $(cat "$PIDFILE")): http://$ADDR:$PORT"
            curl -s --max-time 2 "localhost:$PORT/api/status" && echo || true
        elif pgrep -f "uvicorn app.main:app" > /dev/null 2>&1; then
            echo "Работает копия без PID-файла (pid $(pgrep -f 'uvicorn app.main:app' | head -1))"
        else
            echo "Не запущено"
        fi
        ;;
    fg)
        # Передний план: используется и systemd-сервисом
        cd backend
        exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
        ;;
    *)
        echo "Использование: ./run.sh [start|stop|restart|status]" >&2
        echo "Без аргументов: запуск на переднем плане (Ctrl+C для выхода)" >&2
        exit 1
        ;;
esac
