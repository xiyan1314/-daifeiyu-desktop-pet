# -*- coding: utf-8 -*-
"""P1-手感：甩抛物理纯函数模块（无 Qt 依赖，pytest 直测）。

组成（对应优化清单 P1-手感）：
一、轨迹估速（松手初速）：最近 150ms 窗口 + 停顿判定 + 软上限 + 端点/峰值混合 + 加速放大
二、重力 + 边界反弹 + 地面摩擦：积分步进（单步 dt 上限 0.05s）+ 静止判定
三、落地 Q 弹曲线：冲击速度映射压扁幅度 + 220ms 曲线（前 45% ease-in、后 55% easeOutBack）

开关默认关闭（DEFAULT_PHYSICS["enabled"]=False）：关闭时行为与旧版逐像素一致。
"""
import math

DEFAULT_PHYSICS = {
    "enabled": False,
    "gravity": 1400.0,        # px/s^2
    "restitution": 0.78,      # 四边反弹系数
    "groundFriction": 2.5,    # 落地水平摩擦（每秒衰减系数）
    "ceilingBounce": True,    # 顶边是否反弹
    "throwPower": 1.0,        # 总力度增益（估速/软上限同乘）
}

VELOCITY_THRESHOLD = 500.0   # px/s：低于此视为原地放下，不抛
SOFT_CAP = 3600.0            # px/s：初速软上限
PAUSE_THRESHOLD = 0.150      # s：松手前停顿超过此 = 温柔放下（不带残余速度）
SAMPLE_WINDOW = 0.200        # s：拖拽期只保留最近 200ms 轨迹
ESTIMATE_WINDOW = 0.150      # s：松手估速窗口
MERGE_DT = 0.008             # s：采样段 dt 小于此向前合并（防高回报率鼠标抖动放大峰值）
ACCEL_BOOST_MAX = 0.6        # 仍在加速的甩动最多再放大 60%
STATIC_VY = 40.0             # px/s：静止判定
STATIC_VX = 15.0
DT_MAX = 0.05                # s：积分单步上限（防卡顿后巨帧跳变）
BOUNCE_DURATION = 0.220      # s：落地 Q 弹时长
BOUNCE_C1 = 1.70158          # easeOutBack 常数
BOUNCE_PEAK = 1.12           # scaleY 过冲上限
SQUASH_LIGHT_IMPACT = 300.0  # px/s：轻落（压扁 0.8）
SQUASH_HEAVY_IMPACT = 1500.0 # px/s：重砸（压扁 0.55）
FLIGHT_TICK_MS = 16          # ms：飞行积分定时器间隔
FLIGHT_MAX_SECONDS = 5.0     # s：飞行时长上限（防漂浮模式等软锁）
AIR_STATIC_TICKS = 3         # 空中 |vx|<15 且 |vy|<40 连续 N 拍视为静止收尾
SQUASH_MIN_X = 0.8           # 压扁时 scaleX 下限（体积守恒）


# ---------------- 组成一：轨迹估速 ----------------

def soft_cap(speed, cap=None):
    """软上限 cap*(1-e^(-s/cap))；s<0 按 0。cap=None 用 SOFT_CAP；总力度增益
    由调用方（estimate_throw）对结果整体乘以 throw_power，曲线形状不变。"""
    if speed <= 0:
        return 0.0
    cap = SOFT_CAP if cap is None else cap
    if cap <= 0:
        return speed
    return cap * (1.0 - math.exp(-speed / cap))


def trim_samples(samples, window=None, now=None):
    """只保留最近 window 秒的采样（拖拽期调用）。samples=[(t,x,y)...] 时间递增。

    返回新列表（原列表不变）；now=None 取最后采样时间。"""
    window = SAMPLE_WINDOW if window is None else window
    if not samples:
        return []
    last = samples[-1][0] if now is None else now
    out = []
    for s in samples:
        if last - s[0] <= window:
            out.append(s)
    return out


def _merged_samples(samples):
    """采样段 dt<MERGE_DT 向前合并：短间隔段只保留最新位置（抖动不放大峰值）。"""
    if len(samples) < 2:
        return list(samples)
    out = [samples[0]]
    for s in samples[1:]:
        if s[0] - out[-1][0] < MERGE_DT:
            out[-1] = s  # 向前合并：保留最新
        else:
            out.append(s)
    return out


def _axis_velocity(pts):
    """对 [(t, v)]（已合并）估单轴速度：端点均值 0.5 + 窗口峰值 0.5。

    峰值按 |v| 取、保留符号（负方向甩动与正方向对称，不被低估）；
    仍在同向加速（|端点| > |均值|）最多再放大 60%。返回 px/s。"""
    if len(pts) < 2:
        return 0.0
    segs = []
    for i in range(1, len(pts)):
        dt = pts[i][0] - pts[i - 1][0]
        if dt > 0:
            segs.append(((pts[i][1] - pts[i - 1][1]) / dt))
    if not segs:
        return 0.0
    mean = sum(segs) / len(segs)
    peak = max(segs, key=abs)  # 按 |v| 取峰值（保留方向符号）
    v = 0.5 * mean + 0.5 * peak
    # 仍在同向加速：|端点速度|明显高于 |均值| → 放大（上限 60%）
    end = segs[-1]
    if abs(end) > abs(mean) and (end > 0) == (mean > 0):
        ratio = min(1.0, (abs(end) - abs(mean)) / max(abs(mean), 1.0))
        v *= 1.0 + ACCEL_BOOST_MAX * ratio
    return v


def estimate_throw(samples, now=None, throw_power=1.0):
    """松手估速。samples=[(t,x,y)...] 时间递增。

    返回 (vx, vy) px/s（含 throw_power 增益与软上限）；以下情形返回 (0,0)：
    - 无采样 / 单点
    - 松手前停顿 > PAUSE_THRESHOLD（温柔放下）
    - 合速度 < VELOCITY_THRESHOLD（原地放下）
    """
    if not samples or len(samples) < 2:
        return 0.0, 0.0
    now = samples[-1][0] if now is None else now
    if now - samples[-1][0] > PAUSE_THRESHOLD:
        return 0.0, 0.0  # 松手前停顿：温柔放下
    win = [(t, x, y) for (t, x, y) in samples if now - t <= ESTIMATE_WINDOW]
    if len(win) < 2:
        return 0.0, 0.0
    merged = _merged_samples(win)
    vx = _axis_velocity([(t, x) for t, x, _y in merged])
    vy = _axis_velocity([(t, y) for t, _x, y in merged])
    mag = math.hypot(vx, vy)
    if mag < VELOCITY_THRESHOLD:
        return 0.0, 0.0
    # 总力度增益与初速/软上限同乘：等价于结果整体 ×throw_power（保持方向与曲线形状）
    tp = max(0.0, throw_power)
    capped = tp * soft_cap(mag, SOFT_CAP)
    ratio = capped / mag
    return vx * ratio, vy * ratio


# ---------------- 组成二：重力 + 反弹 + 摩擦 ----------------

def step_physics(x, y, vx, vy, w, h, rect, dt, params=None):
    """单步积分。rect=(left, top, right, bottom) 为可用区域（逻辑 px，右/下为 x+width 语义）。

    返回 (nx, ny, nvx, nvy, on_ground, impact)：
    impact 为本步落地瞬间的向下冲击速度（px/s，未落地为 0）——供落地 Q 弹
    判定使用，与「静止判定」解耦（重砸也能弹、轻落才直接停）。
    params 为 DEFAULT_PHYSICS 风格 dict；dt 超 DT_MAX 自动截断。"""
    p = dict(DEFAULT_PHYSICS)
    if params:
        p.update(params)
    dt = min(max(0.0, dt), DT_MAX)
    g = float(p.get("gravity", 1400.0))  # gravity=0 → 漂浮模式（清单允许）
    rest = float(p.get("restitution", 0.78))
    fric = float(p.get("groundFriction", 2.5))
    ceil_b = bool(p.get("ceilingBounce", True))
    left, top, right, bottom = rect
    on_ground = y + h >= bottom - 1e-6

    if on_ground:
        vx *= max(0.0, 1.0 - fric * dt)  # 地面摩擦
    if on_ground and vy >= 0.0:
        vy = 0.0  # 贴地且无向上速度：重力不累加（避免贴地滑行/静止的每步微弹跳）
    else:
        vy += g * dt  # 腾空或贴地向上反弹中：重力照常累加

    nx = x + vx * dt
    ny = y + vy * dt

    # 左右墙反弹
    if nx < left:
        nx = left
        vx = abs(vx) * rest
    elif nx + w > right:
        nx = right - w
        vx = -abs(vx) * rest
    # 顶边反弹
    if ny < top:
        ny = top
        if ceil_b:
            vy = abs(vy) * rest
        else:
            vy = max(0.0, vy)
    # 落地
    impact = 0.0
    if ny + h > bottom:
        ny = bottom - h
        impact = max(0.0, vy)  # 落地冲击 = 反弹前的向下速度
        if abs(vy) < STATIC_VY:
            vy = 0.0
        else:
            vy = -abs(vy) * rest
        on_ground = True
    elif ny + h < bottom - 1e-6:
        on_ground = False
    # 恰贴地（相等）：保持进入时的 on_ground 状态（静止/贴地滑行不被误标为腾空）
    # 静止判定：贴地且双轴速度都极小 → 停
    if on_ground and abs(vx) < STATIC_VX and abs(vy) < STATIC_VY:
        vx = 0.0
        vy = 0.0
    return nx, ny, vx, vy, on_ground, impact


def landing_squash(impact_speed):
    """落地冲击速度 → 压扁幅度：300px/s→0.8（轻落）、1500px/s→0.55（重砸）、
    低于 300 不触发 Q 弹（返回 1.0）。"""
    if impact_speed < SQUASH_LIGHT_IMPACT:
        return 1.0
    if impact_speed >= SQUASH_HEAVY_IMPACT:
        return 0.55
    f = (impact_speed - SQUASH_LIGHT_IMPACT) / (SQUASH_HEAVY_IMPACT - SQUASH_LIGHT_IMPACT)
    return 0.8 - 0.25 * f


# ---------------- 组成三：落地 Q 弹曲线 ----------------

def bounce_scale(t, squash, duration=None):
    """落地 Q 弹 scaleY 曲线：t∈[0,duration]。

    前 45% ease-in 从 1.0 压到 squash；后 55% easeOutBack 回弹（过冲 ≤1.12）回 1.0。
    返回 scaleY；t 越界时返回端值。"""
    duration = BOUNCE_DURATION if duration is None else duration
    if duration <= 0:
        return 1.0
    if t <= 0:
        return 1.0
    if t >= duration:
        return 1.0
    p = t / duration
    if p < 0.45:
        e = p / 0.45
        e = e * e  # ease-in（二次）
        return 1.0 - (1.0 - squash) * e
    e = (p - 0.45) / 0.55
    # easeOutBack：f(x)=1+c3*(x-1)^3+c1*(x-1)^2, c3=c1+1
    c1 = BOUNCE_C1
    x = e - 1.0
    back = 1.0 + (c1 + 1.0) * x * x * x + c1 * x * x
    s = squash + (1.0 - squash) * back
    return min(s, BOUNCE_PEAK)
