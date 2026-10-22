"""Шрифты с фолбэками Linux + macOS (перенос из monitor.py)."""
from pathlib import Path

from PIL import ImageFont

_FONT_WARNED = False

SANS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/opt/homebrew/share/fonts/DejaVuSans-Bold.ttf",
        "/usr/local/share/fonts/DejaVuSans-Bold.ttf",
        str(Path.home() / "Library/Fonts/DejaVuSans-Bold.ttf"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc"]
MONO = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/opt/homebrew/share/fonts/DejaVuSansMono-Bold.ttf",
        "/usr/local/share/fonts/DejaVuSansMono-Bold.ttf",
        str(Path.home() / "Library/Fonts/DejaVuSansMono-Bold.ttf"),
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
        "/System/Library/Fonts/Menlo.ttc"]


def _font(size, paths):
    global _FONT_WARNED
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    if not _FONT_WARNED:
        _FONT_WARNED = True
        print("[fonts] TrueType шрифт не найден, используется встроенный "
              "растровый (текст будет крошечным)")
    return ImageFont.load_default()


F_HUGE = _font(80, SANS)
F_BIG = _font(44, SANS)
F_MED = _font(32, SANS)
F_REG = _font(26, SANS)
F_SM = _font(20, SANS)
F_TINY = _font(15, MONO)
F_CLOCK = _font(96, SANS)
