"""生成小程序 TabBar 精美图标 (81x81)"""
import os
import struct
import zlib

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE = os.path.join(os.path.dirname(__file__), "..", "miniprogram", "assets")
SIZE = 81

# 紫蓝主题色
COLOR_NORMAL = (167, 139, 250, 255)   # #A78BFA
COLOR_ACTIVE = (255, 255, 255, 255)   # #FFFFFF
BG = (0, 0, 0, 0)


def png_raw(w, h, pixels):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join([b"\x00" + pixels[y] for y in range(h)])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def save_pil(img, path):
    img.save(path, "PNG")


def draw_home(draw, c, active):
    # 房屋：屋顶三角 + 方体
    roof = [(40, 18), (62, 38), (18, 38)]
    draw.polygon(roof, fill=c)
    draw.rounded_rectangle([22, 36, 58, 62], radius=4, fill=c)
    if active:
        draw.rectangle([34, 46, 46, 62], fill=(107, 33, 168, 180))


def draw_rank(draw, c, active):
    # 领奖台三根柱
    bars = [(14, 52, 28, 62), (32, 38, 48, 62), (52, 46, 66, 62)]
    for x1, y1, x2, y2 in bars:
        draw.rounded_rectangle([x1, y1, x2, y2], radius=3, fill=c)
    if active:
        draw.ellipse([34, 14, 46, 26], fill=c)
        draw.polygon([(28, 22), (40, 10), (52, 22)], fill=c)


def draw_shop(draw, c, active):
    # 购物袋
    draw.rounded_rectangle([24, 32, 56, 62], radius=6, fill=c)
    draw.arc([28, 18, 52, 40], 180, 0, fill=c, width=4)
    if active:
        draw.ellipse([36, 44, 44, 52], fill=(107, 33, 168, 200))


def draw_user(draw, c, active):
    # 头像 + 肩
    draw.ellipse([30, 16, 50, 36], fill=c)
    draw.chord([18, 38, 62, 68], 0, 180, fill=c)
    if active:
        draw.ellipse([33, 20, 47, 32], fill=(147, 197, 253, 120))


def gen_with_pil():
    os.makedirs(BASE, exist_ok=True)
    icons = [
        ("home", draw_home),
        ("rank", draw_rank),
        ("shop", draw_shop),
        ("user", draw_user),
    ]
    for name, fn in icons:
        for suffix, color, active in [("", COLOR_NORMAL, False), ("-active", COLOR_ACTIVE, True)]:
            img = Image.new("RGBA", (SIZE, SIZE), BG)
            draw = ImageDraw.Draw(img)
            fn(draw, color, active)
            save_pil(img, os.path.join(BASE, f"{name}{suffix}.png"))
    print("PIL icons generated:", BASE)


def gen_fallback():
    """无 Pillow 时生成简单色块（备用）"""
    os.makedirs(BASE, exist_ok=True)
    for name, c in [
        ("home", COLOR_NORMAL), ("home-active", COLOR_ACTIVE),
        ("rank", COLOR_NORMAL), ("rank-active", COLOR_ACTIVE),
        ("shop", COLOR_NORMAL), ("shop-active", COLOR_ACTIVE),
        ("user", COLOR_NORMAL), ("user-active", COLOR_ACTIVE),
        ("default-avatar", (124, 58, 237, 255)),
    ]:
        row = bytes([c[0], c[1], c[2], c[3]] * SIZE)
        pixels = [row] * SIZE
        with open(os.path.join(BASE, f"{name}.png"), "wb") as f:
            f.write(png_raw(SIZE, SIZE, pixels))
    print("fallback icons generated")


if __name__ == "__main__":
    if HAS_PIL:
        gen_with_pil()
    else:
        print("Pillow not installed, trying pip install pillow...")
        import subprocess
        subprocess.check_call(["pip", "install", "pillow", "-q"])
        from PIL import Image, ImageDraw
        globals()["Image"] = Image
        globals()["ImageDraw"] = ImageDraw
        globals()["HAS_PIL"] = True
        gen_with_pil()
