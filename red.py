"""Тест: заливаем Trofeo Vision LCD красным через hidapi (JPEG mode)."""
import hid
import io
import struct
from PIL import Image

VID, PID = 0x0416, 0x5302
WIDTH, HEIGHT = 1280, 480

def handshake(dev):
    payload = bytearray(512)
    payload[0:4] = b"\xDA\xDB\xDC\xDD"
    payload[12] = 0x01
    dev.write(bytes([0x00]) + bytes(payload))
    resp = dev.read(512, timeout=2000)
    if bytes(resp[:4]) != b"\xDA\xDB\xDC\xDD":
        raise RuntimeError(f"bad magic: {bytes(resp[:4]).hex()}")
    # ВНИМАНИЕ: pm = resp[5], sub = resp[4]
    print(f"  PM=0x{resp[5]:02x} SUB=0x{resp[4]:02x}")
    return resp

def make_solid_jpeg(r, g, b, w=WIDTH, h=HEIGHT, quality=85):
    img = Image.new("RGB", (w, h), (r, g, b))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

def build_frame_packet_jpeg(jpeg_data, w=WIDTH, h=HEIGHT):
    header = bytearray()
    header += b"\xDA\xDB\xDC\xDD"               # magic
    header += b"\x02\x00"                        # cmd_type = PICTURE
    header += b"\x00\x00"                        # mode = 0 (JPEG, не RGB565)
    header += struct.pack("<HH", w, h)           # actual width, height
    header += b"\x02\x00\x00\x00"                # sub-flag
    header += struct.pack("<I", len(jpeg_data))  # data length LE32
    # header = 20 bytes

    raw = bytes(header) + jpeg_data
    padded_len = ((len(raw) + 511) // 512) * 512
    return raw.ljust(padded_len, b"\x00")

def main():
    dev = hid.Device(vid=VID, pid=PID)

    print("Handshake…")
    handshake(dev)

    print("Создаём JPEG (красный)…")
    jpeg = make_solid_jpeg(255, 0, 0)
    print(f"  JPEG: {len(jpeg)} bytes (magic: {jpeg[:2].hex()})")

    print("Собираем packet…")
    packet = build_frame_packet_jpeg(jpeg)
    print(f"  Packet: {len(packet)} bytes")

    print("Отправляем одним write…")
    n = dev.write(bytes([0x00]) + packet)
    print(f"  записано: {n} байт")

    dev.close()
    print("Готово")

if __name__ == "__main__":
    main()