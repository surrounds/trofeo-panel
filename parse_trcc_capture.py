#!/usr/bin/env python3
"""
Разбор дампа USB-трафика TRCC для панели USBDISPLAY (0416:5408).

Требуется tshark (ставится вместе с Wireshark). Работает и на Windows,
и на macOS, так что .pcapng можно разбирать где удобно.

Использование:
    python3 parse_trcc_capture.py capture.pcapng
    python3 parse_trcc_capture.py capture.pcapng --max 40 --bytes 96
    python3 parse_trcc_capture.py capture.pcapng --all-directions
"""
import argparse
import shutil
import subprocess
import sys
from collections import Counter

TSHARK_CANDIDATES = [
    "tshark",
    r"C:\Program Files\Wireshark\tshark.exe",
    r"C:\Program Files (x86)\Wireshark\tshark.exe",
    "/Applications/Wireshark.app/Contents/MacOS/tshark",
]

JPEG_SOI = "ffd8ff"


def find_tshark():
    for c in TSHARK_CANDIDATES:
        p = shutil.which(c) if not c.endswith(".exe") and "/" not in c and "\\" not in c else c
        if p and (shutil.which(p) or __import__("os").path.exists(p)):
            return p
    return None


def run_tshark(exe, path, out_only):
    fields = ["frame.number", "usb.transfer_type", "usb.endpoint_address",
              "usb.endpoint_address.direction", "usb.data_len", "usb.capdata"]
    disp = "usb.transfer_type == 0x03"
    if out_only:
        disp += " && usb.endpoint_address.direction == 0"
    cmd = [exe, "-r", path, "-Y", disp, "-T", "fields"]
    for f in fields:
        cmd += ["-e", f]
    cmd += ["-E", "separator=|"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    return res.stdout.splitlines()


def parse_rows(lines):
    rows = []
    for line in lines:
        parts = line.split("|")
        if len(parts) < 6:
            continue
        frame, ttype, epaddr, direction, dlen, capdata = parts[:6]
        data = capdata.replace(":", "").replace(",", "").strip()
        try:
            length = int(dlen) if dlen else len(data) // 2
        except ValueError:
            length = len(data) // 2
        rows.append({
            "frame": frame,
            "ep": epaddr,
            "dir": "OUT" if direction == "0" else "IN",
            "len": length,
            "data": data,
        })
    return rows


def hexdump(h, width=16):
    out = []
    for i in range(0, len(h), width * 2):
        chunk = h[i:i + width * 2]
        pairs = " ".join(chunk[j:j + 2] for j in range(0, len(chunk), 2))
        ascii_ = "".join(
            chr(int(chunk[j:j + 2], 16))
            if 32 <= int(chunk[j:j + 2], 16) < 127 else "."
            for j in range(0, len(chunk), 2))
        out.append(f"    {i // 2:04x}  {pairs:<47}  {ascii_}")
    return "\n".join(out)


def analyze(rows, nbytes):
    print("\n" + "=" * 68)
    print("АНАЛИЗ")
    print("=" * 68)

    outs = [r for r in rows if r["dir"] == "OUT"]
    if not outs:
        print("Bulk OUT передач не найдено. Проверьте, что выбран верный "
              "USBPcap-интерфейс и что захват шёл во время работы TRCC.")
        return

    sizes = Counter(r["len"] for r in outs)
    print(f"\nВсего bulk OUT передач: {len(outs)}")
    print("Самые частые размеры:")
    for size, cnt in sizes.most_common(8):
        print(f"  {size:>9} байт  x{cnt}")

    big = [r for r in outs if r["len"] > 4096]
    small = [r for r in outs if r["len"] <= 4096]
    print(f"\nКрупных передач (>4096): {len(big)}, мелких: {len(small)}")

    prefixes = Counter(r["data"][:8] for r in outs if r["data"])
    print("\nЧастые первые 4 байта (кандидаты в magic):")
    for pfx, cnt in prefixes.most_common(6):
        print(f"  {pfx}  x{cnt}")

    with_jpeg = [r for r in outs if JPEG_SOI in r["data"][:512]]
    if with_jpeg:
        r = with_jpeg[0]
        off = r["data"].index(JPEG_SOI) // 2
        print(f"\nJPEG SOI (ffd8ff) найден в передаче frame={r['frame']} "
              f"по смещению {off} байт.")
        if off:
            print(f"  => заголовок кадра занимает {off} байт и идёт "
                  f"в одной передаче с картинкой")
            print("  Заголовок:")
            print(hexdump(r["data"][:off * 2]))
        else:
            print("  => картинка идёт без заголовка, "
                  "заголовок должен быть отдельной передачей")
    else:
        print("\nJPEG SOI не найден. Вероятно, панель принимает сырые пиксели, "
              "а не JPEG. Сверьте размер крупных передач с "
              "1920*400*2 = 1536000 (RGB565) или *3 = 2304000 (RGB888).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", help="файл .pcapng от Wireshark/USBPcap")
    ap.add_argument("--max", type=int, default=25,
                    help="сколько передач показать подробно")
    ap.add_argument("--bytes", type=int, default=64,
                    help="сколько байт каждой передачи печатать")
    ap.add_argument("--all-directions", action="store_true",
                    help="показывать и IN тоже")
    args = ap.parse_args()

    exe = find_tshark()
    if not exe:
        print("tshark не найден. Установите Wireshark и убедитесь, что "
              "tshark доступен в PATH.", file=sys.stderr)
        sys.exit(1)

    rows = parse_rows(run_tshark(exe, args.capture, not args.all_directions))
    if not rows:
        print("Bulk-передач в дампе нет.")
        return

    print(f"Найдено передач: {len(rows)}. Первые {min(args.max, len(rows))}:\n")
    for r in rows[:args.max]:
        head = r["data"][:args.bytes * 2]
        print(f"[frame {r['frame']:>6}] {r['dir']} ep={r['ep']} "
              f"len={r['len']}")
        if head:
            print(hexdump(head))
        print()

    analyze(rows, args.bytes)


if __name__ == "__main__":
    main()
