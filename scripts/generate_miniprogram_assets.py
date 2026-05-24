"""生成小程序 tabBar 图标与默认头像占位 PNG（建议 81×81）"""
import os
import struct
import zlib

ROOT = os.path.join(os.path.dirname(__file__), "..", "miniprogram", "assets")
ICON_SIZE = 81


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def write_png(path: str, width: int, height: int, pixels) -> None:
    """pixels: list of (r,g,b,a) row-major"""
    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            r, g, b, a = pixels[y * width + x]
            raw += bytes([r, g, b, a])
    compressed = zlib.compress(raw, 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", compressed)
    png += _png_chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)


def _blank(w, h, rgba=(0, 0, 0, 0)):
    return [rgba] * (w * h)


def _fill_rect(px, w, h, x0, y0, x1, y1, rgba):
    for y in range(max(0, y0), min(h, y1)):
        for x in range(max(0, x0), min(w, x1)):
            px[y * w + x] = rgba


def _icon_home(w, h, color):
    px = _blank(w, h)
    c = color
    _fill_rect(px, w, h, 28, 38, 53, 58, c)
    _fill_rect(px, w, h, 20, 28, 61, 40, c)
    _fill_rect(px, w, h, 36, 48, 45, 58, (10, 15, 26, 255))
    return px


def _icon_rank(w, h, color):
    px = _blank(w, h)
    c = color
    for i, (x, bh) in enumerate([(22, 22), (36, 34), (50, 28)]):
        _fill_rect(px, w, h, x, 58 - bh, x + 10, 58, c)
    _fill_rect(px, w, h, 18, 58, 63, 62, c)
    return px


def _icon_shop(w, h, color):
    px = _blank(w, h)
    c = color
    _fill_rect(px, w, h, 24, 32, 57, 58, c)
    _fill_rect(px, w, h, 20, 28, 61, 36, c)
    _fill_rect(px, w, h, 30, 22, 51, 30, c)
    return px


def _icon_user(w, h, color):
    px = _blank(w, h)
    c = color
    cx, cy, r = 40, 26, 10
    for y in range(h):
        for x in range(w):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                px[y * w + x] = c
    _fill_rect(px, w, h, 24, 44, 57, 62, c)
    return px


DRAWERS = {
    "home": _icon_home,
    "rank": _icon_rank,
    "shop": _icon_shop,
    "user": _icon_user,
}


def main():
    gray = (107, 114, 128, 255)
    gold = (212, 175, 55, 255)
    avatar_bg = (26, 34, 54, 255)
    w = h = ICON_SIZE
    for key, drawer in DRAWERS.items():
        write_png(os.path.join(ROOT, f"{key}.png"), w, h, drawer(w, h, gray))
        write_png(os.path.join(ROOT, f"{key}-active.png"), w, h, drawer(w, h, gold))
    write_png(os.path.join(ROOT, "default-avatar.png"), 120, 120, _blank(120, 120, avatar_bg))
    print(f"Generated assets in {ROOT}")


if __name__ == "__main__":
    main()
