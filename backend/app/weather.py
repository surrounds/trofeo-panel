"""Погода через Open-Meteo (без API-ключа).

Рендер кадра идёт раз в секунду и не должен ждать сеть, поэтому
get() всегда отдаёт кэш мгновенно, а обновление (раз в 10 минут)
крутится в отдельном фоновом потоке. Геокодинг города кэшируется
навсегда, после неудачи следующая попытка не раньше чем через минуту.

Описание погоды хранится кодом WMO и переводится при рендере
(l10n.wmo_desc), кэш ключуется языком: геокодер возвращает
локализованное имя города.
"""
import json
import threading
import time
import urllib.parse
import urllib.request

TTL_SEC = 600
RETRY_SEC = 60

_lock = threading.Lock()
_cache = {}   # "lang|место" -> {"data":, "ts":, "ts_fail":, "loading":}
_geo = {}     # "lang|место" -> (lat, lon, имя из справочника)


def _fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "trofeo-panel"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _geocode(place, lang, key):
    if key in _geo:
        return _geo[key]
    d = _fetch_json(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode({"name": place, "count": 1,
                                  "language": lang}))
    res = (d.get("results") or [None])[0]
    _geo[key] = ((res["latitude"], res["longitude"], res["name"])
                 if res else None)
    return _geo[key]


def _refresh(place, lang, key):
    data = None
    try:
        loc = _geocode(place, lang, key)
        if loc is not None:
            lat, lon, name = loc
            d = _fetch_json(
                "https://api.open-meteo.com/v1/forecast?"
                + urllib.parse.urlencode({
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,"
                               "apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_min,temperature_2m_max",
                    "forecast_days": 1, "timezone": "auto",
                    "wind_speed_unit": "ms"}))
            cur = d["current"]
            data = {
                "name": name,
                "temp": cur["temperature_2m"],
                "feels": cur["apparent_temperature"],
                "hum": cur["relative_humidity_2m"],
                "wind": cur["wind_speed_10m"],
                "code": int(cur["weather_code"]),
                "tmin": d["daily"]["temperature_2m_min"][0],
                "tmax": d["daily"]["temperature_2m_max"][0],
            }
        else:
            data = {"not_found": place}
    except Exception as e:
        print(f"[weather] {place}: {e}")
    with _lock:
        e = _cache.setdefault(key, {})
        if data is not None:
            e["data"] = data
            e["ts"] = time.time()
        else:
            e["ts_fail"] = time.time()
        e["loading"] = False


def get(place, lang="en"):
    """Кэшированные данные (или None), без блокировки на сеть."""
    place = (place or "").strip()
    if not place:
        return None
    key = f"{lang}|{place}"
    now = time.time()
    with _lock:
        e = _cache.setdefault(key, {})
        stale = now - e.get("ts", 0) > TTL_SEC
        cooling = now - e.get("ts_fail", 0) < RETRY_SEC
        if stale and not e.get("loading") and not cooling:
            e["loading"] = True
            threading.Thread(target=_refresh, args=(place, lang, key),
                             daemon=True, name="weather").start()
        return e.get("data")
