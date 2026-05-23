"""[已弃用] 请使用 build_tier_assets.py。Remove only edge-connected background."""
from collections import deque
from pathlib import Path

from PIL import Image

SRC_DIR = Path(
    r"C:\Users\Administrator\.cursor\projects\f-AI-tqxm-weixin-xiaochengxu-1-20260518\assets"
)
OUT_DIR = Path(__file__).resolve().parent.parent / "miniprogram" / "assets" / "tiers"

FILES = [
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_1-5d2ae03f-c520-4163-b400-a9885cc5bed1.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_2-0427d468-bf9e-47b9-a866-1650266679da.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_3-92fae80c-9a0f-4e59-8056-5b726ba15932.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_4-4c69fc3d-bded-48ad-b60e-576bac80951c.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_5-2973d7ed-ae4a-4a91-a404-18e216f8248d.png",
    "c__Users_Administrator_AppData_Roaming_Cursor_User_workspaceStorage_34c2ed0fa449449e5582952b751f60df_images_6-6ab3d460-c340-45aa-b832-22d1d91b92c6.png",
]

OUTPUT_SIZE = 256


def is_edge_background(r: int, g: int, b: int, a: int) -> bool:
    """Only pure white / checkerboard — do not touch emblem metal or colors."""
    if a < 12:
        return True
    if r > 248 and g > 248 and b > 248:
        return True
    # Photoshop checkerboard ~#c0c0c0 / #ffffff alternation
    if abs(r - g) < 6 and abs(g - b) < 6 and 192 <= r <= 208:
        return True
    if abs(r - g) < 6 and abs(g - b) < 6 and 238 <= r <= 255:
        return True
    return False


def flood_remove_background(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    seen = set()
    q = deque()

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


def process_one(src: Path, dest: Path, pad_ratio: float = 0.05) -> None:
    im = flood_remove_background(Image.open(src))
    bbox = im.getbbox()
    if not bbox:
        im.save(dest, format="PNG", optimize=True, compress_level=9)
        return

    im = im.crop(bbox)
    cw, ch = im.size
    side = max(cw, ch)
    pad = int(side * pad_ratio)
    canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
    ox = (side + pad * 2 - cw) // 2
    oy = (side + pad * 2 - ch) // 2
    canvas.paste(im, (ox, oy), im)
    canvas = canvas.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="PNG", optimize=True, compress_level=9)
    print(f"OK {dest.name} <- {src.name} ({dest.stat().st_size // 1024} KB)")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(FILES, start=1):
        src = SRC_DIR / name
        if not src.exists():
            raise FileNotFoundError(src)
        process_one(src, OUT_DIR / f"tier-{i}.png")
    print("Done:", OUT_DIR)


if __name__ == "__main__":
    main()
