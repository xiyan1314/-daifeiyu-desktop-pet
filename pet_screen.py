# -*- coding: utf-8 -*-
"""
P1-4：多屏几何（吸附 / 气泡 / 漫游 / 回收共用）。

独立模块：不 import 桌宠.py；桌宠.py 以 `from pet_screen import ...` 保留模块级名字。
"""
from PySide6.QtWidgets import QApplication

# 距屏右下角的默认边距（初始落位与掉屏回收共用）
SCREEN_EDGE_MARGIN_X = 40
SCREEN_EDGE_MARGIN_Y = 80  # 纵向留得多：让出任务栏


def screen_geometry_at(pt, screens=None):
    """取全局逻辑坐标点 pt 所在屏幕与其 availableGeometry。
    pt 为 None 或屏幕为空时返回 (None, None)。

    Qt6 的 QScreen.geometry()/availableGeometry() 本身就是逻辑(DIP)坐标，
    与 QWidget.move() 同一坐标系——混合 DPI 无需手工 devicePixelRatio 换算，
    跨 100%/125%/150% 缩放的屏幕吸附与定位天然对齐。

    点在屏幕外或屏幕间隙（双屏缝隙/负坐标副屏/竖屏）时，回退到**中心距离
    最近的屏幕**（而不是盲目回主屏），保证吸附、气泡、漫游目标不跳错屏。

    screens 参数供测试注入假屏幕；为 None 时取 QApplication.screens()。
    返回 (QScreen, QRect)；无屏幕时返回 (None, None)。
    """
    if pt is None:
        return None, None
    if screens is None:
        try:
            screens = QApplication.screens()
        except Exception:
            screens = []
    if not screens:
        return None, None
    try:
        scr = QApplication.screenAt(pt) if QApplication.instance() is not None else None
    except Exception:
        scr = None
    if scr is not None and scr in screens:
        return scr, scr.availableGeometry()
    best = None
    best_d = None
    for s in screens:
        c = s.availableGeometry().center()
        d = (pt.x() - c.x()) ** 2 + (pt.y() - c.y()) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = s
    if best is None:
        return None, None
    return best, best.availableGeometry()
