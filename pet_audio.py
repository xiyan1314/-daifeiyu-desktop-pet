# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 音频模块（阶段 3，R3-1）。

职责：把「参考项目音频素材 + 合成回退」统一封装，供主程序在按压 / 松手 / 喂食时播放。

对外接口：
- init(sounds_dir)：扫描 sounds_dir 下的 ya1.wav / ya2.wav / d1.wav / d2.wav，
  记录存在的文件路径；在 GUI 环境下（QCoreApplication 已创建）预建 QtMultimedia
  QSoundEffect 效果器；同时预合成 3 个回退音。
- play(kind)：kind ∈ {press, release, feed}，按三级链路播放：
    1) QSoundEffect 播放 wav 文件（现代音频通道，多音可叠加、不阻塞）；
    2) winsound SND_FILENAME 播放 wav 文件；
    3) winsound SND_MEMORY 播放合成回退音。
  任何一级失败静默降级到下一级，绝不抛出。

实现要点：
- 仅 winsound / wave / os / math / struct 为顶层依赖；PySide6.QtMultimedia 惰性导入，
  模块本身在无 GUI 环境下也可正常 import（冒烟测试走 winsound 路径）。
- 不再依赖 SND_MEMORY + SND_NOWAIT 作为主链路：SND_NOWAIT 在驱动忙时会直接丢音，
  导致用户「听不到音效」；QSoundEffect 三个独立效果器可叠加播放且全程不阻塞。
- 所有播放路径都静默处理异常，绝不抛出，避免打断主循环。

Python 3.8+ 兼容。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import math
import os
import struct
import wave

try:
    import winsound  # 仅 Windows 提供；非 Windows 导入失败时置 None
except ImportError:
    winsound = None


# 采样率（与素材 / 参考实现一致）
_SAMPLE_RATE = 22050

# 素材文件名（d1 为预留音效，暂未被 play() 映射）
_WAV_NAMES = ("ya1", "ya2", "d1", "d2")
_WAV_FILES = {name: name + ".wav" for name in _WAV_NAMES}

# 素材文件路径：name -> 存在文件的绝对路径（缺失 / 损坏为 None）
_wav_paths = {name: None for name in _WAV_NAMES}
# 素材时长：name -> 秒（float）或 None（仅冒烟/诊断打印使用，生产播放路径不消费）
_wav_duration = {name: None for name in _WAV_NAMES}
# QSoundEffect 效果器：name -> QSoundEffect 或 None（QtMultimedia 不可用 / 素材缺失）
_effects = {name: None for name in _WAV_NAMES}
# QSoundEffect 类引用缓存（init 时惰性导入一次，play() 热路径直接使用）
_QSoundEffect = None


# ---------------- 合成回退音（参考现有 play_sound 实现） ----------------
def _wav_bytes(samples, rate=_SAMPLE_RATE):
    """把 float 采样序列封成 16bit 单声道 PCM 的完整 WAV bytes。"""
    data = b"".join(struct.pack("<h", int(max(-32768, min(32767, s)))) for s in samples)
    out = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
    out += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    out += b"data" + struct.pack("<I", len(data)) + data
    return out


def _synth(freq_start, freq_end, dur, vol=0.5, rate=_SAMPLE_RATE):
    """线性扫频正弦波采样序列（带线性衰减包络）。"""
    n = int(rate * dur)
    out = []
    for i in range(n):
        t = i / rate
        f = freq_start + (freq_end - freq_start) * (i / n)
        env = 1.0 - i / n
        out.append(vol * 32767 * env * math.sin(2 * math.pi * f * t))
    return out


def _build_fallback():
    """预合成 3 个回退音：下行短音=按压、上行短音=松手、喂食音。"""
    return {
        "press": _wav_bytes(_synth(900, 400, 0.09)),    # 下行短音（按压）
        "release": _wav_bytes(_synth(300, 700, 0.22)),  # 上行短音（松手）
        "feed": _wav_bytes(_synth(500, 900, 0.15)),     # 喂食音
    }


# 模块加载即合成回退音，保证即使未调用 init() 也能回退播放
_fallback = _build_fallback()


# ---------------- WAV 素材校验 ----------------
def _probe_wav(path):
    """用 wave 模块校验 WAV，返回 (存在且可读, 时长秒)；失败返回 (False, None)。"""
    try:
        with wave.open(path, "rb") as wf:
            nchannels, sampwidth, framerate, nframes, comptype, _ = wf.getparams()
        # 仅支持未压缩 PCM；压缩格式或非法参数按损坏处理；限制帧数防恶意超大声明
        if comptype != "NONE" or not framerate or nframes <= 0 or nframes > 25_000_000:
            return False, None
        return True, nframes / float(framerate)
    except Exception:
        return False, None


# ---------------- 对外接口 ----------------
def init(sounds_dir):
    """扫描并缓存素材；幂等，可重复调用。回退音已在模块导入时合成，无需重建。"""
    # 重置缓存（重复调用会覆盖旧结果，保持幂等）
    for name in _WAV_NAMES:
        _wav_paths[name] = None
        _wav_duration[name] = None
        _effects[name] = None

    for name in _WAV_NAMES:
        path = os.path.join(sounds_dir, _WAV_FILES[name])
        ok, dur = _probe_wav(path)
        if ok:
            _wav_paths[name] = path
            _wav_duration[name] = dur

    # 惰性构建 QSoundEffect 效果器：仅在 GUI 事件循环存在时（主程序已创建 QApplication）
    global _QSoundEffect
    try:
        from PySide6.QtCore import QCoreApplication, QUrl
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return  # QtMultimedia 不可用：play() 自动走 winsound 文件 / 合成回退
    _QSoundEffect = QSoundEffect
    if QCoreApplication.instance() is None:
        return  # 无 GUI 环境（如冒烟测试）：不构建效果器

    for name in _WAV_NAMES:
        path = _wav_paths.get(name)
        if path is None:
            continue
        try:
            eff = QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(path))
            eff.setVolume(0.9)
            _effects[name] = eff
        except Exception:
            _effects[name] = None  # 该素材效果器构建失败：留给 winsound 兜底


# kind -> (素材名, 回退音名)
_PLAY_MAP = {
    "press": ("ya1", "press"),
    "release": ("ya2", "release"),
    "feed": ("d2", "feed"),
}


def _qt_playable(eff):
    """判断 QSoundEffect 是否就绪可播（需要 QSoundEffect 类可见时才能调用）。"""
    cls = _QSoundEffect
    if cls is None or eff is None:
        return False
    try:
        return eff.status() == cls.Status.Ready
    except Exception:
        return False


def play(kind):
    """播放音效：press→ya1 / release→ya2 / feed→d2，三级链路降级；未知 kind 直接返回。"""
    pair = _PLAY_MAP.get(kind)
    if pair is None:
        return  # 未知 kind：直接返回
    wav_name, fb_name = pair

    # 1) QSoundEffect（现代音频通道，多音可叠加，不阻塞）
    eff = _effects.get(wav_name)
    if _qt_playable(eff):
        try:
            eff.play()
            return
        except Exception:
            pass  # 播放入口异常：降级到 winsound 文件

    # 2) winsound 播放真实 wav 文件（异步、驱动忙时以新音替换旧音，不阻塞）
    path = _wav_paths.get(wav_name)
    if winsound is not None and path is not None:
        try:
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return
        except Exception:
            pass  # 文件播放失败：降级到合成回退

    # 3) 合成回退音（SND_MEMORY；NOWAIT 仅作最后兜底的防阻塞保险）
    if winsound is None:
        return
    data = _fallback.get(fb_name)
    if data is None:
        return
    try:
        winsound.PlaySound(
            data,
            winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT | winsound.SND_NOWAIT,
        )
    except Exception:
        pass  # 任何异常静默跳过，不抛


# ---------------- 冒烟测试（无需 GUI，可直接运行本文件） ----------------
if __name__ == "__main__":
    SOUNDS_DIR = r"E:\deep seek\desktop-pet\assets\sounds"

    print("=== 冒烟 1：真实素材目录（无 GUI → 不建效果器，走 winsound 文件路径） ===")
    init(SOUNDS_DIR)
    for name in _WAV_NAMES:
        p = _wav_paths[name]
        d = _wav_duration[name]
        if p is None:
            print("  %s.wav -> MISSING (None)" % name)
        else:
            dur = ("%.3fs" % d) if d is not None else "N/A"
            print("  %s.wav -> %s, 时长 %s" % (name, p, dur))
    print("  effects built:", sum(1 for e in _effects.values() if e is not None))

    print("=== 冒烟 2：不存在的目录（验证回退路径） ===")
    init(r"E:\deep seek\desktop-pet\assets\__no_such_dir__")
    for name in _WAV_NAMES:
        print("  %s.wav -> path=%s" % (name, "None" if _wav_paths[name] is None else "set"))
    for k in ("press", "release", "feed"):
        fb = _fallback.get(k)
        print("  fallback[%s] -> %s" % (k, "OK (%d bytes)" % len(fb) if fb else "None"))

    print("=== 冒烟 3：调用 play 不抛异常 ===")
    play("press")
    play("release")
    play("feed")
    play("未知kind")

    print("AUDIO SMOKE OK")
