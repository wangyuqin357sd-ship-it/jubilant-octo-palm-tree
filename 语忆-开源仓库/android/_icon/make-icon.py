"""生成语忆 App 图标（多密度 PNG）。放 android/_icon/make-icon.py，产物进 android/res/mipmap-*/。"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "res")

BG_TOP = (56, 116, 168)      # 深青蓝
BG_BOT = (28, 68, 112)
FG = (255, 255, 255)

DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make(size):
    ss = size * 4  # 超采样，边缘更干净
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))

    # 竖向渐变底
    grad = Image.new("RGB", (1, ss))
    for y in range(ss):
        t = y / max(1, ss - 1)
        grad.putpixel((0, y), tuple(
            int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
    grad = grad.resize((ss, ss))

    # 圆角遮罩
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, ss - 1, ss - 1], radius=int(ss * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    font = load_font(int(ss * 0.56))
    text = "忆"
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((ss - w) / 2 - box[0], (ss - h) / 2 - box[1]), text, font=font, fill=FG)

    # 右下角一个小话筒点，暗示语音
    r = int(ss * 0.075)
    cx, cy = int(ss * 0.755), int(ss * 0.755)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 214, 102, 255))

    return img.resize((size, size), Image.LANCZOS)


for folder, px in DENSITIES.items():
    out = os.path.join(RES, folder)
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, "ic_launcher.png")
    make(px).save(p, "PNG", optimize=True)
    print("wrote", p, px)
print("done")