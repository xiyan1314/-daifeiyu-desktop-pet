# -*- coding: utf-8 -*-
"""行走参数纯函数回归（三区速度核心常量与步进公式）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import 桌宠 as main  # noqa: E402


def test_walk_constants():
    assert main.WALK_INTERVAL_MS == 120
    assert main.WALK_STEP_MIN == 1
    assert main.WALK_STEP_MAX == 6


def test_step_default_cap():
    assert main._walk_step(1000) == 6
    assert main._walk_step(60) == 6
    assert main._walk_step(4) == 1
    assert main._walk_step(0) == 0


def test_step_custom_cap():
    assert main._walk_step(1000, 30) == 30
    assert main._walk_step(100, 30) == 10


def test_step_never_negative():
    assert main._walk_step(-100) == 6
    assert main._walk_step(-4) == 1

