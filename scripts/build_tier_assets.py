"""
段位资源：1_1~6_1 去黑底 → 透明 PNG + 循环动图 GIF
"""
from __future__ import annotations

import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageEnhance

SRC_DIR = Path(
    r"C:\Users\Administrator\.cursor\projects\f-AI-tqxm-weixin-xiaochengxu-1-20260518\assets"
)
OUT_DIR = Path(__file__).resolve().parent.parent / "miniprogram" / "assets" / "tiers"

# 低→高：1_1 … 6_1
SOURCES = [
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_1_1-a98a4e4a-caff-4072-967a-7403ba9cad71.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_2_1-348954c3-1876-4c9b-85e3-5b1019fd0725.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_3_1-5a489396-0c69-413e-9fab-92d4ce74b2d0.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_4_1-46efc82f-6f1b-479f-be0b-211bffa78f75.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_5_1-4a261bd3-8439-4047-b8e5-555acf26c014.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_6_1-943907ed-ec3e-4c22-975c-e0e8ae75c959.png",
]

OUTPUT_SIZE = 168
GIF_FRAMES = 8
GIF_DURATION_MS = 120
SAVE_PNG = False


def is_edge_background(r: int, g: int, b: int, a: int) -> bool:
    if a < 12:
        return True
    if r > 248 and g > 248 and b > 248:
        return True
    if r < 28 and g < 28 and b < 28:
        return True
    if abs(r - g) < 6 and abs(g - b) < 6 and 192 <= r <= 208:
        return True
    return False


def flood_remove_background(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    seen: set[tuple[int, int]] = set()
    q: deque[tuple[int, int]] = deque()

    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))

    while q:
        x, y = q.popleft()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        r, g, b, a = px[x, y]
        if not is_edge_background(r, g, b, a):
            continue
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                q.append((nx, ny))
    return im


def crop_center_square(im: Image.Image, pad_ratio: float = 0.04) -> Image.Image:
    bbox = im.getbbox()
    if not bbox:
        return im
    im = im.crop(bbox)
    cw, ch = im.size
    side = max(cw, ch)
    pad = int(side * pad_ratio)
    canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
    ox = (side + pad * 2 - cw) // 2
    oy = (side + pad * 2 - ch) // 2
    canvas.paste(im, (ox, oy), im)
    return canvas.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)


def rgba_to_gif_frame(im: Image.Image) -> Image.Image:
    alpha = im.split()[3]
    rgb = im.convert("RGB")
    frame = rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    mask = Image.eval(alpha, lambda a: 255 if a < 128 else 0)
    frame.paste(255, mask)
    frame.info["transparency"] = 255
    return frame


def make_shimmer_gif(base: Image.Image, dest: Path, tier_index: int) -> None:
    """段位越高，光晕幅度略大。"""
    amp = 0.04 + tier_index * 0.004
    bright_amp = 0.05 + tier_index * 0.005
    frames_p: list[Image.Image] = []

    for i in range(GIF_FRAMES):
        t = (i / GIF_FRAMES) * 2 * math.pi
        scale = 1.0 + amp * math.sin(t)
        bright = 0.94 + bright_amp * math.sin(t + 0.5)

        sw = max(1, int(OUTPUT_SIZE * scale))
        sh = max(1, int(OUTPUT_SIZE * scale))
        scaled = base.resize((sw, sh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (OUTPUT_SIZE, OUTPUT_SIZE), (0, 0, 0, 0))
        ox = (OUTPUT_SIZE - sw) // 2
        oy = (OUTPUT_SIZE - sh) // 2
        canvas.paste(scaled, (ox, oy), scaled)
        canvas = ImageEnhance.Brightness(canvas).enhance(bright)
        frames_p.append(rgba_to_gif_frame(canvas))

    frames_p[0].save(
        dest,
        save_all=True,
        append_images=frames_p[1:],
        duration=GIF_DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )


def process_tier(index: int, src_name: str) -> None:
    src = SRC_DIR / src_name
    if not src.exists():
        raise FileNotFoundError(src)

    base = crop_center_square(flood_remove_background(Image.open(src)))
    png_path = OUT_DIR / f"tier-{index}.png"
    gif_path = OUT_DIR / f"tier-{index}.gif"

    if SAVE_PNG:
        base.save(png_path, format="PNG", optimize=True, compress_level=9)
    elif png_path.exists():
        png_path.unlink()
    make_shimmer_gif(base, gif_path, index)

    print(f"tier-{index}: gif {gif_path.stat().st_size // 1024}KB")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(SOURCES, start=1):
        process_tier(i, name)

    mp = Path(__file__).resolve().parent.parent / "miniprogram"
    total = sum(f.stat().st_size for f in mp.rglob("*") if f.is_file()) / 1024
    print(f"miniprogram total: {total:.1f} KB")


if __name__ == "__main__":
    main()
