"""Виджеты панелей. Каждый рисует себя в прямоугольнике (x, y, w, h).

Сигнатура: draw_<type>(img, d, x, y, w, h, theme, settings, m), где
m - срез метрик из metrics.snapshot(). Макеты перенесены из monitor.py
и параметризованы по ширине панели.
"""
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image

from . import gcal, l10n, weather
from .config import IMAGES_DIR
from .fonts import F_HUGE, F_BIG, F_MED, F_REG, F_SM, F_TINY, F_CLOCK
from .l10n import tr

PAD = 22


def color_for(theme, p):
    return (theme.crit if p >= 85 else theme.warn if p >= 65
            else theme.accent if p >= 40 else theme.good)


def fmt_bytes(n):
    n = float(n)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def bar(d, theme, x, y, w, h, pct, color=None):
    pct = max(0.0, min(100.0, float(pct)))
    color = color or color_for(theme, pct)
    r = h // 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=theme.track)
    fw = int(w * pct / 100)
    if fw > h:
        d.rounded_rectangle([x, y, x + fw, y + h], radius=r, fill=color)
    elif fw > 0:
        d.ellipse([x, y, x + h, y + h], fill=color)


def text_right(d, x_right, y, text, font, fill):
    d.text((x_right - d.textlength(text, font=font), y), text, font=font, fill=fill)


def _draw_no_data(d, x, y, theme):
    d.text((x + PAD, y + 34), tr("No data", "Немає даних"),
           font=F_BIG, fill=theme.dim)


def draw_cpu(img, d, x, y, w, h, theme, settings, m):
    if m.get("no_data"):
        return _draw_no_data(d, x, y, theme)
    cpu = m["cpu"]
    per = m["cpu_per_core"]
    d.text((x + PAD, y + 34), f"{cpu:.1f}%", font=F_HUGE,
           fill=color_for(theme, cpu))

    sub = f"{m.get('cores') or len(per)} cores"
    if settings.get("show_temp", True) and m["cpu_temp"] is not None:
        sub += f"   {m['cpu_temp']:.0f}°C"
    d.text((x + PAD, y + 132), sub, font=F_SM, fill=theme.dim)

    if not settings.get("show_cores", True):
        return
    cores = per[:16]
    rows = min(8, max(1, (len(cores) + 1) // 2)) if len(cores) > 8 else len(cores)
    col_w = (w - 2 * PAD - 12) // 2
    top = y + 166
    pitch = 15
    for i, c in enumerate(cores):
        cx = x + PAD + (0 if i < rows else col_w + 12)
        cy = top + (i % rows) * pitch
        if cy + 8 > y + h - 12:
            break
        d.text((cx, cy - 3), f"{i:>2}", font=F_TINY, fill=theme.dim)
        bar(d, theme, cx + 24, cy, col_w - 30, 8, c)


def draw_memory(img, d, x, y, w, h, theme, settings, m):
    if m.get("no_data"):
        return _draw_no_data(d, x, y, theme)
    mem = m["mem"]
    d.text((x + PAD, y + 34), f"{mem.percent:.1f}%",
           font=F_HUGE, fill=color_for(theme, mem.percent))
    d.text((x + PAD, y + 132),
           f"{fmt_bytes(mem.used)} / {fmt_bytes(mem.total)}",
           font=F_REG, fill=theme.fg)
    bar(d, theme, x + PAD, y + 176, w - 2 * PAD, 18, mem.percent)

    if not settings.get("show_swap", True):
        return
    swap = m["swap"]
    d.text((x + PAD, y + 220), "SWAP", font=F_SM, fill=theme.dim)
    text_right(d, x + w - PAD, y + 220,
               f"{fmt_bytes(swap.used)} / {fmt_bytes(swap.total)}",
               F_SM, theme.dim)
    bar(d, theme, x + PAD, y + 252, w - 2 * PAD, 10,
        swap.percent, theme.warn if swap.percent > 10 else theme.dim)


def draw_disk(img, d, x, y, w, h, theme, settings, m):
    if m.get("no_data"):
        return _draw_no_data(d, x, y, theme)
    path = settings.get("path", "/")
    disk = m["disks"].get(path)
    if disk is None:
        d.text((x + PAD, y + 34), "n/a", font=F_HUGE, fill=theme.dim)
        return
    d.text((x + PAD, y + 34), f"{disk.percent:.1f}%",
           font=F_HUGE, fill=color_for(theme, disk.percent))
    d.text((x + PAD, y + 132),
           f"{fmt_bytes(disk.used)} / {fmt_bytes(disk.total)}",
           font=F_REG, fill=theme.fg)
    bar(d, theme, x + PAD, y + 176, w - 2 * PAD, 18, disk.percent)

    d.text((x + PAD, y + 218), "FREE", font=F_SM, fill=theme.dim)
    d.text((x + PAD, y + 242), fmt_bytes(disk.free), font=F_BIG, fill=theme.good)


def draw_network(img, d, x, y, w, h, theme, settings, m):
    if m.get("no_data"):
        return _draw_no_data(d, x, y, theme)
    net = m["net"]
    d.text((x + PAD, y + 46), "↓", font=F_BIG, fill=theme.good)
    d.text((x + PAD + 44, y + 54), f"{fmt_bytes(net['recv'])}/s",
           font=F_MED, fill=theme.fg)

    d.text((x + PAD, y + 122), "↑", font=F_BIG, fill=theme.accent)
    d.text((x + PAD + 44, y + 130), f"{fmt_bytes(net['sent'])}/s",
           font=F_MED, fill=theme.fg)

    d.line([x + PAD, y + 200, x + w - PAD, y + 200], fill=theme.border, width=2)
    d.text((x + PAD, y + 216), "total", font=F_SM, fill=theme.dim)
    d.text((x + PAD, y + 244), f"↓ {fmt_bytes(net['tot_r'])}",
           font=F_REG, fill=theme.dim)
    text_right(d, x + w - PAD, y + 244, f"↑ {fmt_bytes(net['tot_s'])}",
               F_REG, theme.dim)


def draw_clock(img, d, x, y, w, h, theme, settings, m):
    fmt = "%H:%M:%S" if settings.get("show_seconds", True) else "%H:%M"
    text = time.strftime(fmt)
    tw = d.textlength(text, font=F_CLOCK)
    d.text((x + (w - tw) // 2, y + h // 2 - 75), text,
           font=F_CLOCK, fill=theme.fg)
    if settings.get("show_date", True):
        today = date.today()
        ds = f"{today.day} {l10n.months_gen()[today.month - 1]} {today.year}"
        dw = d.textlength(ds, font=F_MED)
        d.text((x + (w - dw) // 2, y + h // 2 + 40), ds,
               font=F_MED, fill=theme.dim)
        wd = l10n.weekdays()[today.weekday()]
        ww = d.textlength(wd, font=F_MED)
        d.text((x + (w - ww) // 2, y + h // 2 + 82), wd,
               font=F_MED, fill=theme.accent)


def draw_image(img, d, x, y, w, h, theme, settings, m):
    name = settings.get("name")
    if not name:
        d.text((x + PAD, y + 40),
               tr("image: no file selected", "image: файл не вибрано"),
               font=F_SM, fill=theme.dim)
        return
    path = (IMAGES_DIR / name).resolve()
    if IMAGES_DIR.resolve() not in path.parents or not path.exists():
        d.text((x + PAD, y + 40),
               f"{tr('image: missing file', 'image: немає файлу')} {name}",
               font=F_SM, fill=theme.warn)
        return
    try:
        src = Image.open(path).convert("RGB")
    except Exception:
        d.text((x + PAD, y + 40),
               f"{tr('image: cannot read', 'image: не читається')} {name}",
               font=F_SM, fill=theme.warn)
        return
    fit = settings.get("fit", "cover")
    sw, sh = src.size
    scale = (max if fit == "cover" else min)(w / sw, h / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    src = src.resize((nw, nh), Image.LANCZOS)
    if fit == "cover":
        left = (nw - w) // 2
        top = (nh - h) // 2
        src = src.crop((left, top, left + w, top + h))
        img.paste(src, (x, y))
    else:
        img.paste(src, (x + (w - nw) // 2, y + (h - nh) // 2))


def _parse_events(text):
    """Строки 'ГГГГ-ММ-ДД текст' -> [(date, None, текст)], битые пропускаем."""
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        try:
            day = date.fromisoformat(parts[0])
        except ValueError:
            continue
        events.append((day, None, parts[1] if len(parts) > 1 else ""))
    return events


def draw_calendar(img, d, x, y, w, h, theme, settings, m):
    today = date.today()
    events = _parse_events(settings.get("events", ""))
    ics_url = (settings.get("ics_url") or "").strip()
    ics_loading = False
    if ics_url:
        ics_events = gcal.get(ics_url)
        if ics_events is None:
            ics_loading = True
        else:
            events = events + list(ics_events)
    events.sort(key=lambda e: (e[0], e[1] or ""))
    # Skip today: показываем начиная с завтрашнего дня
    from_day = today + timedelta(days=1) if settings.get("skip_today") else today
    upcoming = [(ev, t, title) for ev, t, title in events if ev >= from_day]

    # Только события: две строки на каждое (дата/время, название),
    # между событиями разделительная линия
    ey = y + 50
    avail = w - 2 * PAD
    shown = 0
    # Дата/время не сегодняшних событий: приглушённый цвет, но светлее dim
    label_fill = tuple(min(255, c + 45) for c in theme.dim)
    for ev, ev_time, title in upcoming:
        if ey + 62 > y + h - 12:
            break
        if shown:
            d.line([x + PAD, ey - 11, x + w - PAD, ey - 11],
                   fill=theme.border, width=1)
        if ev == today:
            label = tr("today", "сьогодні")
        elif (ev - today).days == 1:
            label = tr("tomorrow", "завтра")
        else:
            label = ev.strftime("%d.%m")
        if ev_time:
            label += f"  {ev_time}"
        d.text((x + PAD, ey), label, font=F_REG,
               fill=theme.accent if ev == today else label_fill)
        while title and d.textlength(title, font=F_REG) > avail:
            title = title[:-1]
        d.text((x + PAD, ey + 32), title, font=F_REG, fill=theme.fg)
        ey += 78
        shown += 1
    if not shown:
        d.text((x + PAD, ey),
               tr("loading calendar...", "завантаження календаря...")
               if ics_loading else tr("no events", "немає подій"),
               font=F_SM, fill=theme.dim)


# Все часовые пояса с опорным городом (подписи EN и UK).
# Российских городов нет намеренно: GMT+2 - Киев, GMT+3 - Стамбул/Эр-Рияд.
ZONE_CATALOG = [
    ("Pacific/Pago_Pago", "Pago Pago", "Паго-Паго", "GMT-11"),
    ("Pacific/Honolulu", "Honolulu", "Гонолулу", "GMT-10"),
    ("America/Anchorage", "Anchorage", "Анкоридж", "GMT-9"),
    ("America/Los_Angeles", "Los Angeles", "Лос-Анджелес", "GMT-8"),
    ("America/Denver", "Denver", "Денвер", "GMT-7"),
    ("America/Mexico_City", "Mexico City", "Мехіко", "GMT-6"),
    ("America/Chicago", "Chicago", "Чикаго", "GMT-6"),
    ("America/New_York", "New York", "Нью-Йорк", "GMT-5"),
    ("America/Caracas", "Caracas", "Каракас", "GMT-4"),
    ("America/Santiago", "Santiago", "Сантьяго", "GMT-4"),
    ("America/Argentina/Buenos_Aires", "Buenos Aires", "Буенос-Айрес", "GMT-3"),
    ("America/Sao_Paulo", "Sao Paulo", "Сан-Паулу", "GMT-3"),
    ("Atlantic/South_Georgia", "South Georgia", "Пд. Джорджія", "GMT-2"),
    ("Atlantic/Azores", "Azores", "Азорські о-ви", "GMT-1"),
    ("Europe/London", "London", "Лондон", "GMT+0"),
    ("Europe/Berlin", "Berlin", "Берлін", "GMT+1"),
    ("Europe/Paris", "Paris", "Париж", "GMT+1"),
    ("Europe/Kyiv", "Kyiv", "Київ", "GMT+2"),
    ("Africa/Cairo", "Cairo", "Каїр", "GMT+2"),
    ("Europe/Istanbul", "Istanbul", "Стамбул", "GMT+3"),
    ("Asia/Riyadh", "Riyadh", "Ер-Ріяд", "GMT+3"),
    ("Asia/Tehran", "Tehran", "Тегеран", "GMT+3:30"),
    ("Asia/Dubai", "Dubai", "Дубай", "GMT+4"),
    ("Asia/Baku", "Baku", "Баку", "GMT+4"),
    ("Asia/Kabul", "Kabul", "Кабул", "GMT+4:30"),
    ("Asia/Tashkent", "Tashkent", "Ташкент", "GMT+5"),
    ("Asia/Karachi", "Karachi", "Карачі", "GMT+5"),
    ("Asia/Kolkata", "Delhi", "Делі", "GMT+5:30"),
    ("Asia/Kathmandu", "Kathmandu", "Катманду", "GMT+5:45"),
    ("Asia/Dhaka", "Dhaka", "Дакка", "GMT+6"),
    ("Asia/Yangon", "Yangon", "Янгон", "GMT+6:30"),
    ("Asia/Bangkok", "Bangkok", "Бангкок", "GMT+7"),
    ("Asia/Shanghai", "Beijing", "Пекін", "GMT+8"),
    ("Asia/Singapore", "Singapore", "Сінгапур", "GMT+8"),
    ("Asia/Tokyo", "Tokyo", "Токіо", "GMT+9"),
    ("Australia/Darwin", "Darwin", "Дарвін", "GMT+9:30"),
    ("Australia/Sydney", "Sydney", "Сідней", "GMT+10"),
    ("Pacific/Guadalcanal", "Honiara", "Хоніара", "GMT+11"),
    ("Pacific/Auckland", "Auckland", "Окленд", "GMT+12"),
    ("Pacific/Tongatapu", "Nuku'alofa", "Нукуалофа", "GMT+13"),
    ("Pacific/Kiritimati", "Kiritimati", "Кірітіматі", "GMT+14"),
]
ZONE_MAP_EN = {tz: en for tz, en, _, _ in ZONE_CATALOG}
ZONE_MAP_UK = {tz: uk for tz, _, uk, _ in ZONE_CATALOG}


def zone_label(name):
    zmap = ZONE_MAP_UK if l10n.is_uk() else ZONE_MAP_EN
    return zmap.get(name, str(name).split("/")[-1].replace("_", " "))


MAX_ZONES = 6


def _tz(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def _parse_zones(value):
    """Настройка zones -> [(подпись, tz | None)].

    Новый формат: список имён IANA из каталога. Старый (совместимость):
    многострочный текст 'Area/City|Подпись'."""
    zones = []
    if isinstance(value, list):
        for name in value:
            zones.append((zone_label(name), _tz(name)))
    else:
        for line in (value or "").splitlines():
            line = line.strip()
            if not line:
                continue
            name, _, label = line.partition("|")
            name = name.strip()
            zones.append((label.strip() or name.split("/")[-1].replace("_", " "),
                          _tz(name)))
    return zones[:MAX_ZONES]


def draw_worldclock(img, d, x, y, w, h, theme, settings, m):
    zones = _parse_zones(settings.get("zones", ""))
    if not zones:
        d.text((x + PAD, y + 40),
               tr("no cities selected", "міста не вибрано"),
               font=F_SM, fill=theme.dim)
        return
    now_local = datetime.now().astimezone()
    pitch = min(56, max(40, (h - 60) // len(zones)))
    ey = y + 44
    for label, tz in zones:
        if tz is None:
            d.text((x + PAD, ey + 8),
                   f"{label}: {tr('invalid timezone', 'невірний пояс')}",
                   font=F_SM, fill=theme.warn)
            ey += pitch
            continue
        now = now_local.astimezone(tz)
        d.text((x + PAD, ey + 6), label, font=F_MED, fill=theme.fg)
        # Смещение дня относительно локальной даты: вчера/завтра
        dd = (now.date() - now_local.date()).days
        suffix = (tr(" +1d", " +1д") if dd > 0
                  else (tr(" -1d", " -1д") if dd < 0 else ""))
        text_right(d, x + w - PAD, ey, now.strftime("%H:%M") + suffix,
                   F_BIG, theme.accent)
        ey += pitch


def draw_weather(img, d, x, y, w, h, theme, settings, m):
    place = settings.get("place", "")
    if not place:
        d.text((x + PAD, y + 40), tr("city not set", "місто не задано"),
               font=F_SM, fill=theme.dim)
        return
    data = weather.get(place, "uk" if l10n.is_uk() else "en")
    if data is None:
        d.text((x + PAD, y + 40),
               f"{place}: {tr('loading...', 'завантаження...')}",
               font=F_SM, fill=theme.dim)
        return
    if "not_found" in data:
        d.text((x + PAD, y + 40),
               f"{tr('place not found:', 'місто не знайдено:')} {place}",
               font=F_SM, fill=theme.warn)
        return
    d.text((x + PAD, y + 34), f"{data['temp']:+.0f}°", font=F_HUGE, fill=theme.fg)
    d.text((x + PAD, y + 132), l10n.wmo_desc(data["code"]),
           font=F_REG, fill=theme.accent)
    d.text((x + PAD, y + 176),
           f"{tr('feels like', 'відчувається')} {data['feels']:+.0f}°",
           font=F_SM, fill=theme.dim)
    d.text((x + PAD, y + 204),
           tr(f"wind {data['wind']:.0f} m/s   humidity {data['hum']:.0f}%",
              f"вітер {data['wind']:.0f} м/с   вологість {data['hum']:.0f}%"),
           font=F_SM, fill=theme.dim)
    d.text((x + PAD, y + 244),
           f"{tr('day', 'вдень')} {data['tmin']:+.0f}°..{data['tmax']:+.0f}°",
           font=F_REG, fill=theme.fg)
    text_right(d, x + w - PAD, y + 12, data["name"], F_SM, theme.dim)


WIDGETS = {
    "cpu": draw_cpu,
    "memory": draw_memory,
    "disk": draw_disk,
    "network": draw_network,
    "clock": draw_clock,
    "image": draw_image,
    "calendar": draw_calendar,
    "worldclock": draw_worldclock,
    "weather": draw_weather,
}

# Каталог для фронтенда: типы виджетов и схема их настроек.
# Подписи в двух языках: title (EN) + title_uk, фронтенд выбирает сам.
CATALOG = [
    {"type": "cpu", "title": "CPU", "title_uk": "Процесор",
     "settings": {"show_cores": {"type": "bool", "default": True,
                                 "title": "Show cores",
                                 "title_uk": "Показувати ядра"},
                  "show_temp": {"type": "bool", "default": True,
                                "title": "Show temperature",
                                "title_uk": "Показувати температуру"}}},
    {"type": "memory", "title": "Memory", "title_uk": "Пам'ять",
     "settings": {"show_swap": {"type": "bool", "default": True,
                                "title": "Show swap",
                                "title_uk": "Показувати swap"}}},
    {"type": "disk", "title": "Disk", "title_uk": "Диск",
     "settings": {"path": {"type": "str", "default": "/",
                           "title": "Mount point",
                           "title_uk": "Точка монтування"}}},
    {"type": "network", "title": "Network", "title_uk": "Мережа",
     "settings": {}},
    {"type": "clock", "title": "Clock", "title_uk": "Годинник",
     "settings": {"show_seconds": {"type": "bool", "default": True,
                                   "title": "Seconds",
                                   "title_uk": "Секунди"},
                  "show_date": {"type": "bool", "default": True,
                                "title": "Date", "title_uk": "Дата"}}},
    {"type": "image", "title": "Image", "title_uk": "Зображення",
     "settings": {"name": {"type": "image", "default": None,
                           "title": "Uploaded file",
                           "title_uk": "Завантажений файл"},
                  "fit": {"type": "enum", "values": ["cover", "contain"],
                          "default": "cover", "title": "Fit",
                          "title_uk": "Масштабування"}}},
    {"type": "calendar", "title": "Calendar", "title_uk": "Календар",
     "settings": {"ics_url": {"type": "str", "default": "",
                              "title": "Google Calendar: secret iCal address",
                              "title_uk": "Google Calendar: секретна адреса iCal"},
                  "events": {"type": "text", "default": "",
                             "title": "Custom events: YYYY-MM-DD text, one per line",
                             "title_uk": "Власні події: РРРР-ММ-ДД текст, по рядку"},
                  "skip_today": {"type": "bool", "default": False,
                                 "title": "Skip today (start from tomorrow)",
                                 "title_uk": "Пропускати сьогодні (з завтрашнього дня)"}}},
    {"type": "worldclock", "title": "World time", "title_uk": "Світовий час",
     "settings": {"zones": {
         "type": "zonelist",
         "default": ["Europe/Kyiv", "Europe/London",
                     "America/New_York", "Asia/Tokyo"],
         "max": MAX_ZONES,
         "title": "Cities (up to 6)",
         "title_uk": "Міста (до 6)",
         "options": [{"value": tz, "label": f"{en} ({gmt})",
                      "label_uk": f"{uk} ({gmt})"}
                     for tz, en, uk, gmt in ZONE_CATALOG]}}},
    {"type": "weather", "title": "Weather", "title_uk": "Погода",
     "settings": {"place": {"type": "str", "default": "Kyiv",
                            "title": "City", "title_uk": "Місто"}}},
]
