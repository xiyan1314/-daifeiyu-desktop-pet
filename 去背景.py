# -*- coding: utf-8 -*-
"""去除角色图背景，输出透明 PNG。
用法：python 去背景.py 输入图 [输出图] [容差]
示例：python 去背景.py source.png character.png 40
"""
import sys
import os
from collections import Counter
from PIL import Image


def remove_background(img, tolerance=40):
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    # 1) 若图已有明显透明区域，直接阈值化返回
    step = max(1, min(w, h) // 60)
    alpha_min = 255
    for y in range(0, h, step):
        for x in range(0, w, step):
            a = px[x, y][3]
            if a < alpha_min:
                alpha_min = a
    if alpha_min < 250:
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a < 128:
                    px[x, y] = (r, g, b, 0)
        return img

    # 2) 采样四角，取主导背景色
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = Counter(corners).most_common(1)[0][0]

    def near(c):
        return abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) <= tolerance * 3

    # 3) 从边界 flood-fill 背景连通区域
    stack = []
    for x in range(w):
        stack.append((x, 0))
        stack.append((x, h - 1))
    for y in range(h):
        stack.append((0, y))
        stack.append((w - 1, y))
    seen = set()
    while stack:
        x, y = stack.pop()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        r, g, b, a = px[x, y]
        if not near((r, g, b, a)):
            continue
        px[x, y] = (r, g, b, 0)
        if x > 0:
            stack.append((x - 1, y))
        if x < w - 1:
            stack.append((x + 1, y))
        if y > 0:
            stack.append((x, y - 1))
        if y < h - 1:
            stack.append((x, y + 1))
    return img


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_透明.png"
    try:
        tol = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    except ValueError:
        print("容差参数必须是整数，例如：python 去背景.py source.png character.png 40")
        return
    tol = max(0, min(255, tol))  # 钳制容差（near() 内乘 3 后对应曼哈顿距离 ≤765）
    Image.MAX_IMAGE_PIXELS = 40_000_000  # 防解压炸弹（限制超大图）
    img = None
    try:
        img = Image.open(src)
        out = remove_background(img, tol)
        out.save(dst)
        print("已输出：", dst)
    except FileNotFoundError:
        print("找不到输入文件：", src)
    except Exception as e:
        print("处理失败：", e)
    finally:
        if img is not None:
            img.close()


if __name__ == "__main__":
    main()
