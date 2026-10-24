"""Сборка кадра 1920x440 из конфигурации: шапка + панели виджетов."""
import time

from PIL import Image, ImageDraw

from trofeo_lcd import WIDTH, HEIGHT

from . import l10n
from .config import AppConfig
from .fonts import F_MED, F_SM
from .widgets import WIDGETS, text_right

MARGIN = 20
HEADER_H = 58
GAP = 14


def fmt_uptime(s):
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{d}d {h:02d}:{m:02d}" if d else f"{h:02d}:{m:02d}"


def draw_header(d, theme, hcfg, m):
    y = MARGIN - 4
    x = MARGIN + 4
    if hcfg.show_host:
        d.text((x, y), m["host"], font=F_MED, fill=theme.accent)
        x += d.textlength(m["host"], font=F_MED) + 20
    if m.get("no_data"):
        d.text((x, y + 10), l10n.tr("no data", "немає даних"),
               font=F_SM, fill=theme.dim)
    elif hcfg.show_uptime:
        d.text((x, y + 10), f"up {fmt_uptime(m['uptime'])}",
               font=F_SM, fill=theme.dim)
    if hcfg.show_load and m["load"] is not None:
        la1, la5, la15 = m["load"]
        d.text((WIDTH // 2 - 120, y + 10),
               f"load {la1:.2f}  {la5:.2f}  {la15:.2f}", font=F_SM, fill=theme.dim)
    if hcfg.show_clock:
        text_right(d, WIDTH - MARGIN - 4, y, time.strftime("%H:%M:%S"),
                   F_MED, theme.fg)
        import datetime as _dt
        today = _dt.date.today()
        text_right(d, WIDTH - MARGIN - 4 - 175, y + 10,
                   f"{today.day} {l10n.months_gen()[today.month - 1]}",
                   F_SM, theme.dim)


def render_frame(cfg: AppConfig, m: dict) -> Image.Image:
    """Отрисовать кадр по конфигу и срезу метрик."""
    l10n.set_lang(getattr(cfg, "language", "en"))
    theme = cfg.theme
    img = Image.new("RGB", (WIDTH, HEIGHT), theme.bg)
    d = ImageDraw.Draw(img)

    header_h = HEADER_H if cfg.header.enabled else 0
    if cfg.header.enabled:
        draw_header(d, theme, cfg.header, m)

    n = len(cfg.panels)
    panel_y = MARGIN + header_h
    panel_h = HEIGHT - panel_y - MARGIN
    panel_w = (WIDTH - 2 * MARGIN - (n - 1) * GAP) // n

    titles = {"cpu": "CPU", "memory": "MEMORY", "network": "NETWORK",
              "clock": "", "image": "", "calendar": "CALENDAR",
              "worldclock": "WORLD TIME", "weather": "WEATHER"}
    for i, p in enumerate(cfg.panels):
        x = MARGIN + i * (panel_w + GAP)
        d.rounded_rectangle([x, panel_y, x + panel_w, panel_y + panel_h],
                            radius=14, fill=theme.panel,
                            outline=theme.border, width=2)
        title = (f"DISK  {p.settings.get('path', '/')}" if p.type == "disk"
                 else titles.get(p.type, p.type.upper()))
        if title:
            d.text((x + 22, panel_y + 12), title, font=F_SM, fill=theme.dim)
        WIDGETS[p.type](img, d, x, panel_y, panel_w, panel_h,
                        theme, p.settings, m)
    return img


def disk_paths(cfg: AppConfig):
    """Пути дисков, нужные метрикам для этого конфига."""
    paths = [p.settings.get("path", "/") for p in cfg.panels if p.type == "disk"]
    return tuple(paths) or ("/",)
