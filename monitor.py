#!/usr/bin/env python3
"""
Системный мониторинг для Thermalright Trofeo Vision 11.3 LCD BLACK
Разрешение панели: 1920x400 (11.3", IPS, USB Type-C).
Передача кадров через PyUSB bulk transfer. Linux / Proxmox.

Запуск:
    python3 monitor_113.py                  # обычный режим
    python3 monitor_113.py --preview out.png  # отрисовать кадр в файл, без USB
    python3 monitor_113.py --list           # показать подходящие USB-устройства
    TV_VID=0x0416 TV_PID=0x5302 python3 monitor_113.py
"""
import argparse
import io
import os
import socket
import struct
import sys
import time
from pathlib import Path

import psutil
import usb.core
import usb.util
from PIL import Image, ImageDraw, ImageFont

# ── Устройство ────────────────────────────────────────────────────
# Trofeo Vision 11.3 LCD BLACK: 0416:5408, product string "USBDISPLAY".
# (0416 = Nuvoton/Winbond, тот же контроллер, что и в 6.86"/9.16" версиях,
#  но PID отличается: у 6.86" было 5302.)
VID = int(os.environ.get("TV_VID", "0x0416"), 0)
PID = int(os.environ.get("TV_PID", "0x5408"), 0)

# Запасные ID на случай другой ревизии прошивки
CANDIDATE_IDS = [(0x0416, 0x5408), (0x0416, 0x5302), (0x0416, 0x5304)]

WIDTH, HEIGHT = 1920, 440   # реальный буфер панели: 440 строк, не 400 (см. дамп TRCC)
REFRESH_SEC = 1.0
JPEG_QUALITY = 85
# 2 = 4:2:0, как кодирует TRCC. Аппаратные декодеры часто не умеют 4:4:4,
# и на нём прошивка виснет до передёргивания питания.
SUBSAMPLING = 2

EP_OUT = None
EP_IN = None

# ── Тема ──────────────────────────────────────────────────────────
BG = (12, 14, 22)
PANEL = (24, 28, 40)
BORDER = (40, 50, 70)
FG = (220, 230, 240)
DIM = (130, 140, 160)
ACCENT = (80, 200, 255)
GOOD = (90, 220, 130)
WARN = (255, 180, 60)
CRIT = (255, 80, 80)
TRACK = (35, 40, 55)


_FONT_WARNED = False


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
        print("[warn] TrueType шрифт не найден, используется встроенный "
              "растровый (текст будет крошечным). "
              "macOS: brew install --cask font-dejavu")
    return ImageFont.load_default()


# Linux + macOS. Первый существующий путь выигрывает.
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

F_HUGE = _font(80, SANS)
F_BIG = _font(44, SANS)
F_MED = _font(32, SANS)
F_REG = _font(26, SANS)
F_SM = _font(20, SANS)
F_TINY = _font(15, MONO)

# ── Геометрия под 1920x400 ────────────────────────────────────────
MARGIN = 20
HEADER_H = 58
GAP = 14
PANEL_Y = MARGIN + HEADER_H          # 78
PANEL_H = HEIGHT - PANEL_Y - MARGIN  # 302
PANEL_W = (WIDTH - 2 * MARGIN - 3 * GAP) // 4   # 459
COL = [MARGIN + i * (PANEL_W + GAP) for i in range(4)]
PAD = 22   # внутренний отступ панели


def color_for(p):
    return CRIT if p >= 85 else WARN if p >= 65 else ACCENT if p >= 40 else GOOD


def fmt_bytes(n):
    n = float(n)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_uptime(s):
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{d}d {h:02d}:{m:02d}" if d else f"{h:02d}:{m:02d}"


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


# ── Примитивы отрисовки ───────────────────────────────────────────
def panel(d, col, title):
    x, y = COL[col], PANEL_Y
    d.rounded_rectangle([x, y, x + PANEL_W, y + PANEL_H],
                        radius=14, fill=PANEL, outline=BORDER, width=2)
    d.text((x + PAD, y + 12), title, font=F_SM, fill=DIM)
    return x, y


def bar(d, x, y, w, h, pct, color=None):
    pct = max(0.0, min(100.0, float(pct)))
    color = color or color_for(pct)
    r = h // 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=TRACK)
    fw = int(w * pct / 100)
    if fw > h:
        d.rounded_rectangle([x, y, x + fw, y + h], radius=r, fill=color)
    elif fw > 0:
        d.ellipse([x, y, x + h, y + h], fill=color)


def text_right(d, x_right, y, text, font, fill):
    d.text((x_right - d.textlength(text, font=font), y), text, font=font, fill=fill)


# ── Сбор метрик ───────────────────────────────────────────────────
_last_net = {"t": time.time(), "s": 0, "r": 0}


def net_rates():
    now = time.time()
    n = psutil.net_io_counters()
    dt = max(now - _last_net["t"], 0.001)
    s = (n.bytes_sent - _last_net["s"]) / dt
    r = (n.bytes_recv - _last_net["r"]) / dt
    _last_net.update(t=now, s=n.bytes_sent, r=n.bytes_recv)
    return max(0, s), max(0, r), n.bytes_sent, n.bytes_recv


psutil.cpu_percent(interval=None)
psutil.cpu_percent(percpu=True, interval=None)
net_rates()


# ── Кадр ──────────────────────────────────────────────────────────
def draw_header(d):
    y = MARGIN - 4
    host = socket.gethostname().split(".")[0].upper()
    d.text((MARGIN + 4, y), host, font=F_MED, fill=ACCENT)
    hw = d.textlength(host, font=F_MED)
    d.text((MARGIN + 4 + hw + 20, y + 10),
           f"up {fmt_uptime(time.time() - psutil.boot_time())}", font=F_SM, fill=DIM)

    try:
        la1, la5, la15 = os.getloadavg()
        d.text((WIDTH // 2 - 120, y + 10),
               f"load {la1:.2f}  {la5:.2f}  {la15:.2f}", font=F_SM, fill=DIM)
    except OSError:
        pass

    text_right(d, WIDTH - MARGIN - 4, y, time.strftime("%H:%M:%S"), F_MED, FG)
    text_right(d, WIDTH - MARGIN - 4 - 175, y + 10,
               time.strftime("%a %d %b"), F_SM, DIM)


def draw_cpu(d):
    x, y = panel(d, 0, "CPU")
    cpu = psutil.cpu_percent(interval=None)
    per = psutil.cpu_percent(percpu=True, interval=None)

    d.text((x + PAD, y + 34), f"{cpu:.1f}%", font=F_HUGE, fill=color_for(cpu))

    t = cpu_temp()
    sub = f"{len(per)} cores"
    if t is not None:
        sub += f"   {t:.0f}\u00b0C"
    d.text((x + PAD, y + 132), sub, font=F_SM, fill=DIM)

    # Ядра: до 16 штук в две колонки
    cores = per[:16]
    rows = min(8, max(1, (len(cores) + 1) // 2)) if len(cores) > 8 else len(cores)
    col_w = (PANEL_W - 2 * PAD - 12) // 2
    top = y + 166
    pitch = 15
    for i, c in enumerate(cores):
        cx = x + PAD + (0 if i < rows else col_w + 12)
        cy = top + (i % rows) * pitch
        if cy + 8 > y + PANEL_H - 12:
            break
        d.text((cx, cy - 3), f"{i:>2}", font=F_TINY, fill=DIM)
        bar(d, cx + 24, cy, col_w - 30, 8, c)


def draw_memory(d):
    x, y = panel(d, 1, "MEMORY")
    mem = psutil.virtual_memory()
    d.text((x + PAD, y + 34), f"{mem.percent:.1f}%",
           font=F_HUGE, fill=color_for(mem.percent))
    d.text((x + PAD, y + 132),
           f"{fmt_bytes(mem.used)} / {fmt_bytes(mem.total)}", font=F_REG, fill=FG)
    bar(d, x + PAD, y + 176, PANEL_W - 2 * PAD, 18, mem.percent)

    swap = psutil.swap_memory()
    d.text((x + PAD, y + 220), "SWAP", font=F_SM, fill=DIM)
    text_right(d, x + PANEL_W - PAD, y + 220,
               f"{fmt_bytes(swap.used)} / {fmt_bytes(swap.total)}", F_SM, DIM)
    bar(d, x + PAD, y + 252, PANEL_W - 2 * PAD, 10,
        swap.percent, WARN if swap.percent > 10 else DIM)


def draw_disk(d):
    x, y = panel(d, 2, "DISK  /")
    disk = psutil.disk_usage("/")
    d.text((x + PAD, y + 34), f"{disk.percent:.1f}%",
           font=F_HUGE, fill=color_for(disk.percent))
    d.text((x + PAD, y + 132),
           f"{fmt_bytes(disk.used)} / {fmt_bytes(disk.total)}", font=F_REG, fill=FG)
    bar(d, x + PAD, y + 176, PANEL_W - 2 * PAD, 18, disk.percent)

    d.text((x + PAD, y + 218), "FREE", font=F_SM, fill=DIM)
    d.text((x + PAD, y + 242), fmt_bytes(disk.free), font=F_BIG, fill=GOOD)


def draw_network(d):
    x, y = panel(d, 3, "NETWORK")
    sent, recv, tot_s, tot_r = net_rates()

    d.text((x + PAD, y + 46), "\u2193", font=F_BIG, fill=GOOD)
    d.text((x + PAD + 44, y + 54), f"{fmt_bytes(recv)}/s", font=F_MED, fill=FG)

    d.text((x + PAD, y + 122), "\u2191", font=F_BIG, fill=ACCENT)
    d.text((x + PAD + 44, y + 130), f"{fmt_bytes(sent)}/s", font=F_MED, fill=FG)

    d.line([x + PAD, y + 200, x + PANEL_W - PAD, y + 200], fill=BORDER, width=2)
    d.text((x + PAD, y + 216), "total", font=F_SM, fill=DIM)
    d.text((x + PAD, y + 244), f"\u2193 {fmt_bytes(tot_r)}", font=F_REG, fill=DIM)
    text_right(d, x + PANEL_W - PAD, y + 244, f"\u2191 {fmt_bytes(tot_s)}", F_REG, DIM)


def render_frame():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    draw_header(d)
    draw_cpu(d)
    draw_memory(d)
    draw_disk(d)
    draw_network(d)
    return img


# ── USB ───────────────────────────────────────────────────────────
def find_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is not None:
        return dev
    for vid, pid in CANDIDATE_IDS:
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        if dev is not None:
            print(f"  найдено по запасному ID: {vid:04x}:{pid:04x}")
            return dev
    return None


def list_devices():
    print("Все USB-устройства (ищите панель по VID:PID):")
    for dev in usb.core.find(find_all=True):
        try:
            name = usb.util.get_string(dev, dev.iProduct) or "?"
        except Exception:
            name = "?"
        print(f"  {dev.idVendor:04x}:{dev.idProduct:04x}  {name}")


def open_device():
    global EP_OUT, EP_IN
    EP_OUT = EP_IN = None

    dev = find_device()
    if dev is None:
        raise RuntimeError(
            f"Устройство {VID:04x}:{PID:04x} не найдено. "
            "Проверьте lsusb и задайте TV_VID / TV_PID.")

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
            print("  kernel driver detached")
    except Exception as e:
        print(f"  detach: {e}")

    try:
        dev.set_configuration()
    except Exception as e:
        print(f"  set_configuration: {e}")

    try:
        usb.util.claim_interface(dev, 0)
    except Exception as e:
        print(f"  claim: {e}")

    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    print(f"  intf class=0x{intf.bInterfaceClass:02x} "
          f"sub=0x{intf.bInterfaceSubClass:02x} proto=0x{intf.bInterfaceProtocol:02x}")
    for ep in intf:
        direction = usb.util.endpoint_direction(ep.bEndpointAddress)
        ep_type = usb.util.endpoint_type(ep.bmAttributes)
        kind = {usb.util.ENDPOINT_TYPE_BULK: "bulk",
                usb.util.ENDPOINT_TYPE_INTR: "intr",
                usb.util.ENDPOINT_TYPE_ISO: "iso",
                usb.util.ENDPOINT_TYPE_CTRL: "ctrl"}.get(ep_type, "?")
        print(f"    ep 0x{ep.bEndpointAddress:02x} {kind} "
              f"maxpkt={ep.wMaxPacketSize}")
        if ep_type != usb.util.ENDPOINT_TYPE_BULK:
            continue
        if direction == usb.util.ENDPOINT_OUT and EP_OUT is None:
            EP_OUT = ep.bEndpointAddress
        elif direction == usb.util.ENDPOINT_IN and EP_IN is None:
            EP_IN = ep.bEndpointAddress

    if EP_OUT is None:
        raise RuntimeError("не найден OUT endpoint")
    print(f"  EP_OUT=0x{EP_OUT:02x}  EP_IN="
          f"{'0x%02x' % EP_IN if EP_IN is not None else 'нет'}")
    return dev


MAGIC = b"\xDA\xDB\xDC\xDD"


def _hs_payload(cmd, offset):
    p = bytearray(512)
    p[0:4] = MAGIC
    p[offset] = cmd
    return bytes(p)


def handshake(dev, cmd=0x01, offset=12, quiet=False):
    """Возвращает True, если панель ответила. Ошибка не фатальна."""
    try:
        dev.write(EP_OUT, _hs_payload(cmd, offset), timeout=2000)
    except Exception as e:
        if not quiet:
            print(f"  handshake write: {e}")
        return False

    if EP_IN is None:
        return False
    try:
        resp = bytes(dev.read(EP_IN, 512, timeout=2000))
    except usb.core.USBTimeoutError:
        if not quiet:
            print("  [warn] handshake без ответа (timeout), продолжаем без него")
        return False
    except Exception as e:
        if not quiet:
            print(f"  handshake read: {e}")
        return False

    if resp[:4] != MAGIC:
        if not quiet:
            print(f"  [warn] неожиданный ответ: {resp[:16].hex()}")
        return False
    print(f"  handshake ok: PM=0x{resp[5]:02x} SUB=0x{resp[4]:02x}")
    return True


def probe_handshake(dev):
    """Перебор байта команды и его смещения, ищем тот, на который панель отвечает."""
    print("Перебор вариантов handshake (magic DA DB DC DD)…")
    hits = []
    for offset in (4, 8, 12):
        for cmd in range(0x00, 0x10):
            try:
                dev.write(EP_OUT, _hs_payload(cmd, offset), timeout=1000)
            except Exception as e:
                print(f"  off={offset:2d} cmd=0x{cmd:02x}  write err: {e}")
                continue
            try:
                resp = bytes(dev.read(EP_IN, 512, timeout=600))
            except usb.core.USBTimeoutError:
                continue
            except Exception as e:
                print(f"  off={offset:2d} cmd=0x{cmd:02x}  read err: {e}")
                continue
            print(f"  off={offset:2d} cmd=0x{cmd:02x}  ОТВЕТ: {resp[:24].hex()}")
            hits.append((offset, cmd))
            time.sleep(0.05)
    if not hits:
        print("Ответов нет ни на один вариант. "
              "Вероятно, эта прошивка вообще не отвечает на IN endpoint, "
              "и handshake ей не нужен. Пробуйте --once.")
    else:
        print(f"Отвечают: {hits}")
    return hits


def probe_repeat(dev, cmd, offset, n):
    """Один и тот же пакет n раз подряд.

    Если панель разбирает содержимое, ответ придёт на каждую попытку.
    Если это периодический heartbeat (~2с), ответы придут равномерно
    по времени и от cmd зависеть не будут.
    """
    print(f"Повтор: cmd=0x{cmd:02x} off={offset}, {n} раз подряд")
    got = 0
    for i in range(n):
        try:
            dev.write(EP_OUT, _hs_payload(cmd, offset), timeout=1000)
        except Exception as e:
            print(f"  #{i:<2} write err: {e}")
            continue
        try:
            resp = bytes(dev.read(EP_IN, 512, timeout=600))
            got += 1
            print(f"  #{i:<2} ОТВЕТ: {resp[:24].hex()}")
        except usb.core.USBTimeoutError:
            print(f"  #{i:<2} тишина")
        except Exception as e:
            print(f"  #{i:<2} read err: {e}")
    print(f"Итого ответов: {got} из {n}")
    if got == n:
        print("=> панель разбирает содержимое пакета, cmd значим")
    elif 0 < got < n:
        print("=> ответ привязан к объёму принятых байт, а не к cmd; "
              "handshake этой прошивке не нужен")
    else:
        print("=> ответов нет")
    return got


def drain_in(dev, limit=8):
    """Вычитать накопившиеся статус-пакеты, чтобы IN endpoint не встал."""
    if EP_IN is None:
        return 0
    n = 0
    for _ in range(limit):
        try:
            dev.read(EP_IN, 512, timeout=20)
            n += 1
        except Exception:
            break
    return n


# ── Протокол кадра (восстановлен из дампа TRCC) ───────────────────
# Каждый чанк: 16 байт заголовка + данные.
#   [0:2]   01 ff            константа
#   [2:4]   LE u16           значение на кадр (назначение выясняется)
#   [4:11]  03 00 f0 01 01 0a 02   константа
#   [11:15] LE u32           смещение чанка в блоках по 512
# Кадр: 65 чанков по 4096 + один 2048. Payload ровно 267232 байта,
# JPEG добивается нулями до этого размера.
HDR_LEN = 16
CHUNK_FULL = 4096
CHUNK_LAST = 2048
CHUNKS_FULL = 65
HDR_CONST = bytes.fromhex("0300f001010a02")
FRAME_PAYLOAD = CHUNKS_FULL * (CHUNK_FULL - HDR_LEN) + (CHUNK_LAST - HDR_LEN)


# ── Протокол (окончательный, доказан по дампам TRCC) ──────────────
# Поток кадра = 524 блока по 512 байт. Каждый блок:
#   [0:2]   01 ff
#   [2:4]   LE u16  поле кадра (функция длины JPEG)
#   [4:11]  03 00 f0 01 01 0a 02
#   [11:15] LE u32  номер блока (0..523)
#   [15]    00
#   [16:]   496 байт данных JPEG
# Ёмкость кадра: 524*496 = 259904 байта. Bulk-записи по 4096 (8 блоков),
# последняя 2048 (4 блока) — это только транспортная нарезка.
BLOCK = 512
BLK_DATA = BLOCK - HDR_LEN          # 496
N_BLOCKS = 524
FRAME_PAYLOAD = N_BLOCKS * BLK_DATA  # 259904
TARGET_LEN = 258507                  # длина JPEG эталонного кадра TRCC
FIELD_BASE = 195600


def frame_field(clean_len):
    """Поле [2:4] по чистой длине JPEG.

    Формула восстановлена по 19 кадрам двух дампов на "грязной" длине C
    (JPEG с вкраплёнными заголовками): field = C - 16*(C//512) - 195600.
    C выражается через чистую длину R как R + 16 * (число блоков 1..b,
    не кратных 8), где b — блок последнего байта."""
    b = max(0, (clean_len - 1) // BLK_DATA)
    non8 = b - b // 8
    c = clean_len + 16 * non8
    return (c - 16 * (c // 512) - FIELD_BASE) & 0xFFFF


def pad_jpeg_com(jpeg, target):
    """Добить JPEG до target байт COM-сегментами перед FF D9."""
    if len(jpeg) > target:
        raise ValueError(f"JPEG {len(jpeg)} длиннее цели {target}")
    need = target - len(jpeg)
    if need == 0:
        return jpeg
    if not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("нет EOI в конце JPEG")
    if need < 4:
        return jpeg + b"\x00" * need
    segs = bytearray()
    while need:
        take = min(need, 65535 + 2)
        if 0 < need - take < 4:
            take = need - 4
        data_len = take - 4
        segs += b"\xff\xfe" + (data_len + 2).to_bytes(2, "big") + b"\x00" * data_len
        need -= take
    return jpeg[:-2] + bytes(segs) + b"\xff\xd9"


def clean_extracted(F):
    """Убрать вкраплённые заголовки из JPEG, извлечённого старым парсером."""
    out = bytearray()
    for st in range(0, len(F), 4080):
        sl = F[st:st + 4080]
        out += sl[:BLK_DATA]
        p = BLK_DATA
        while p < len(sl):
            out += sl[p + HDR_LEN:p + BLOCK]
            p += BLOCK
    return bytes(out)


def build_chunks(jpeg, field):
    """Собрать кадр: 524 блока с заголовками, нарезанные в bulk-записи."""
    if len(jpeg) > FRAME_PAYLOAD:
        raise ValueError(
            f"JPEG {len(jpeg)} байт не влезает в {FRAME_PAYLOAD}, "
            "снизьте JPEG_QUALITY")
    buf = jpeg.ljust(FRAME_PAYLOAD, b"\x00")
    wire = bytearray()
    for i in range(N_BLOCKS):
        h = bytearray(HDR_LEN)
        h[0:2] = b"\x01\xff"
        h[2:4] = struct.pack("<H", field & 0xFFFF)
        h[4:11] = HDR_CONST
        h[11:15] = struct.pack("<I", i)
        wire += h + buf[i * BLK_DATA:(i + 1) * BLK_DATA]
    # транспортная нарезка как у TRCC: 65 x 4096 + 2048
    chunks = [bytes(wire[o:o + CHUNK_FULL])
              for o in range(0, CHUNKS_FULL * CHUNK_FULL, CHUNK_FULL)]
    chunks.append(bytes(wire[CHUNKS_FULL * CHUNK_FULL:]))
    return chunks


def send_chunks(dev, chunks):
    for i, c in enumerate(chunks):
        try:
            dev.write(EP_OUT, c, timeout=5000)
        except Exception as e:
            raise RuntimeError(
                f"запись чанка {i}/{len(chunks)} ({len(c)} байт): {e}") from e
    drain_in(dev, limit=64)


def send_jpeg(dev, jpeg, field):
    send_chunks(dev, build_chunks(jpeg, field))


def replay(dev, path, field=None, repeat=3, pause=0.5):
    """Проиграть кадр, снятый с TRCC (файл из parse_trcc_capture)."""
    jpeg = Path(path).read_bytes()
    if b"\x01\xff" == jpeg[496:498]:
        jpeg = clean_extracted(jpeg)
        eoi = jpeg.rfind(b"\xff\xd9")
        jpeg = jpeg[:eoi + 2]
        print(f"  вкраплённые заголовки убраны, чистый JPEG {len(jpeg)} байт")
    if field is None:
        field = frame_field(len(jpeg))
        print(f"  поле по формуле: 0x{field:04x}")
    print(f"Кадр {path}: {len(jpeg)} байт, поле=0x{field:04x}, "
          f"повторов {repeat}")
    for i in range(repeat):
        send_jpeg(dev, jpeg, field)
        print(f"  отправлен {i + 1}/{repeat}")
        time.sleep(pause)
    print("Смотрите на панель.")


def inspect_jpeg(path):
    """Полный список маркеров JPEG, работает и на битых файлах."""
    data = Path(path).read_bytes()
    print(f"{path}: {len(data)} байт, поле по формуле 0x{frame_field(len(data)):04x}")
    if data[:2] != b"\xff\xd8":
        print("  нет SOI, это не JPEG")
        return
    names = {0xC0: "SOF0 baseline", 0xC1: "SOF1", 0xC2: "SOF2 PROGRESSIVE",
             0xC4: "DHT", 0xDB: "DQT", 0xDD: "DRI", 0xDA: "SOS",
             0xFE: "COM", 0xD9: "EOI"}
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0x00, 0x01, 0xD8) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        if m == 0xD9:
            print(f"  {i:6d}  EOI, хвост {len(data) - i - 2} байт")
            break
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        name = names.get(m, f"APP{m - 0xE0}" if 0xE0 <= m <= 0xEF else f"0x{m:02x}")
        extra = ""
        if m == 0xDD:
            extra = f"  restart interval = {int.from_bytes(data[i+4:i+6], 'big')} MCU"
        elif m in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            nc = data[i + 9]
            samps = " ".join(f"{data[i+11+c*3] >> 4}x{data[i+11+c*3] & 0xF}"
                             for c in range(nc))
            extra = f"  {w}x{h}, {nc} комп., сэмплирование {samps}"
        elif m == 0xDB:
            extra = f"  таблица id={data[i+4] & 0xF}, точность={'16бит' if data[i+4]>>4 else '8бит'}"
        elif m == 0xC4:
            extra = f"  класс={'AC' if data[i+4]>>4 else 'DC'} id={data[i+4] & 0xF}"
        elif 0xE0 <= m <= 0xEF:
            extra = f"  {data[i+4:i+4+min(seglen-2,12)]!r}"
        print(f"  {i:6d}  {name:<16} len={seglen}{extra}")
        if m == 0xDA:
            j = i + 2 + seglen
            rst = 0
            while j + 1 < len(data):
                if data[j] == 0xFF and data[j + 1] not in (0x00,):
                    if 0xD0 <= data[j + 1] <= 0xD7:
                        rst += 1
                        j += 2
                        continue
                    break
                j += 1
            print(f"          entropy-данные {j - i - 2 - seglen} байт, "
                  f"RST-маркеров: {rst}")
            i = j
            continue
        i += 2 + seglen


def watchdog_test(dev, path=None):
    """Найти, через сколько без кадра панель возвращает логотип."""
    if path:
        jpeg = Path(path).read_bytes()
    else:
        b = io.BytesIO()
        test_image().save(b, format="JPEG", quality=JPEG_QUALITY, subsampling=SUBSAMPLING)
        jpeg = b.getvalue()
    print("Смотрите на панель и запоминайте, на какой паузе вернулся логотип.\n")
    for gap in (0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0):
        send_jpeg(dev, jpeg, 0xF1CB)
        print(f"  кадр отправлен, пауза {gap}с …")
        time.sleep(gap)
    send_jpeg(dev, jpeg, 0xF1CB)
    print("\nГотово. Максимальная пауза, при которой картинка держалась, "
          "и есть верхняя граница для --interval.")


# ── Диагностика устройства ────────────────────────────────────────
def dump_descriptors(dev):
    print(f"idVendor=0x{dev.idVendor:04x}  idProduct=0x{dev.idProduct:04x}  "
          f"bcdDevice=0x{dev.bcdDevice:04x}  bDeviceClass=0x{dev.bDeviceClass:02x}")
    for label, idx in (("Manufacturer", dev.iManufacturer),
                       ("Product", dev.iProduct),
                       ("Serial", dev.iSerialNumber)):
        try:
            print(f"  {label}: {usb.util.get_string(dev, idx)}")
        except Exception as e:
            print(f"  {label}: <{e}>")

    for cfg in dev:
        print(f"\nconfig {cfg.bConfigurationValue}: "
              f"{cfg.bNumInterfaces} интерфейс(ов), "
              f"maxpower={cfg.bMaxPower * 2}mA")
        for intf in cfg:
            print(f"  intf {intf.bInterfaceNumber} alt {intf.bAlternateSetting}  "
                  f"class=0x{intf.bInterfaceClass:02x} "
                  f"sub=0x{intf.bInterfaceSubClass:02x} "
                  f"proto=0x{intf.bInterfaceProtocol:02x}  "
                  f"endpoints={intf.bNumEndpoints}")
            for ep in intf:
                d = ("OUT" if usb.util.endpoint_direction(ep.bEndpointAddress)
                     == usb.util.ENDPOINT_OUT else "IN")
                t = usb.util.endpoint_type(ep.bmAttributes)
                kind = {usb.util.ENDPOINT_TYPE_BULK: "bulk",
                        usb.util.ENDPOINT_TYPE_INTR: "intr",
                        usb.util.ENDPOINT_TYPE_ISO: "iso",
                        usb.util.ENDPOINT_TYPE_CTRL: "ctrl"}.get(t, "?")
                print(f"    ep 0x{ep.bEndpointAddress:02x} {d:3} {kind:4} "
                      f"maxpkt={ep.wMaxPacketSize} interval={ep.bInterval}")


def ctrl_probe(dev, write_probe=False):
    """Опрос vendor/class control-запросов на чтение. Ничего не меняет."""
    print("Control IN запросы (bmRequestType 0xC0 vendor, 0xA1 class)…")
    found = 0
    for rt in (0xC0, 0xA1, 0x80):
        for breq in range(0x100):
            try:
                r = dev.ctrl_transfer(rt, breq, 0, 0, 64, timeout=250)
            except Exception:
                continue
            if r is not None and len(r):
                data = bytes(r)
                if any(data):
                    found += 1
                    print(f"  rt=0x{rt:02x} bRequest=0x{breq:02x} "
                          f"len={len(data)}  {data[:32].hex()}")
    if not found:
        print("  ничего не ответило")
    return found


def try_interfaces(dev, img=None):
    """Отправить тестовый кадр в каждый bulk OUT каждого интерфейса."""
    img = img or test_image()
    jpg = _jpeg(img)
    payload = _pad(_hdr_v1(len(jpg)) + jpg)
    cfg = dev.get_active_configuration()
    for intf in cfg:
        try:
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
        except Exception as e:
            print(f"  intf {intf.bInterfaceNumber}: claim не удался ({e})")
            continue
        try:
            dev.set_interface_altsetting(intf)
        except Exception:
            pass
        for ep in intf:
            if usb.util.endpoint_direction(ep.bEndpointAddress) != usb.util.ENDPOINT_OUT:
                continue
            if usb.util.endpoint_type(ep.bmAttributes) != usb.util.ENDPOINT_TYPE_BULK:
                continue
            addr = ep.bEndpointAddress
            print(f"  intf {intf.bInterfaceNumber} alt {intf.bAlternateSetting} "
                  f"-> ep 0x{addr:02x} …")
            try:
                dev.write(addr, payload, timeout=8000)
                print("    отправлено, смотрите на панель 3с")
            except Exception as e:
                print(f"    ошибка: {e}")
            time.sleep(3)


# ── Восстановление после залипания ────────────────────────────────
def recover(dev, hard=False):
    """Снять halt с эндпоинтов и вычистить накопившееся.

    hard=True дополнительно делает USB-reset устройства. Это ближайший
    программный аналог передёргивания кабеля.
    """
    for ep in (EP_OUT, EP_IN):
        if ep is None:
            continue
        try:
            dev.clear_halt(ep)
        except Exception:
            pass
    try:
        drain_in(dev, limit=400)
    except Exception:
        pass
    if hard:
        try:
            dev.reset()
            print("  device reset выполнен")
            time.sleep(1.5)
            return True
        except Exception as e:
            print(f"  device reset не удался: {e}")
    return False


def reopen(dev):
    """Полностью переоткрыть устройство."""
    try:
        usb.util.release_interface(dev, 0)
    except Exception:
        pass
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    time.sleep(1.0)
    return open_device()


# ── Завершение передачи: короткий пакет и ZLP ─────────────────────
def _chunked(dev, data, chunk=512, final_zlp=False):
    for i in range(0, len(data), chunk):
        dev.write(EP_OUT, data[i:i + chunk], timeout=10000)
    if final_zlp:
        dev.write(EP_OUT, b"", timeout=2000)


def zlp_variants(img):
    """Варианты, различающиеся только признаком конца передачи."""
    jpg = _jpeg(img)
    hdr = _hdr_v1(len(jpg))
    raw = hdr + jpg
    v = []
    v.append(("A. header+jpeg одной передачей БЕЗ паддинга (конец = короткий пакет)",
              lambda d: d.write(EP_OUT, raw, timeout=10000)))
    v.append(("B. header+jpeg с паддингом, затем явный ZLP",
              lambda d: (d.write(EP_OUT, _pad(raw), timeout=10000),
                         d.write(EP_OUT, b"", timeout=2000))))
    v.append(("C. header 512 отдельно, jpeg без паддинга",
              lambda d: (d.write(EP_OUT, _pad(hdr), timeout=5000),
                         d.write(EP_OUT, jpg, timeout=10000))))
    v.append(("D. header 512 отдельно, jpeg с паддингом, затем ZLP",
              lambda d: (d.write(EP_OUT, _pad(hdr), timeout=5000),
                         d.write(EP_OUT, _pad(jpg), timeout=10000),
                         d.write(EP_OUT, b"", timeout=2000))))
    v.append(("E. кусками по 512, последний кусок короткий",
              lambda d: _chunked(d, raw)))
    v.append(("F. кусками по 512 с паддингом, затем ZLP",
              lambda d: _chunked(d, _pad(raw), final_zlp=True)))
    v.append(("G. голый jpeg кусками по 512, последний короткий",
              lambda d: _chunked(d, jpg)))
    return v


def try_zlp(dev, only=None, pause=3.0):
    img = test_image()
    variants = zlp_variants(img)
    letters = "ABCDEFG"
    for i, (name, fn) in enumerate(variants):
        if only and letters[i] != only.upper():
            continue
        print(f"\n[{letters[i]}] {name}")
        try:
            fn(dev)
            drain_in(dev, limit=200)
            print(f"    отправлено, смотрите на панель {pause:.0f}с…")
        except Exception as e:
            print(f"    ошибка: {e}")
            recover(dev)
        time.sleep(pause)
        recover(dev)
    print("\nГотово.")


# ── Перебор форматов кадра ────────────────────────────────────────
def test_image():
    """Заведомо заметный кадр: половина зелёная, половина красная."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (220, 30, 30))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, WIDTH // 2, HEIGHT], fill=(30, 200, 60))
    d.text((WIDTH // 2 - 170, HEIGHT // 2 - 60), "TEST", font=F_HUGE,
           fill=(255, 255, 255))
    return img


def _jpeg(img, quality=80):
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=quality)
    return b.getvalue()


def _pad(b):
    return b.ljust(((len(b) + 511) // 512) * 512, b"\x00")


def _rgb565(img, big_endian=False):
    out = bytearray()
    fmt = ">H" if big_endian else "<H"
    for r, g, b in img.getdata():
        out += struct.pack(fmt, ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return bytes(out)


def _hdr_v1(size):
    return (MAGIC + b"\x02\x00\x00\x00" + struct.pack("<HH", WIDTH, HEIGHT)
            + b"\x02\x00\x00\x00" + struct.pack("<I", size))


def frame_variants(img):
    """(имя, [список bulk-передач])"""
    jpg = _jpeg(img)
    v = []
    v.append(("1. header+jpeg одной передачей (текущий)",
              [_pad(_hdr_v1(len(jpg)) + jpg)]))
    v.append(("2. header отдельным пакетом 512, затем jpeg",
              [_pad(_hdr_v1(len(jpg))), _pad(jpg)]))
    v.append(("3. header 512 + jpeg без паддинга",
              [_pad(_hdr_v1(len(jpg))), jpg]))
    v.append(("4. голый jpeg с паддингом, без заголовка",
              [_pad(jpg)]))
    v.append(("5. голый jpeg без паддинга",
              [jpg]))
    rgb565 = _rgb565(img)
    v.append(("6. raw RGB565 LE, без заголовка",
              [rgb565]))
    v.append(("7. header 512 + raw RGB565 LE",
              [_pad(_hdr_v1(len(rgb565))), rgb565]))
    v.append(("8. raw RGB565 BE, без заголовка",
              [_rgb565(img, big_endian=True)]))
    v.append(("9. raw RGB888, без заголовка",
              [img.tobytes()]))
    return v


def try_formats(dev, only=None, pause=3.0):
    img = test_image()
    print("Готовлю варианты (RGB565 считается медленно, подождите)…")
    variants = frame_variants(img)
    for i, (name, chunks) in enumerate(variants, start=1):
        if only and i != only:
            continue
        total = sum(len(c) for c in chunks)
        print(f"\n[{i}] {name}  ({len(chunks)} передач, {total} байт)")
        try:
            for c in chunks:
                dev.write(EP_OUT, c, timeout=10000)
            drain_in(dev, limit=200)
            print(f"    отправлено. Смотрите на панель {pause:.0f}с…")
        except Exception as e:
            print(f"    ошибка: {e}")
            recover(dev)
        time.sleep(pause)
        recover(dev)
    print("\nГотово. Запомните номер варианта, на котором что-то появилось.")


def send_image(dev, pil_img, field=None, quality=None, pad=True):
    if pil_img.size != (WIDTH, HEIGHT):
        pil_img = pil_img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG",
                 quality=quality or JPEG_QUALITY, subsampling=SUBSAMPLING)
    jpeg = buf.getvalue()
    if pad:
        jpeg = pad_jpeg_com(jpeg, TARGET_LEN)
    if field is None:
        field = frame_field(len(jpeg))
    send_jpeg(dev, jpeg, field)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", metavar="PNG",
                    help="сохранить один кадр в файл и выйти (без USB)")
    ap.add_argument("--list", action="store_true",
                    help="перечислить USB-устройства и выйти")
    ap.add_argument("--interval", type=float, default=REFRESH_SEC,
                    help="период обновления в секундах")
    ap.add_argument("--probe", action="store_true",
                    help="перебрать варианты handshake и выйти")
    ap.add_argument("--once", action="store_true",
                    help="отправить один кадр и выйти")
    ap.add_argument("--no-handshake", action="store_true",
                    help="сразу слать кадры, без handshake")
    ap.add_argument("--hs-cmd", type=lambda v: int(v, 0), default=0x01,
                    help="байт команды handshake (по умолчанию 0x01)")
    ap.add_argument("--hs-offset", type=int, default=12,
                    help="смещение байта команды handshake (по умолчанию 12)")
    ap.add_argument("--repeat", type=int, metavar="N",
                    help="послать один и тот же handshake N раз и выйти")
    ap.add_argument("--try-formats", action="store_true",
                    help="перебрать варианты формата кадра на тестовой картинке")
    ap.add_argument("--variant", type=int, metavar="N",
                    help="прогнать только вариант N из --try-formats")
    ap.add_argument("--info", action="store_true",
                    help="полный дамп дескрипторов устройства")
    ap.add_argument("--ctrl-probe", action="store_true",
                    help="опросить control-запросы на чтение")
    ap.add_argument("--try-interfaces", action="store_true",
                    help="послать тестовый кадр в каждый bulk OUT каждого интерфейса")
    ap.add_argument("--zlp", action="store_true",
                    help="перебрать способы завершения передачи (короткий пакет / ZLP)")
    ap.add_argument("--zlp-variant", metavar="LETTER",
                    help="прогнать только один вариант --zlp, например B")
    ap.add_argument("--reset", action="store_true",
                    help="снять halt и сделать USB-reset устройства, затем выйти")
    ap.add_argument("--replay", metavar="JPG",
                    help="проиграть кадр, извлечённый из дампа TRCC")
    ap.add_argument("--field", type=lambda v: int(v, 0), default=None,
                    help="переопределить поле [2:4]; иначе считается по формуле")
    ap.add_argument("--no-pad", action="store_true",
                    help="не добивать JPEG до эталонной длины (чистая формула)")
    ap.add_argument("--repeat-frames", type=int, default=3,
                    help="сколько раз повторить кадр при --replay")
    ap.add_argument("--mutate", type=int, metavar="OFFSET",
                    help="при --replay инвертировать байт по смещению (тест: проверяет ли панель содержимое)")
    ap.add_argument("--watchdog", action="store_true",
                    help="найти предельную паузу между кадрами")
    ap.add_argument("--inspect", metavar="JPG",
                    help="показать параметры кадра из дампа и сравнить с нашими")
    args = ap.parse_args()

    if args.inspect:
        inspect_jpeg(args.inspect)
        return

    if args.list:
        list_devices()
        return

    if args.preview:
        time.sleep(0.5)
        render_frame().save(args.preview)
        print(f"Кадр сохранён: {args.preview}  ({WIDTH}x{HEIGHT})")
        return

    print(f"Подключение к {VID:04x}:{PID:04x} …")
    dev = open_device()

    if args.probe:
        probe_handshake(dev)
        usb.util.release_interface(dev, 0)
        return

    if args.repeat:
        probe_repeat(dev, args.hs_cmd, args.hs_offset, args.repeat)
        usb.util.release_interface(dev, 0)
        return

    if args.info:
        dump_descriptors(dev)
        return

    if args.ctrl_probe:
        ctrl_probe(dev)
        return

    if args.try_interfaces:
        try_interfaces(dev)
        return

    if args.watchdog:
        watchdog_test(dev, args.replay)
        usb.util.release_interface(dev, 0)
        return

    if args.replay:
        if args.mutate is not None:
            raw = bytearray(Path(args.replay).read_bytes())
            raw[args.mutate] ^= 0xFF
            tmp = "/tmp/_mutated.jpg"
            Path(tmp).write_bytes(bytes(raw))
            print(f"байт {args.mutate} инвертирован -> {tmp}")
            replay(dev, tmp, args.field, args.repeat_frames)
            usb.util.release_interface(dev, 0)
            return
        replay(dev, args.replay, args.field, args.repeat_frames)
        usb.util.release_interface(dev, 0)
        return

    if args.reset:
        recover(dev, hard=True)
        print("Готово. Если панель не ожила, передёрните кабель физически.")
        return

    if args.zlp or args.zlp_variant:
        try_zlp(dev, only=args.zlp_variant)
        usb.util.release_interface(dev, 0)
        return

    if args.try_formats or args.variant:
        try_formats(dev, only=args.variant)
        usb.util.release_interface(dev, 0)
        return

    if args.once:
        send_image(dev, render_frame(), args.field, pad=not args.no_pad)
        print("Кадр отправлен. Смотрите на панель.")
        usb.util.release_interface(dev, 0)
        return

    print(f"Готово. Обновление каждые {args.interval}с. Ctrl+C для остановки.")
    try:
        while True:
            try:
                send_image(dev, render_frame(), args.field, pad=not args.no_pad)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[error] {e}, переподключение")
                try:
                    recover(dev, hard=True)
                except Exception:
                    pass
                try:
                    usb.util.release_interface(dev, 0)
                except Exception:
                    pass
                try:
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass
                time.sleep(2)
                dev = open_device()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        try:
            usb.util.release_interface(dev, 0)
            usb.util.dispose_resources(dev)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())