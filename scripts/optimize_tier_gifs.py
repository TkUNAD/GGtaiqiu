"""压缩段位 GIF，使每个文件 < 200KB（建议 < 150KB）以通过微信代码质量检查"""
from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path

from PIL import Image

TIERS_DIR = Path(__file__).resolve().parent.parent / "miniprogram" / "assets" / "tiers"
TARGET_MAX_BYTES = 150_000
SIZES = (128, 112, 96)
FRAME_COUNTS = (8, 6, 5, 4)
DURATIONS = (120, 140, 160)


def _load_gif_frames(path: Path) -> list[Image.Image]:
    im = Image.open(path)
    frames: list[Image.Image] = []
    try:
        while True:
            frames.append(im.convert("RGBA"))
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    return frames or [Image.open(path).convert("RGBA")]


def _pick_frames(frames: list[Image.Image], count: int) -> list[Image.Image]:
    if len(frames) <= count:
        return frames
    step = len(frames) / count
    return [frames[min(len(frames) - 1, int(i * step))] for i in range(count)]


def _rgba_to_p_frame(im: Image.Image) -> Image.Image:
    alpha = im.split()[3]
    rgb = im.convert("RGB")
    frame = rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=200)
    mask = Image.eval(alpha, lambda a: 255 if a < 128 else 0)
    frame.paste(255, mask)
    frame.info["transparency"] = 255
    return frame


def _encode_gif(frames: list[Image.Image], duration: int) -> bytes:
    p_frames = [_rgba_to_p_frame(f) for f in frames]
    buf = BytesIO()
    p_frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=p_frames[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return buf.getvalue()


def compress_gif(path: Path) -> int:
    raw_frames = _load_gif_frames(path)
    best = path.read_bytes()
    if len(best) <= TARGET_MAX_BYTES:
        return len(best)

    for size in SIZES:
        base = [f.resize((size, size), Image.Resampling.LANCZOS) for f in raw_frames]
        for n in FRAME_COUNTS:
            picked = _pick_frames(base, n)
            for dur in DURATIONS:
                data = _encode_gif(picked, dur)
                if len(data) < len(best):
                    best = data
                if len(data) <= TARGET_MAX_BYTES:
                    path.write_bytes(data)
                    return len(data)

    path.write_bytes(best)
    return len(best)


def main() -> None:
    if not TIERS_DIR.is_dir():
        raise SystemExit(f"目录不存在: {TIERS_DIR}")

    total = 0
    failed = []
    for p in sorted(TIERS_DIR.glob("tier-*.gif")):
        before = p.stat().st_size
        after = compress_gif(p)
        total += after
        status = "OK" if after <= 200_000 else "WARN>200K"
        print(f"{p.name}: {before // 1024}KB -> {after // 1024}KB [{status}]")
        if after > 200_000:
            failed.append(p.name)

    print(f"total tiers GIF: {total // 1024} KB")
    if failed:
        raise SystemExit(f"仍超过 200KB: {', '.join(failed)}")


if __name__ == "__main__":
    main()
