"""生成小程序 TabBar 图标与默认头像（81x81 PNG）"""
import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("请先安装: pip install pillow")
    raise

ROOT = Path(__file__).resolve().parent.parent / "miniprogram" / "assets"
SIZE = 81

ICONS = {
    "home": ((107, 33, 168), (37, 99, 235)),
    "rank": ((107, 33, 168), (37, 99, 235)),
    "shop": ((107, 33, 168), (37, 99, 235)),
    "user": ((107, 33, 168), (37, 99, 235)),
}


def make_icon(name: str, active: bool):
    c1, c2 = ICONS[name]
    color = c2 if active else (196, 181, 253)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 14
    draw.rounded_rectangle(
        [margin, margin, SIZE - margin, SIZE - margin],
        radius=12,
        fill=color + (255,),
    )
    if name == "home":
        draw.polygon([(40, 28), (58, 42), (58, 58), (22, 58), (22, 42)], fill=(255, 255, 255, 230))
    elif name == "rank":
        draw.rectangle([26, 48, 34, 58], fill=(255, 255, 255, 230))
        draw.rectangle([37, 38, 45, 58], fill=(255, 255, 255, 230))
        draw.rectangle([48, 28, 56, 58], fill=(255, 255, 255, 230))
    elif name == "shop":
        draw.rectangle([24, 32, 58, 52], outline=(255, 255, 255, 230), width=3)
        draw.line([(24, 38), (58, 38)], fill=(255, 255, 255, 230), width=2)
    else:
        draw.ellipse([30, 24, 52, 46], fill=(255, 255, 255, 230))
        draw.arc([24, 40, 58, 62], 20, 160, fill=(255, 255, 255, 230), width=3)
    suffix = "-active" if active else ""
    img.save(ROOT / f"{name}{suffix}.png")


def make_avatar():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, SIZE - 4, SIZE - 4], fill=(124, 58, 237, 255))
    draw.ellipse([24, 20, 58, 54], fill=(233, 213, 255, 255))
    draw.arc([18, 44, 64, 78], 10, 170, fill=(233, 213, 255, 255), width=6)
    img.save(ROOT / "default-avatar.png")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        make_icon(name, False)
        make_icon(name, True)
    make_avatar()
    print("已生成到", ROOT)


if __name__ == "__main__":
    main()
