"""Re-compress tier PNGs under miniprogram/assets/tiers (keep package < 2MB)."""
from io import BytesIO
from pathlib import Path

from PIL import Image

TIERS_DIR = Path(__file__).resolve().parent.parent / "miniprogram" / "assets" / "tiers"
TARGET = 256


def compress_file(path: Path) -> int:
    im = Image.open(path).convert("RGBA")
    im = im.resize((TARGET, TARGET), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True, compress_level=9)
    data = buf.getvalue()
    if len(data) > 100_000:
        im = im.resize((128, 128), Image.Resampling.LANCZOS)
        buf = BytesIO()
        im.save(buf, format="PNG", optimize=True, compress_level=9)
        data = buf.getvalue()
    path.write_bytes(data)
    return len(data)


def main():
    total = 0
    for p in sorted(TIERS_DIR.glob("tier-*.png")):
        n = compress_file(p)
        total += n
        print(f"{p.name}: {n // 1024} KB")
    print(f"total tiers: {total // 1024} KB")


if __name__ == "__main__":
    main()
