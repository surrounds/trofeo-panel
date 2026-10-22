"""Сбор системных метрик для рендера кадра.

snapshot() собирает всё нужное виджетам за один вызов, чтобы кадр
рисовался по согласованному срезу данных.
"""
import os
import socket
import time

import psutil

_last_net = {"t": time.time(), "s": 0, "r": 0}


def _net_rates():
    now = time.time()
    n = psutil.net_io_counters()
    dt = max(now - _last_net["t"], 0.001)
    s = (n.bytes_sent - _last_net["s"]) / dt
    r = (n.bytes_recv - _last_net["r"]) / dt
    _last_net.update(t=now, s=n.bytes_sent, r=n.bytes_recv)
    return max(0, s), max(0, r), n.bytes_sent, n.bytes_recv


def cpu_temp():
    """Температура пакета CPU, если ядро её отдаёт."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    for key in ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz"):
        for entry in temps.get(key, []):
            label = (entry.label or "").lower()
            if key != "acpitz" and label and not any(
                    t in label for t in ("package", "tctl", "tdie", "composite")):
                continue
            if entry.current:
                return entry.current
    for entries in temps.values():
        for entry in entries:
            if entry.current:
                return entry.current
    return None


# Первый вызов cpu_percent всегда отдаёт 0, прогреваем счётчики при импорте
psutil.cpu_percent(interval=None)
psutil.cpu_percent(percpu=True, interval=None)
_net_rates()


def snapshot(disk_paths=("/",)):
    """Срез всех метрик для одного кадра."""
    sent, recv, tot_s, tot_r = _net_rates()
    disks = {}
    for path in disk_paths:
        try:
            disks[path] = psutil.disk_usage(path)
        except Exception:
            disks[path] = None
    try:
        load = os.getloadavg()
    except OSError:
        load = None
    return {
        "host": socket.gethostname().split(".")[0].upper(),
        "uptime": time.time() - psutil.boot_time(),
        "load": load,
        "cpu": psutil.cpu_percent(interval=None),
        "cpu_per_core": psutil.cpu_percent(percpu=True, interval=None),
        "cpu_temp": cpu_temp(),
        "mem": psutil.virtual_memory(),
        "swap": psutil.swap_memory(),
        "disks": disks,
        "net": {"sent": sent, "recv": recv, "tot_s": tot_s, "tot_r": tot_r},
    }
