# -*- coding: utf-8 -*-
"""P1-4 多屏几何：screen_geometry_at 纯逻辑回归（假屏幕注入，无需真实多屏）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import 桌宠 as main  # noqa: E402

from PySide6.QtCore import QPoint, QRect  # noqa: E402


class _FakeScreen:
    """鸭子类型 QScreen：只实现 availableGeometry（helper 唯一依赖）。"""

    def __init__(self, x, y, w, h, dpr=1.0):
        self._g = QRect(x, y, w, h)
        self.devicePixelRatio = dpr

    def availableGeometry(self):
        return self._g


def _dual_setup():
    """主屏 1920x1080@(0,0) + 副屏 2560x1440@(-2560,0)（负坐标左侧副屏，125% DPR）。"""
    return [_FakeScreen(0, 0, 1920, 1080), _FakeScreen(-2560, 0, 2560, 1440, dpr=1.25)]


def test_point_inside_secondary_negative_coords():
    screens = _dual_setup()
    scr, rect = main.screen_geometry_at(QPoint(-1000, 500), screens)
    assert scr is screens[1]  # 负坐标副屏
    assert rect.left() == -2560 and rect.width() == 2560


def test_point_inside_primary():
    screens = _dual_setup()
    scr, rect = main.screen_geometry_at(QPoint(800, 300), screens)
    assert scr is screens[0]
    assert rect.left() == 0 and rect.width() == 1920


def test_gap_nearest_secondary(monkeypatch):
    # 真缝隙拓扑：副屏 1280x720@(-3000,0)（x∈[-3000,-1721]）与主屏 (0,0) 之间留 1721px 缝隙。
    # 点 (-1700,700) 不在任何屏内：距副屏中心 (-2360,360) 远小于距主屏中心 → 副屏赢
    screens = [_FakeScreen(0, 0, 1920, 1080), _FakeScreen(-3000, 0, 1280, 720)]
    monkeypatch.setattr(main.QApplication, "screenAt", lambda pt: None)  # 确定性：强制走回退
    scr, _ = main.screen_geometry_at(QPoint(-1700, 700), screens)
    assert scr is screens[1]


def test_gap_nearest_primary(monkeypatch):
    # 同拓扑，点 (-100,100) 距主屏中心更近 → 主屏赢
    screens = [_FakeScreen(0, 0, 1920, 1080), _FakeScreen(-3000, 0, 1280, 720)]
    monkeypatch.setattr(main.QApplication, "screenAt", lambda pt: None)
    scr, _ = main.screen_geometry_at(QPoint(-100, 100), screens)
    assert scr is screens[0]


def test_screenat_hit_priority(monkeypatch):
    # 产线主路径：screenAt 命中（点在屏内）优先于最近屏回退——
    # 即使几何上距另一块屏中心更近，也以所在屏为准
    screens = _dual_setup()
    monkeypatch.setattr(main.QApplication, "screenAt", lambda pt: screens[0])
    scr, _ = main.screen_geometry_at(QPoint(-2000, 400), screens)
    assert scr is screens[0]


def test_portrait_secondary():
    screens = [_FakeScreen(0, 0, 1920, 1080), _FakeScreen(1920, -200, 1080, 1920)]  # 右侧竖屏
    scr, rect = main.screen_geometry_at(QPoint(2300, 600), screens)
    assert scr is screens[1]
    assert rect.width() == 1080 and rect.height() == 1920


def test_no_screens_returns_none():
    scr, rect = main.screen_geometry_at(QPoint(0, 0), [])
    assert scr is None and rect is None


def test_dpi_needs_no_conversion():
    # Qt6 QScreen 几何即逻辑(DIP)坐标：125% DPR 的副屏 rect 与 widget move() 同坐标系，
    # 直接使用 rect 值即可（无手工换算）——此处仅锁定 helper 不触碰 DPR 的行为契约
    screens = _dual_setup()
    scr, rect = main.screen_geometry_at(QPoint(-500, 200), screens)
    assert scr.devicePixelRatio == 1.25
    # Qt QRect.right() 为含端点（x+width-1）：改用 x+width 表达「右缘与主屏左缘相接」
    assert rect.x() + rect.width() == 0  # 副屏右缘接主屏左缘：DIP 坐标连续

