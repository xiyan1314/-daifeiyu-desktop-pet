# -*- coding: utf-8 -*-
"""P1-手感 pet_physics 纯函数回归（估速/软上限/积分反弹/落地 Q 弹）。"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import pet_physics as ph  # noqa: E402


# ---------------- 软上限 ----------------

def test_soft_cap_basic():
    assert ph.soft_cap(0) == 0.0
    assert ph.soft_cap(-5) == 0.0
    assert ph.soft_cap(100) < 100  # 有衰减
    assert ph.soft_cap(100, None) > 95  # 小速度衰减轻微
    assert ph.soft_cap(1e9) == pytest.approx(ph.SOFT_CAP, rel=0.01)  # 渐近线


# ---------------- 轨迹估速 ----------------

def _line_samples(t0, x0, y0, speed_x, speed_y, n=10, dt=0.016):
    return [(t0 + i * dt, x0 + speed_x * i * dt, y0 + speed_y * i * dt) for i in range(n)]


def test_estimate_empty_or_single():
    assert ph.estimate_throw([]) == (0.0, 0.0)
    assert ph.estimate_throw([(0.0, 0.0, 0.0)]) == (0.0, 0.0)


def test_estimate_pause_gentle_put():
    samples = _line_samples(0.0, 0.0, 0.0, 2000.0, 0.0)
    # 松手时刻距最后采样 0.5s（停顿）：温柔放下
    vx, vy = ph.estimate_throw(samples, now=samples[-1][0] + 0.5)
    assert (vx, vy) == (0.0, 0.0)


def test_estimate_slow_no_throw():
    samples = _line_samples(0.0, 0.0, 0.0, 100.0, 0.0)  # 100px/s < 500
    vx, vy = ph.estimate_throw(samples)
    assert (vx, vy) == (0.0, 0.0)


def test_estimate_fast_right():
    samples = _line_samples(0.0, 0.0, 0.0, 2000.0, 0.0, n=10, dt=0.02)
    vx, vy = ph.estimate_throw(samples)
    assert vy == 0.0
    assert vx > 0
    assert vx <= ph.SOFT_CAP + 1e-6  # 软上限
    # 端点均值 0.5 + 窗口峰值 0.5 的合成值再软上限（数值直测锁定）
    assert vx == pytest.approx(ph.soft_cap(2000.0), rel=0.01)


def test_estimate_throw_power_gain():
    samples = _line_samples(0.0, 0.0, 0.0, 2000.0, 0.0, n=10, dt=0.02)
    v1, _ = ph.estimate_throw(samples, throw_power=1.0)
    v2, _ = ph.estimate_throw(samples, throw_power=2.0)
    assert v2 == pytest.approx(2.0 * v1, rel=0.01)  # 总力度增益=线性放大


def test_estimate_negative_direction_symmetric():
    # 负方向（左/上）甩动与正方向对称：同样的速率得到同样的合速度大小
    right = _line_samples(0.0, 0.0, 0.0, 2000.0, 0.0, n=10, dt=0.02)
    left = _line_samples(0.0, 0.0, 0.0, -2000.0, 0.0, n=10, dt=0.02)
    vr, _ = ph.estimate_throw(right)
    vl, _ = ph.estimate_throw(left)
    assert vr > 0 and vl < 0
    assert abs(vl) == pytest.approx(abs(vr), rel=0.01)


def test_grounded_slide_no_micro_bounce():
    # 贴地滑行连续多步：vy 恒为 0（无周期性微弹跳），vx 持续摩擦衰减
    x, y, vx, vy = 0.0, 990.0, 100.0, 0.0
    for _ in range(10):
        x, y, vx, vy, og, _imp = ph.step_physics(x, y, vx, vy, 10, 10, (0, 0, 1000, 1000), 0.05)
        assert vy == 0.0
        assert og is True
    assert abs(vx) < 100  # 摩擦衰减后明显减速


def test_estimate_merge_dt_no_peak_inflation():
    # 高回报率鼠标：2ms 采样间隔的来回抖动不应放大峰值
    samples = [(i * 0.002, 10.0 if i % 2 == 0 else 12.0, 0.0) for i in range(50)]
    vx, _vy = ph.estimate_throw(samples)
    assert abs(vx) < ph.VELOCITY_THRESHOLD  # 抖动被合并后速度远低于抛掷阈值


# ---------------- 积分：重力/反弹/摩擦 ----------------

def test_free_fall():
    nx, ny, vx, vy, og, _imp = ph.step_physics(0, 0, 0, 0, 10, 10, (0, 0, 1000, 1000), 0.05)
    assert nx == 0 and ny > 0
    assert vy == pytest.approx(1400 * 0.05)
    assert og is False


def test_ground_bounce_restitution():
    # 屏幕坐标：vy 为正 = 下落；以 +800 砸地（含一步重力 70）→ 反向 ×0.78
    nx, ny, vx, vy, og, _imp = ph.step_physics(0, 950, 0, 800, 10, 10, (0, 0, 1000, 1000), 0.05)
    assert og is True
    assert vy == pytest.approx(-(800 + 70) * 0.78)
    assert _imp == pytest.approx(870)  # 落地冲击 = 反弹前向下速度（供 Q 弹判定）


def test_wall_bounce():
    nx, ny, vx, vy, og, _imp = ph.step_physics(995, 0, 300, 0, 10, 10, (0, 0, 1000, 1000), 0.05)
    assert nx <= 990
    assert vx == pytest.approx(-300 * 0.78)


def test_ground_friction_and_static():
    nx, ny, vx, vy, og, _imp = ph.step_physics(0, 990, 30, 0, 10, 10, (0, 0, 1000, 1000), 0.05)
    assert og is True
    assert abs(vx) < 30  # 摩擦衰减
    # 静止：贴地小速度 → 双零
    nx2, ny2, vx2, vy2, og2, _imp2 = ph.step_physics(0, 990, 5, 5, 10, 10, (0, 0, 1000, 1000), 0.05)
    assert og2 is True and vx2 == 0.0 and vy2 == 0.0


def test_dt_clamp():
    a = ph.step_physics(0, 0, 0, 0, 10, 10, (0, 0, 1000, 1000), 0.5)
    b = ph.step_physics(0, 0, 0, 0, 10, 10, (0, 0, 1000, 1000), 0.05)
    assert a == b  # dt 截断到 0.05


def test_zero_gravity_float_mode():
    p = dict(ph.DEFAULT_PHYSICS)
    p["gravity"] = 0
    nx, ny, vx, vy, og, _imp = ph.step_physics(0, 0, 0, 100, 10, 10, (0, 0, 1000, 1000), 0.05, p)
    assert vy == 100  # 无重力：速度不变
    assert ny == pytest.approx(100 * 0.05)


# ---------------- 落地 Q 弹 ----------------

def test_landing_squash_mapping():
    assert ph.landing_squash(100) == 1.0       # 低于 300：不触发
    assert ph.landing_squash(300) == pytest.approx(0.8)
    assert ph.landing_squash(1500) == pytest.approx(0.55)
    assert ph.landing_squash(5000) == 0.55     # 超重砸钳制


def test_bounce_scale_shape():
    squash = 0.7
    assert ph.bounce_scale(0.0, squash) == 1.0
    assert ph.bounce_scale(ph.BOUNCE_DURATION, squash) == 1.0
    mid = ph.bounce_scale(ph.BOUNCE_DURATION * 0.45, squash)
    assert mid == pytest.approx(squash)  # 前 45% 压缩到底
    # 回弹段有峰值且 ≤1.12
    peak = max(ph.bounce_scale(ph.BOUNCE_DURATION * t, squash) for t in (i / 100.0 for i in range(45, 101)))
    assert peak > squash and peak <= ph.BOUNCE_PEAK + 1e-9
