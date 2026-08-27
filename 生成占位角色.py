# -*- coding: utf-8 -*-
"""生成占位角色图（大肥鱼），输出透明 PNG：
- 常态：character.png（侧）+ character_front.png（正）
- 吃饱：character_full.png（侧）+ character_full_front.png（正）
用法：python 生成占位角色.py
"""
import os
from PIL import Image, ImageDraw

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.LANCZOS

ORANGE = (255, 179, 71, 255)
ORANGE_DK = (232, 142, 52, 255)
FIN = (255, 150, 60, 255)
FIN_DK = (240, 130, 50, 255)
BELLY = (255, 232, 188, 255)
BLUSH = (255, 150, 150, 170)
EYE_DK = (45, 45, 45, 255)


def _eye_round(d, P, cx, cy):
    d.ellipse([P(cx - 20, cy - 18), P(cx + 20, cy + 18)], fill=(255, 255, 255, 255))
    d.ellipse([P(cx - 12, cy - 10), P(cx + 12, cy + 14)], fill=EYE_DK)
    d.ellipse([P(cx - 8, cy - 6), P(cx + 1, cy + 3)], fill=(255, 255, 255, 255))


def _eye_happy(d, P, S, cx, cy):
    # 满意的闭眼弯眉（^^）
    d.arc([P(cx - 18, cy - 6), P(cx + 18, cy + 14)], start=200, end=340, fill=EYE_DK, width=S)


def draw_side(full=False):
    S = 4
    W, H = 240, 240
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return (x * S, y * S)

    # 尾巴（右侧）
    d.polygon([P(160, 95), P(215, 60), P(205, 130)], fill=FIN)
    d.polygon([P(160, 120), P(220, 145), P(190, 160)], fill=FIN_DK)
    # 身体（吃饱时更圆胖）
    if full:
        d.ellipse([P(28, 38), P(192, 178)], fill=ORANGE, outline=ORANGE_DK, width=S)
    else:
        d.ellipse([P(40, 45), P(180, 165)], fill=ORANGE, outline=ORANGE_DK, width=S)
    # 肚皮（吃饱时更大更低）
    if full:
        d.ellipse([P(40, 74), P(180, 174)], fill=BELLY)
    else:
        d.ellipse([P(55, 80), P(160, 160)], fill=BELLY)
    # 背鳍
    d.polygon([P(80, 50), P(105, 16), P(140, 52)], fill=FIN)
    # 胸鳍
    d.polygon([P(88, 138), P(112, 172), P(70, 162)], fill=FIN_DK)
    # 眼睛
    if full:
        _eye_happy(d, P, S, 72, 98)
    else:
        _eye_round(d, P, 72, 98)
    # 腮红
    d.ellipse([P(100, 112), P(124, 132)], fill=BLUSH)
    # 微笑
    d.arc([P(44, 98), P(78, 124)], start=30, end=150, fill=(150, 80, 30, 255), width=S)
    # 气泡
    d.ellipse([P(160, 30), P(176, 46)], outline=(190, 220, 255, 255), width=S)
    d.ellipse([P(176, 12), P(186, 22)], outline=(190, 220, 255, 255), width=S)
    return img.resize((W, H), RESAMPLE)


def draw_front(full=False):
    S = 4
    W, H = 240, 240
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return (x * S, y * S)

    # 身体（正面，吃饱时更圆胖）
    if full:
        d.ellipse([P(30, 40), P(210, 180)], fill=ORANGE, outline=ORANGE_DK, width=S)
    else:
        d.ellipse([P(40, 45), P(200, 175)], fill=ORANGE, outline=ORANGE_DK, width=S)
    # 肚皮
    if full:
        d.ellipse([P(58, 96), P(182, 178)], fill=BELLY)
    else:
        d.ellipse([P(65, 95), P(175, 175)], fill=BELLY)
    # 背鳍（顶部）
    d.polygon([P(95, 48), P(120, 14), P(145, 48)], fill=FIN)
    # 两侧胸鳍
    d.polygon([P(40, 120), P(20, 150), P(52, 158)], fill=FIN_DK)
    d.polygon([P(200, 120), P(220, 150), P(188, 158)], fill=FIN_DK)
    # 眼睛（对称）
    if full:
        _eye_happy(d, P, S, 90, 100)
        _eye_happy(d, P, S, 150, 100)
    else:
        _eye_round(d, P, 90, 100)
        _eye_round(d, P, 150, 100)
    # 腮红（对称）
    d.ellipse([P(50, 118), P(74, 140)], fill=BLUSH)
    d.ellipse([P(166, 118), P(190, 140)], fill=BLUSH)
    # 微笑
    d.arc([P(104, 118), P(136, 146)], start=20, end=160, fill=(150, 80, 30, 255), width=S)
    return img.resize((W, H), RESAMPLE)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "assets"), exist_ok=True)
    files = {
        "character.png": draw_side(False),
        "character_front.png": draw_front(False),
        "character_full.png": draw_side(True),
        "character_full_front.png": draw_front(True),
    }
    for name, img in files.items():
        img.save(os.path.join(here, name))
        img.save(os.path.join(here, "assets", name))
    print("生成完成：", ", ".join(files.keys()))


if __name__ == "__main__":
    main()
