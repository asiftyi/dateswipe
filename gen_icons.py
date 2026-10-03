#!/usr/bin/env python3
"""Generate DateSwipe PWA icons with pure Python (zlib+struct, no PIL).
Pink-to-red gradient rounded square with a white heart (circles + triangle)."""
import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icons")


def heart_hit(x, y, cx, cy, s):
    """True if point is inside a heart centered at (cx,cy) with size s."""
    # two circles
    r = s * 0.32
    c1 = (cx - s * 0.30, cy - s * 0.18)
    c2 = (cx + s * 0.30, cy - s * 0.18)
    if (x - c1[0]) ** 2 + (y - c1[1]) ** 2 <= r * r:
        return True
    if (x - c2[0]) ** 2 + (y - c2[1]) ** 2 <= r * r:
        return True
    # triangle below: point-in-triangle test
    ax, ay = cx - s * 0.58, cy - s * 0.02
    bx, by = cx + s * 0.58, cy - s * 0.02
    cxp, cyp = cx, cy + s * 0.62
    def sign(px, py, qx, qy, rx, ry):
        return (px - rx) * (qy - ry) - (qx - rx) * (py - ry)
    d1 = sign(x, y, ax, ay, bx, by)
    d2 = sign(x, y, bx, by, cxp, cyp)
    d3 = sign(x, y, cxp, cyp, ax, ay)
    neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (neg and pos)


def rounded_rect(x, y, size, radius):
    c = radius
    # inside if within inner rects or corner circles
    if c <= x <= size - c:
        return True
    if c <= y <= size - c:
        return True
    for qx, qy in ((c, c), (size - c, c), (c, size - c), (size - c, size - c)):
        if (x - qx) ** 2 + (y - qy) ** 2 <= c * c:
            return True
    return False


def lerp(a, b, t):
    return int(a + (b - a) * t)


def write_png(path, size):
    # gradient: rose (#ff4d6d) top-left -> violet (#8b5cf6) mid -> warm orange (#fb923c) bottom-right
    stops = [(0.0, (255, 77, 109)), (0.55, (139, 92, 246)), (1.0, (251, 146, 60))]

    def grad(t):
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0) if t1 > t0 else 0
                return tuple(lerp(c0[j], c1[j], k) for j in range(3))
        return stops[-1][1]

    radius = size * 0.22
    heart_s = size * 0.52
    hcx, hcy = size / 2, size * 0.52
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type 0
        for x in range(size):
            if not rounded_rect(x + 0.5, y + 0.5, size, radius):
                raw.extend((0, 0, 0, 0))  # transparent outside
                continue
            t = (x + y) / (2 * size)
            r, g, b = grad(t)
            if heart_hit(x + 0.5, y + 0.5, hcx, hcy, heart_s):
                r, g, b = 255, 255, 255
            raw.extend((r, g, b, 255))
    # build PNG with RGBA (color type 6)
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    print(f"wrote {path} ({len(png)} bytes)")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write_png(os.path.join(OUT, "icon-192.png"), 192)
    write_png(os.path.join(OUT, "icon-512.png"), 512)
