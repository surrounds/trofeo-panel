"""Зонд для Trofeo Vision LCD (0416:5302) через hidapi на macOS."""
import hid
import sys
import time

VID, PID = 0x0416, 0x5302

# 1. Перечисление — посмотрим все интерфейсы устройства
print("=== Enumerate ===")
found = list(hid.enumerate(VID, PID))
if not found:
    print(f"  Устройство {VID:04x}:{PID:04x} не найдено через hidapi.")
    sys.exit(1)

for i, d in enumerate(found):
    print(f"  [{i}] interface={d.get('interface_number')} "
          f"usage_page={d.get('usage_page')} usage={d.get('usage')}")
    print(f"      path={d['path']}")
    print(f"      product={d.get('product_string')!r}")
    print(f"      serial={d.get('serial_number')!r}")

# 2. Открываем устройство (по умолчанию первый интерфейс)
print("\n=== Open ===")
try:
    dev = hid.Device(vid=VID, pid=PID)
except Exception as e:
    print(f"  Не открылось: {e}")
    sys.exit(1)

print(f"  manufacturer = {dev.manufacturer!r}")
print(f"  product      = {dev.product!r}")
print(f"  serial       = {dev.serial!r}")

# 3. Handshake DA DB DC DD
print("\n=== Handshake ===")
# 1 byte Report ID (0) + 512 bytes payload
payload = bytearray(512)
payload[0:4] = b"\xDA\xDB\xDC\xDD"
payload[12]  = 0x01  # command: device info
out = bytes([0x00]) + bytes(payload)

print(f"  TX: {len(out)} bytes, head = {out[1:24].hex()}")
try:
    n = dev.write(out)
    print(f"  записано: {n} байт")
except Exception as e:
    print(f"  ошибка write: {e}")
    sys.exit(1)

# Читаем ответ
time.sleep(0.1)
try:
    resp = dev.read(512, timeout=2000)
    print(f"\n  RX: {len(resp)} bytes")
    if resp:
        print(f"  first 64 bytes hex: {bytes(resp[:64]).hex()}")
        print(f"  magic [0:4] (ожидаем DA DB DC DD): {bytes(resp[:4]).hex()}")
        print(f"  status [12] (ожидаем 01): {resp[12]:02x}")
        print(f"  flag [16] (ожидаем 10): {resp[16]:02x}")
except Exception as e:
    print(f"  ошибка read: {e}")

dev.close()
