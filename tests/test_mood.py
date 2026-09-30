# -*- coding: utf-8 -*-
"""pet_mood.Mood 状态机回归（戳链/食物超时/调皮节流）。"""
import time

import pytest
from PySide6.QtCore import QCoreApplication

import pet_mood


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _make_mood():
    m = pet_mood.Mood()
    m.prime_mischief()
    return m


def test_poke_chain(qapp):
    m = _make_mood()
    states, emotes = [], []
    m.state.connect(states.append)
    m.emote.connect(emotes.append)
    m.poke()
    m.poke()
    m.poke()
    assert states == ["puzzled", "angry", "hiss"]
    assert emotes == ["question", "anger", "anger"]


def test_poke_reset_after_threshold(qapp, monkeypatch):
    m = _make_mood()
    states = []
    m.state.connect(states.append)
    m.poke()
    monkeypatch.setattr(time, "monotonic", lambda: 10 ** 15)  # 远大于当前单调时钟
    m.poke()
    assert states == ["puzzled", "puzzled"]  # 重新从 1 开始


def test_food_withhold(qapp):
    m = _make_mood()
    states = []
    m.state.connect(states.append)
    m.food_shown()
    assert states == ["drool"]
    m._withhold()
    assert states[-1] == "cry"
    m.fed()  # 不抛


def test_mischief_primed(qapp, monkeypatch):
    m = _make_mood()
    states = []
    m.state.connect(states.append)
    m.tick()
    assert states == []  # prime 后首次 tick 不触发
    monkeypatch.setattr(time, "monotonic", lambda: 10 ** 15)
    m.tick()
    assert states == ["smug"]

