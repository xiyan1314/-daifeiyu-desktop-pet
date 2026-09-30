# -*- coding: utf-8 -*-
"""pet_anim.FrameAnim 边界（loops/stop/on_finish/空帧集/重复 play）。"""
import pytest
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

import pet_anim


@pytest.fixture(scope="module")
def qapp():
    # 用 QApplication 而非 QGuiApplication：全仓测试共享同一个应用单例，
    # 若先建 QGuiApplication，后续 QApplication.instance() 会误判导致控件类崩溃
    app = QApplication.instance() or QApplication([])
    yield app


def _frames(n=3):
    out = []
    for i in range(n):
        p = QPixmap(4, 4)
        p.fill(QColor("#%02x%02x%02x" % (40 * i, 80, 200)))
        out.append(p)
    return out


def test_empty_set_calls_finish(qapp):
    anim = pet_anim.FrameAnim()
    done = []
    ok = anim.play("none", on_finish=lambda name: done.append(name))
    assert ok is False and done == ["none"]


def test_loop_count(qapp):
    anim = pet_anim.FrameAnim()
    anim.add_set("demo", _frames(3))
    done = []
    anim.play("demo", interval_ms=10, loops=2, on_finish=lambda n: done.append(n))
    for _ in range(6):
        anim._advance()  # 6 次发射 = 2 遍 x 3 帧 → 播完
    assert done == ["demo"]
    assert not anim._timer.isActive()


def test_stop_clears_callback(qapp):
    anim = pet_anim.FrameAnim()
    anim.add_set("demo", _frames(3))
    done = []
    anim.play("demo", interval_ms=10, loops=2, on_finish=lambda n: done.append(n))
    anim.stop()
    assert done == []  # stop 不回调
    assert not anim._timer.isActive()


def test_replay_replaces(qapp):
    anim = pet_anim.FrameAnim()
    anim.add_set("a", _frames(3))
    anim.add_set("b", _frames(5))
    anim.play("a", interval_ms=50)
    anim.play("b", interval_ms=50)
    assert anim.current() is anim._sets["b"][0]

