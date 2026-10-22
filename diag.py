"""Диагностика стабильности отправки кадров на Trofeo Vision LCD."""
import hid, io, struct, time
from PIL import Image, ImageDraw, ImageFont

VID, PID = 0x0416, 0x5302
WIDTH, HEIGHT = 1280, 480
DELAY = 0.5   # 20 fps

def make_jpeg(idx):
    img = Image.new("RGB", (WIDTH, HEIGHT), (20, 30, 50))
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 250)
    except Exception:
        f = ImageFont.load_default()
    d.text((WIDTH//2 - 200, 100), f"#{idx}", fill=(255, 255, 255), font=f)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

def build_packet(jpeg):
    header = (
        b"\xDA\xDB\xDC\xDD"
        + b"\x02\x00\x00\x00"
        + struct.pack("<HH", WIDTH, HEIGHT)
        + b"\x02\x00\x00\x00"
        + struct.pack("<I", len(jpeg))
    )
    raw = header + jpeg
    padded = ((len(raw) + 511) // 512) * 512
    return raw.ljust(padded, b"\x00")

print("Открываем устройство…")
dev = hid.Device(vid=VID, pid=PID)

# handshake — best effort, не критично
try:
    p = bytearray(512); p[0:4] = b"\xDA\xDB\xDC\xDD"; p[12] = 0x01
    dev.write(bytes([0x00]) + bytes(p))
    r = dev.read(512, timeout=2000)
    print(f"  handshake: {bytes(r[:4]).hex() if r else 'no response'}")
except Exception as e:
    print(f"  handshake skipped: {e}")

print(f"Шлём кадры, delay={DELAY*1000:.0f}ms...")
fails = 0
for i in range(200):
    try:
        jpeg = make_jpeg(i)
        packet = build_packet(jpeg)
        t0 = time.time()
        n = dev.write(bytes([0x00]) + packet)
        t1 = time.time()

        # Попытка дренажа input buffer (non-blocking)
        drained = b""
        try:
            drained = dev.read(64, timeout=1)
        except Exception:
            pass

        print(f"#{i:3d} jpeg={len(jpeg):6d} packet={len(packet):6d} "
              f"write={1000*(t1-t0):5.1f}ms  drain={len(drained)}B"
              f"{(' '+drained[:8].hex()) if drained else ''}")
        time.sleep(DELAY)
    except Exception as e:
        fails += 1
        print(f"#{i:3d} FAIL: {e}")
        if fails > 3:
            break
        time.sleep(0.5)

dev.close()
print("Готово.")
