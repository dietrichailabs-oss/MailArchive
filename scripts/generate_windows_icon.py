from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png_rgba(size: int) -> bytes:
    # Deterministic Dietrich AI Labs / MailArchive-style icon: dark rounded tile,
    # blue archive tray, and a white mail envelope. No external imaging library.
    px = bytearray(size * size * 4)

    def put(x: int, y: int, rgba: tuple[int, int, int, int]):
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            px[i:i+4] = bytes(rgba)

    def rect(x0, y0, x1, y1, rgba):
        for y in range(max(0, y0), min(size, y1)):
            for x in range(max(0, x0), min(size, x1)):
                put(x, y, rgba)

    def rounded_rect(x0, y0, x1, y1, radius, rgba):
        r2 = radius * radius
        for y in range(y0, y1):
            for x in range(x0, x1):
                cx = min(max(x, x0 + radius), x1 - radius - 1)
                cy = min(max(y, y0 + radius), y1 - radius - 1)
                if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                    put(x, y, rgba)

    dark = (18, 24, 33, 255)
    blue = (35, 132, 255, 255)
    blue2 = (78, 166, 255, 255)
    white = (244, 248, 255, 255)
    transparent = (0, 0, 0, 0)
    rect(0, 0, size, size, transparent)
    pad = max(1, size // 16)
    rounded_rect(pad, pad, size-pad, size-pad, max(2, size//7), dark)

    tray_x0, tray_x1 = size * 3 // 16, size * 13 // 16
    tray_y0, tray_y1 = size * 9 // 16, size * 13 // 16
    rounded_rect(tray_x0, tray_y0, tray_x1, tray_y1, max(1, size//20), blue)
    rect(size * 5 // 16, size * 10 // 16, size * 11 // 16, size * 11 // 16, blue2)

    ex0, ex1 = size * 4 // 16, size * 12 // 16
    ey0, ey1 = size * 4 // 16, size * 9 // 16
    rounded_rect(ex0, ey0, ex1, ey1, max(1, size//28), white)
    # Dark-blue envelope folds.
    fold = (42, 104, 184, 255)
    mid = (ex0 + ex1) // 2
    for y in range(ey0, ey1):
        span = max(0, (y - ey0) * (ex1 - ex0) // max(1, 2 * (ey1 - ey0)))
        for x in range(ex0, ex0 + span):
            put(x, y, fold)
        for x in range(ex1 - span, ex1):
            put(x, y, fold)
    # Central V fold line.
    for i in range(max(1, size // 32)):
        for x in range(ex0, ex1):
            rel = x - ex0
            half = max(1, (ex1 - ex0) // 2)
            y = ey0 + abs(rel - half) * (ey1 - ey0) // half // 2 + i
            put(x, y, fold)

    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)
        raw.extend(px[y*stride:(y+1)*stride])
    signature = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b'IHDR', ihdr) + _png_chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + _png_chunk(b'IEND', b'')


def build_ico(sizes=(16, 24, 32, 48, 64, 128, 256)) -> bytes:
    images = [(size, _png_rgba(size)) for size in sizes]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, png in images:
        dim = 0 if size == 256 else size
        entries.extend(struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(png), offset))
        payload.extend(png)
        offset += len(png)
    return header + bytes(entries) + bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build_ico()
    path.write_bytes(data)
    print(f'MAILARCHIVE_ICON_GENERATED path={path} bytes={len(data)} sha_source=deterministic-v1')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
