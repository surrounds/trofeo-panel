"""Сбор системных метрик для рендера кадра.

snapshot() собирает всё нужное виджетам за один вызов, чтобы кадр
рисовался по согласованному срезу данных.
"""
import os
import socket
import time
import types

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


# Метрики с удалённой машины (Mac с flutter-приложением): если свежие,
# системные виджеты и шапка показывают их вместо метрик этой машины
REMOTE_TTL_SEC = 5.0
_remote = {"data": None, "ts": 0.0}


def set_remote(payload):
    """Принять снимок метрик от удалённого клиента."""
    if isinstance(payload, dict):
        _remote["data"] = payload
        _remote["ts"] = time.time()


def remote_info():
    """Для /api/status: кто шлёт метрики и насколько они свежие."""
    if _remote["data"] is None:
        return None
    age = time.time() - _remote["ts"]
    return {"source": _remote["data"].get("host"),
            "age_sec": round(age, 1),
            "active": age <= REMOTE_TTL_SEC}


def _ns(d, keys):
    d = d or {}
    return types.SimpleNamespace(**{k: d.get(k) or 0 for k in keys})


def _from_remote(r, disk_paths):
    """Снимок из удалённого JSON в формате локального snapshot()."""
    disks = {}
    rdisks = r.get("disks") or {}
    for p in disk_paths:
        d = rdisks.get(p)
        disks[p] = _ns(d, ("percent", "used", "total", "free")) if d else None
    load = r.get("load")
    net = r.get("net") or {}
    per_core = list(r.get("cpu_per_core") or [])
    return {
        "host": str(r.get("host") or "?").upper(),
        "uptime": float(r.get("uptime") or 0),
        "load": tuple(load) if isinstance(load, (list, tuple))
                and len(load) == 3 else None,
        "cpu": float(r.get("cpu") or 0),
        "cpu_per_core": per_core,
        "cores": int(r.get("cores") or len(per_core)),
        "cpu_temp": r.get("cpu_temp"),
        "mem": _ns(r.get("mem"), ("percent", "used", "total")),
        "swap": _ns(r.get("swap"), ("percent", "used", "total")),
        "disks": disks,
        "net": {"sent": float(net.get("sent") or 0),
                "recv": float(net.get("recv") or 0),
                "tot_s": int(net.get("tot_s") or 0),
                "tot_r": int(net.get("tot_r") or 0)},
    }


def snapshot(disk_paths=("/",)):
    """Срез всех метрик для одного кадра.

    Если удалённый клиент (Mac) прислал метрики за последние
    REMOTE_TTL_SEC - кадр показывает их, иначе метрики этой машины."""
    r = _remote["data"]
    if r is not None and time.time() - _remote["ts"] <= REMOTE_TTL_SEC:
        return _from_remote(r, disk_paths)
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
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    return {
        "host": socket.gethostname().split(".")[0].upper(),
        "uptime": time.time() - psutil.boot_time(),
        "load": load,
        "cpu": psutil.cpu_percent(interval=None),
        "cpu_per_core": per_core,
        "cores": len(per_core),
        "cpu_temp": cpu_temp(),
        "mem": psutil.virtual_memory(),
        "swap": psutil.swap_memory(),
        "disks": disks,
        "net": {"sent": sent, "recv": recv, "tot_s": tot_s, "tot_r": tot_r},
    }
