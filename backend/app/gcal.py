"""События календаря по iCal-ссылке (Google Calendar: "Закрытый адрес
в формате iCal" в настройках календаря; подходит и Apple/Outlook).

Как и погода: get() отдаёт кэш мгновенно, скачивание и разбор ICS идут
в фоновом потоке. Повторяющиеся события разворачиваются через
dateutil.rrule с учётом EXDATE; арифметика идёт по aware-датам
исходного пояса, и каждое вхождение переводится в локальное время
отдельно (astimezone на вхождение) - серия держит время своего пояса
при смене DST, как в Google.

Паритет с flutter-версией: отменённые события (STATUS:CANCELLED)
пропускаются, перенесённые вхождения (RECURRENCE-ID) замещают
оригинальные в своей серии, Windows TZID из Outlook-инвайтов
маппятся в IANA.
"""
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rruleset, rrulestr

TTL_SEC = 300
RETRY_SEC = 60
HORIZON_DAYS = 60   # на сколько дней вперёд разворачивать события
MAX_EVENTS = 60

_lock = threading.Lock()
_cache = {}   # url -> {"data": [(date, "HH:MM"|None, текст)], "ts", "ts_fail", "loading"}

# Outlook-инвайты приносят Windows-имена поясов вместо IANA
_WINDOWS_TZ = {
    "Pacific Standard Time": "America/Los_Angeles",
    "Mountain Standard Time": "America/Denver",
    "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York",
    "US Eastern Standard Time": "America/New_York",
    "Atlantic Standard Time": "America/Halifax",
    "Central America Standard Time": "America/Guatemala",
    "SA Pacific Standard Time": "America/Bogota",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "E. Europe Standard Time": "Europe/Bucharest",
    "GTB Standard Time": "Europe/Bucharest",
    "FLE Standard Time": "Europe/Kyiv",
    "Turkey Standard Time": "Europe/Istanbul",
    "Israel Standard Time": "Asia/Jerusalem",
    "Egypt Standard Time": "Africa/Cairo",
    "South Africa Standard Time": "Africa/Johannesburg",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "Iran Standard Time": "Asia/Tehran",
    "Pakistan Standard Time": "Asia/Karachi",
    "India Standard Time": "Asia/Kolkata",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC": "UTC",
}


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "trofeo-panel"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _unfold(text):
    """Склеить перенесённые строки ICS (продолжение начинается с пробела)."""
    lines = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw.rstrip("\r"))
    return lines


def _zone(tzid):
    if not tzid:
        return None
    try:
        return ZoneInfo(tzid)
    except Exception:
        pass
    mapped = _WINDOWS_TZ.get(tzid)
    if mapped:
        try:
            return ZoneInfo(mapped)
        except Exception:
            pass
    return None  # неизвестный пояс: трактуем время как локальное


def _parse_dt(value, params):
    """DTSTART/EXDATE/RECURRENCE-ID -> (datetime | date, all_day)."""
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    else:
        tz = _zone(params.get("TZID"))
        if tz is not None:
            dt = dt.replace(tzinfo=tz)
    return dt, False


def _to_local(dt):
    """Aware/naive datetime -> локальное naive (конверсия на вхождение)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _collect_vevents(lines):
    """Первый проход: сырые VEVENT со свойствами и EXDATE."""
    vevents = []
    cur = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {"EXDATE": []}
        elif line == "END:VEVENT":
            if cur and "DTSTART" in cur:
                vevents.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.split(":", 1)
            name, *raw_params = key.split(";")
            params = dict(p.split("=", 1) for p in raw_params if "=" in p)
            if name in ("DTSTART", "SUMMARY", "RRULE", "UID", "STATUS",
                        "RECURRENCE-ID"):
                cur[name] = (params, value)
            elif name == "EXDATE":
                cur["EXDATE"].append((params, value))
    return vevents


def _parse_ics(text):
    """ICS -> [(date, "HH:MM" | None, текст)], развёрнуто и отсортировано."""
    vevents = _collect_vevents(_unfold(text))

    # Перенесённые вхождения (RECURRENCE-ID) замещают оригинальные:
    # их даты-времена становятся EXDATE для серии с тем же UID
    overrides = {}
    for ev in vevents:
        rid = ev.get("RECURRENCE-ID")
        uid = ev.get("UID", ({}, None))[1]
        if rid is None or uid is None:
            continue
        try:
            rid_dt, rid_all_day = _parse_dt(rid[1], rid[0])
        except Exception:
            continue
        overrides.setdefault(uid, []).append((rid_dt, rid_all_day))

    today = date.today()
    lo = datetime.combine(today, datetime.min.time())
    hi = lo + timedelta(days=HORIZON_DAYS)
    out = []
    for ev in vevents:
        if ev.get("STATUS", ({}, ""))[1] == "CANCELLED":
            continue
        params, value = ev["DTSTART"]
        summary = ev.get("SUMMARY", ({}, ""))[1]
        summary = summary.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
        try:
            start, all_day = _parse_dt(value, params)
        except Exception:
            continue

        # EXDATE события + даты, занятые перенесёнными вхождениями серии
        exdates = list(ev["EXDATE"])
        uid = ev.get("UID", ({}, None))[1]
        is_master = "RECURRENCE-ID" not in ev
        override_dts = overrides.get(uid, []) if (uid and is_master) else []

        if "RRULE" not in ev:
            occurrences = [start]
        else:
            dtstart = (datetime.combine(start, datetime.min.time())
                       if all_day else start)
            try:
                rs = rruleset()
                rs.rrule(rrulestr(ev["RRULE"][1], dtstart=dtstart))
                for ex_params, ex_value in exdates:
                    for chunk in ex_value.split(","):
                        ex_dt, ex_all_day = _parse_dt(chunk, ex_params)
                        rs.exdate(datetime.combine(ex_dt, datetime.min.time())
                                  if ex_all_day else ex_dt)
                for ov_dt, ov_all_day in override_dts:
                    rs.exdate(datetime.combine(ov_dt, datetime.min.time())
                              if ov_all_day else ov_dt)
                win_lo = lo.replace(tzinfo=dtstart.tzinfo) if dtstart.tzinfo else lo
                win_hi = hi.replace(tzinfo=dtstart.tzinfo) if dtstart.tzinfo else hi
                occurrences = rs.between(win_lo, win_hi, inc=True)
            except Exception:
                occurrences = [start]

        for occ in occurrences:
            if isinstance(occ, datetime):
                occ_local = _to_local(occ)
                d, t = occ_local.date(), (None if all_day
                                          else occ_local.strftime("%H:%M"))
            else:
                d, t = occ, None
            if today <= d <= today + timedelta(days=HORIZON_DAYS):
                out.append((d, t, summary))

    out.sort(key=lambda e: (e[0], e[1] or ""))
    return out[:MAX_EVENTS]


def _refresh(url):
    data = None
    try:
        data = _parse_ics(_fetch(url))
    except Exception as e:
        print(f"[gcal] {e}")
    with _lock:
        e = _cache.setdefault(url, {})
        if data is not None:
            e["data"] = data
            e["ts"] = time.time()
        else:
            e["ts_fail"] = time.time()
        e["loading"] = False


def get(url):
    """Кэшированные события (или None), без блокировки на сеть."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    now = time.time()
    with _lock:
        e = _cache.setdefault(url, {})
        stale = now - e.get("ts", 0) > TTL_SEC
        cooling = now - e.get("ts_fail", 0) < RETRY_SEC
        if stale and not e.get("loading") and not cooling:
            e["loading"] = True
            threading.Thread(target=_refresh, args=(url,),
                             daemon=True, name="gcal").start()
        return e.get("data")
