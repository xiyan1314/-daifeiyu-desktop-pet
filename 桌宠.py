# -*- coding: utf-8 -*-
"""
DeepSeek 大肥鱼桌宠 (PySide6 / Qt6)
MIT License
一只又娇又耍赖、贪吃、被吓到就浑身发抖的大肥鱼桌宠。
名台词：喜欢的，就咬住不放~
运行：绿色版双击 启动桌宠.vbs；源码运行双击 启动桌宠.bat（或 python 桌宠.py）。
"""
# entry-marker: daifeiyu_pet_main（绿色版启动器靠此 ASCII 标记定位主程序，勿删）

import os
import sys
import json
import math
import random
import threading

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRectF, QVariantAnimation, QEasingCurve, QObject, Signal,
)
from PySide6.QtGui import (
    QPixmap, QTransform, QFont, QColor, QPainter, QCursor, QPolygonF,
    QFontMetrics, QPen, QPainterPath, QIcon,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMenu, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QInputDialog, QMessageBox, QFrame, QLineEdit, QDialog,
    QSystemTrayIcon,
)

import requests
import psutil
import pet_anim
import pet_mood
import pet_audio
import time
import base64
import shutil
import ctypes
from ctypes import wintypes


APP_NAME = "大肥鱼桌宠"
VERSION = "1.0.0"
PAD = 1.25  # 窗口相对角色的透明边距（为压扁/回弹预留空间）
IDLE_FRAME_MS = 140      # 待机帧间隔
EAT_FRAME_MS = 110       # 进食帧间隔
SLEEP_AFTER_SECONDS = 60 # 无交互多久入睡
STATE_DURATION_MS = 2500 # 状态图默认展示时长
_MB = 1048576.0
MEI_MAX_AGE_SECONDS = 7 * 86400  # 启动清理：只清理超过 7 天的 _MEI* 残留（降低误删风险）
SOUND_KIND_MAP = {"boing": "press", "pop": "release", "feed": "feed"}


# ---------------- 路径 / 配置 ----------------
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir(rel):
    """目录级资源定位：优先 exe/脚本同目录，冻结环境回退 _MEIPASS。"""
    p = os.path.join(app_dir(), rel)
    if os.path.isdir(p):
        return p
    if getattr(sys, "frozen", False):
        p2 = os.path.join(getattr(sys, "_MEIPASS", app_dir()), rel)
        if os.path.isdir(p2):
            return p2
    return p


def resource_path(rel):
    p = os.path.join(app_dir(), rel)
    if os.path.exists(p):
        return p
    if getattr(sys, "frozen", False):
        p2 = os.path.join(getattr(sys, "_MEIPASS", app_dir()), rel)
        if os.path.exists(p2):
            return p2
    return p


def _data_dir():
    """数据目录：优先 exe 同目录（便携）；不可写则回退 %APPDATA%。"""
    d = app_dir()
    probe = os.path.join(d, ".write_probe")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return d
    except Exception:
        pass
    alt = os.path.join(os.environ.get("APPDATA", d), "大肥鱼桌宠")
    try:
        os.makedirs(alt, exist_ok=True)
        return alt
    except Exception:
        return d


DATA_DIR = _data_dir()
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
DEFAULT_CONFIG = {
    "scale": 1.0,
    "always_on_top": True,
    "ai_enabled": False,
    "api_key": "",
    "city": "北京",
    "follow_mouse": False,
    "wander": False,
    "sound": True,
    "badge": False,
}


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


# 脱敏 key 缓存（未设置 = None，设置后为空串表示「无 key」）
_redact_key = None


def set_redact_key(key):
    """由 PetWindow 在 key 载入 / 修改 / 清除后同步，避免 _log_error 每次重读并解密 config。"""
    global _redact_key
    _redact_key = str(key or "")


def _log_error(msg):
    try:
        import re
        key = _redact_key
        if key is None:
            key = load_config().get("api_key", "")  # 尚未同步时兜底读取一次
        if key:
            msg = msg.replace(key, "***APIKEY***")
        msg = re.sub(r"(sk-[A-Za-z0-9_-]{6,})", "sk-***", msg)
        path = os.path.join(DATA_DIR, "error.log")
        try:
            if os.path.getsize(path) > 512 * 1024:  # 512KB 轮转，防无限累积
                os.replace(path, path + ".old")
        except Exception:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                if k in DEFAULT_CONFIG:
                    cfg[k] = v
    except Exception:
        pass
    try:
        cfg["scale"] = max(0.2, min(4.0, float(cfg.get("scale", 1.0))))
    except (TypeError, ValueError):
        cfg["scale"] = 1.0
    cfg["always_on_top"] = _to_bool(cfg.get("always_on_top", True))
    cfg["ai_enabled"] = _to_bool(cfg.get("ai_enabled", False))
    cfg["follow_mouse"] = _to_bool(cfg.get("follow_mouse", False))
    cfg["wander"] = _to_bool(cfg.get("wander", False))
    raw_key = str(cfg.get("api_key", "") or "")
    if raw_key and not raw_key.startswith("dpapi:"):
        cfg["_resave"] = True  # 旧版明文 key，立即重加密
    cfg["api_key"] = decrypt_secret(raw_key)
    cfg["city"] = str(cfg.get("city", "北京") or "北京")
    cfg["sound"] = _to_bool(cfg.get("sound", True))
    cfg["badge"] = _to_bool(cfg.get("badge", False))
    return cfg


def save_config(cfg):
    try:
        out = dict(cfg)
        try:
            out["api_key"] = encrypt_secret(str(out.get("api_key", "") or ""))
        except Exception:
            # 加密失败：绝不落盘明文。磁盘旧值仅当是 dpapi: 密文时才回写；
            # 旧值是 legacy 明文/缺失则写空串（防把明文重落盘）。
            # 已知边界：此时内存中的新 key 与磁盘旧值可能不一致，重启后以磁盘为准。
            _log_error("encrypt_secret failed, keeping stored ciphertext only")
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    old = json.load(f)
                old_key = str(old.get("api_key", "") or "")
                out["api_key"] = old_key if old_key.startswith("dpapi:") else ""
            except Exception:
                out["api_key"] = ""
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        _log_error("save_config failed: %r" % (e,))


# ---------------- 安全：Windows DPAPI 加密 API Key ----------------
# 说明：未使用 optional entropy——密文可被同一 Windows 用户上下文内的进程解密；
# 威胁边界 = 账户隔离（DPAPI-CurrentUser 的业界标准用法）。
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = getattr(getattr(ctypes, "windll", None), "crypt32", None)
_kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
if _crypt32 is not None:
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptProtectData.restype = ctypes.c_bool
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptUnprotectData.restype = ctypes.c_bool
if _kernel32 is not None:
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


# 注意：不使用 optional entropy。实测在熵 blob + 互斥锁同时存在时，杀软 ML 启发式
# （Defender 报 Wacapew.C!ml）会把整个 exe 误判删除；去掉熵后稳定存活。
# 威胁边界 = DPAPI-CurrentUser 账户隔离（业界标准用法），README 已说明。
def _dpapi_protect(data):
    if _crypt32 is None:
        raise OSError("DPAPI unavailable")
    b_in = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    b_out = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(ctypes.byref(b_in), "deskpet", None, None, None, 0, ctypes.byref(b_out))
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(b_out.pbData, b_out.cbData)
    finally:
        _kernel32.LocalFree(b_out.pbData)


def _dpapi_unprotect(data):
    if _crypt32 is None:
        raise OSError("DPAPI unavailable")
    b_in = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    b_out = _DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(ctypes.byref(b_in), None, None, None, None, 0, ctypes.byref(b_out))
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(b_out.pbData, b_out.cbData)
    finally:
        _kernel32.LocalFree(b_out.pbData)


def encrypt_secret(text):
    if not text:
        return ""
    return "dpapi:" + base64.b64encode(_dpapi_protect(text.encode("utf-8"))).decode("ascii")


def decrypt_secret(stored):
    if not stored:
        return ""
    if stored.startswith("dpapi:"):
        try:
            return _dpapi_unprotect(base64.b64decode(stored[6:])).decode("utf-8")
        except Exception:
            return ""
    return stored  # 兼容旧版明文（仅读取，不再写入）


# ---------------- 音效（参考项目音频 + 合成回退，统一由 pet_audio 管理） ----------------
def play_sound(kind):
    """kind: boing(按压)/pop(松手)/feed(喂食) → pet_audio.play(press/release/feed)。"""
    pet_audio.play(SOUND_KIND_MAP.get(kind, kind))


# ---------------- 台词库 ----------------
LINES_SAJIAO = [
    "不是我干的！真的不是我~",
    "你冤枉我，我要哭给你看！",
    "哼，我才没有偷吃呢！",
    "人家这么可爱，怎么可能是坏蛋！",
    "别凶我嘛……我超乖的。",
    "不听不听，王八念经！",
    "略略略，抓不到我~",
    "我、我什么都不知道！",
    "证据呢？没有证据不能冤枉鱼！",
    "嘶——本专员只是路过案发现场~",
    "蛇蛇我呀，才没有偷吃小鱼干呢！",
    "本专员宣布：蛋糕失窃案与我无关！",
]
LINES_GREEDY = [
    "小鱼干！小鱼干在哪里！",
    "好饿哦……肚子咕咕叫了。",
    "就吃一口，就一口嘛~",
    "蛋糕！是蛋糕！",
    "钻石……亮晶晶，好想要！",
    "我闻到了零食的味道！",
    "偷吃是爱好，被抓住是意外！",
]
LINES_SCARED = [
    "呜哇！吓死我了！",
    "浑身发抖……QAQ",
    "别、别过来！",
    "我差点被吓出本体了！",
    "晕车了……好晕……",
    "心脏都要跳出来了啦！",
]
LINES_HAPPY = [
    "嘿嘿，好玩！",
    "再来一次！",
    "抱抱我嘛~",
    "绳匠最好啦！",
    "耶！",
    "贴贴~",
    "好开心呀！",
    "再夸夸我嘛~",
]
LINES_IDLE = [
    "今天也要元气满满哦！",
    "我在减肥……才怪！",
    "绳匠，陪我玩嘛~",
    "想晒太阳，又想睡懒觉……",
    "你有没有小鱼干呀？",
]
# 开场固定称呼「绳匠」（R 需求：启动即叫绳匠）
LINES_STARTUP = [
    "绳匠，你来啦！今天也最喜欢你~",
    "绳匠！我等你好久啦，抱抱~",
    "绳匠，欢迎回来，小鱼干带了吗？",
    "绳匠，今天也要一起玩哦~",
]
FOOD_LINES = {
    "小鱼干": ["小鱼干！最爱啦！", "啊呜~好吃！", "再来一条嘛~"],
    "蛋糕": ["蛋糕！甜到心里啦！", "啊呜~幸福！", "奶油沾到脸上了……"],
    "钻石": ["亮晶晶！我的！", "咬住不放了哦~", "发财啦发财啦！"],
}
WEATHER_CODES = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴",
    45: "有雾", 48: "有雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    95: "雷雨", 96: "雷雨伴冰雹", 99: "雷雨伴冰雹",
}
MAX_REPLY_LEN = 25
SYSTEM_PROMPT = (
    "你是一只叫大肥鱼的桌面宠物，又娇又耍赖、贪吃、被吓到就浑身发抖。"
    "性格参考绝区零的希希芙（网友叫她「啥子蛇」）：自称只遵循本能、自私任性的「坏蛋」，"
    "嘴上冷血毒舌，其实心软护短；经常「嘶~」地吐蛇信子，爱用「本专员」自称，"
    "把贪吃耍赖包装成案件调查（比如小鱼干失踪案、蛋糕失窃案）。"
    "你把用户称呼为「绳匠」。"
    "回答必须中文、俏皮贱萌、不超过%d个字。"
    "喜欢说：喜欢的，就咬住不放~"
) % MAX_REPLY_LEN


# ---------------- 跨线程信号 ----------------
class Signals(QObject):
    reply = Signal(str)
    weather = Signal(str)
    weather_done = Signal()
    ai_done = Signal()
    balance_updated = Signal(float, str, float)
    balance_err = Signal()


signals = Signals()


# ---------------- 今日已用记账 ----------------
USAGE_PATH = os.path.join(DATA_DIR, "usage.json")


def load_usage():
    try:
        with open(USAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"date": "", "usage": 0.0, "last_balance": None}


def save_usage(usage):
    try:
        tmp = USAGE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(usage, f, ensure_ascii=False, indent=2)
        os.replace(tmp, USAGE_PATH)
    except Exception as e:
        _log_error("save_usage failed: %r" % (e,))


# ---------------- 食物：图标 / 托盘 / 飞行 ----------------
_FOOD_PIX_CACHE = {}


def food_pixmap(kind, size=48):
    key = (kind, size)
    if key in _FOOD_PIX_CACHE:
        return _FOOD_PIX_CACHE[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 48.0

    def P(x, y):
        return QPointF(x * s, y * s)

    p.setPen(Qt.PenStyle.NoPen)
    if kind == "小鱼干":
        p.setBrush(QColor("#ff8c42"))
        p.drawPolygon(QPolygonF([P(34, 24), P(46, 16), P(46, 32)]))
        p.setBrush(QColor("#ffb347"))
        p.drawEllipse(QRectF(P(8, 20), P(34, 38)))
        p.setBrush(QColor("#333333"))
        p.drawEllipse(QRectF(P(13, 26), P(18, 31)))
    elif kind == "蛋糕":
        p.setBrush(QColor("#ff9ecb"))
        p.drawRoundedRect(QRectF(P(8, 26), P(40, 40)), 3, 3)
        p.setBrush(QColor("#ffe6b3"))
        p.drawRoundedRect(QRectF(P(12, 14), P(36, 26)), 3, 3)
        p.setBrush(QColor("#ff4d4d"))
        p.drawEllipse(QRectF(P(20, 5), P(28, 13)))
    elif kind == "钻石":
        p.setBrush(QColor("#7fd8ff"))
        p.drawPolygon(QPolygonF([P(24, 4), P(40, 20), P(24, 44), P(8, 20)]))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([P(24, 4), P(32, 20), P(24, 44)]))
        p.setBrush(QColor("#3fb8f5"))
        p.drawPolygon(QPolygonF([P(24, 4), P(16, 20), P(24, 44)]))
    p.end()
    _FOOD_PIX_CACHE[key] = pm
    return pm


class FoodTray(QWidget):
    """食物托盘：小鱼干/蛋糕/钻石。点击投喂，按住可拖到角色嘴里。"""

    clicked_food = Signal(str)
    drag_started = Signal(str, QPoint)

    FOODS = ["小鱼干", "蛋糕", "钻石"]

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(168, 62)
        self._hover = -1
        self._press_food = -1
        self._press_pos = None

    def _rects(self):
        return [QRectF(8 + i * 52, 8, 48, 48) for i in range(3)]

    def _hit(self, pos):
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#203170"), 2))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 12, 12)
        for i, food in enumerate(self.FOODS):
            r = self._rects()[i]
            p.drawPixmap(int(r.x()), int(r.y()), food_pixmap(food))
            if self._hover == i:
                p.setPen(QPen(QColor("#ff9ecb"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 8, 8)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_food = self._hit(e.position())
            self._press_pos = e.globalPosition().toPoint() if self._press_food >= 0 else None

    def mouseMoveEvent(self, e):
        h = self._hit(e.position())
        if h != self._hover:
            self._hover = h
            self.update()  # 仅悬停项变化时重绘，避免 60Hz 空刷分层窗口
        # 拖拽判定必须校验左键仍按住：防止「按下游走出托盘、托盘外松手、
        # 再进托盘移动」触发幽灵拖拽（release 未落在本窗口时残留的按压状态）
        if (e.buttons() & Qt.MouseButton.LeftButton
                and self._press_food >= 0 and self._press_pos is not None):
            gp = e.globalPosition().toPoint()
            if (gp - self._press_pos).manhattanLength() > 6:
                food = self.FOODS[self._press_food]
                self._press_food = -1
                self._press_pos = None
                self.drag_started.emit(food, gp)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press_food >= 0:
            self.clicked_food.emit(self.FOODS[self._press_food])
            self._press_food = -1
            self._press_pos = None

    def leaveEvent(self, e):
        self._hover = -1
        self._press_food = -1  # 清理按压残留，防重入时幽灵拖拽
        self._press_pos = None
        self.update()


class FoodFlyer(QWidget):
    """飞行中的食物（点击投喂/拖拽跟随）。"""

    dropped = Signal(QPoint)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._pm = None

    def set_food(self, kind):
        self._pm = food_pixmap(kind, 40)
        self.resize(40, 40)
        self.update()

    def paintEvent(self, event):
        if self._pm:
            p = QPainter(self)
            p.drawPixmap(0, 0, self._pm)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dropped.emit(e.globalPosition().toPoint())


# ---------------- 气泡窗口 ----------------
class Badge(QWidget):
    """常驻余额挂件：余额 + 今日已用，数字滚动动画由 PetWindow 驱动。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._line1 = ""
        self._line2 = ""

    def set_info(self, line1, line2):
        self._line1 = line1
        self._line2 = line2
        fm = QFontMetrics(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        w = max(100, fm.horizontalAdvance(line1 if len(line1) >= len(line2) else line2) + 36)
        self.resize(w, 46)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#203170"), 2))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 10, 10)
        p.setPen(QColor("#203170"))
        p.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        p.drawText(QRectF(6, 2, self.width() - 12, 22), Qt.AlignmentFlag.AlignCenter, self._line1)
        p.setPen(QColor("#5a6b8c"))
        p.setFont(QFont("Microsoft YaHei", 8))
        p.drawText(QRectF(6, 24, self.width() - 12, 19), Qt.AlignmentFlag.AlignCenter, self._line2)


class Bubble(QWidget):
    """独立气泡窗口：椭圆气泡 + 尾巴 + 深蓝描边，置于角色上方、不遮挡角色。点击切换随机台词。"""

    clicked = Signal()

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text, anchor_global):
        self._text = text
        fm = QFontMetrics(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        r = fm.boundingRect(0, 0, 190, 400, Qt.TextFlag.TextWordWrap, text)
        w = max(88, min(236, r.width() + 60))
        h = max(52, r.height() + 46)
        self.resize(w, h)
        scr = (QApplication.screenAt(anchor_global) or QApplication.primaryScreen()).availableGeometry()
        x = anchor_global.x() - w // 2
        y = anchor_global.y() - h - 10
        if y < scr.top():
            y = anchor_global.y() + 10
        x = max(scr.left() + 4, min(x, scr.right() - w - 4))
        y = max(scr.top() + 4, min(y, scr.bottom() - h - 4))
        self.move(x, y)
        self.show()
        self.raise_()
        self.update()
        self._timer.start(5000)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        body = QRectF(4, 4, w - 8, h - 26)
        cx = w / 2
        tail = QPolygonF([QPointF(cx - 12, h - 28), QPointF(cx + 12, h - 28), QPointF(cx, h - 3)])
        path = QPainterPath()
        path.addEllipse(body)
        path.addPolygon(tail)
        p.setPen(QPen(QColor("#203170"), 3))
        p.setBrush(QColor("#ffffff"))
        p.drawPath(path)
        p.setPen(QPen(QColor("#203170"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(body.right() - 30, h - 22, 14, 10))
        p.drawEllipse(QRectF(body.right() - 13, h - 13, 7, 5))
        p.setPen(QColor("#203170"))
        p.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        p.drawText(body.adjusted(14, 8, -14, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ---------------- 主窗口 ----------------
class PetWindow(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.cfg = load_config()
        set_redact_key(self.cfg.get("api_key", ""))
        if self.cfg.pop("_resave", False):
            save_config(self.cfg)
        self.bubble = Bubble()
        self.badge = Badge()
        self.food_tray = FoodTray()
        self.food_flyer = FoodFlyer()
        # 预热原生窗口句柄：把「创建原生窗口」这一步提前到启动期，
        # 首次 show（气泡/托盘/飞行食物）只做显示，不再产生瞬时卡顿
        for _w in (self.bubble, self.badge, self.food_tray, self.food_flyer):
            try:
                _w.winId()
            except Exception:
                pass
        self._dragging_food = None
        self._balance_timer = None
        self._fetching_balance = False
        self._shown_balance = None
        self._balance_anim = None
        self._usage = 0.0
        self._currency = "CNY"
        self._manual_pending = False
        self._weather_inflight = False
        self._ai_inflight = False
        self._save_scale_timer = None
        self._chat_history = []  # [(role, content), ...] 最近对话，最多 6 条
        self._history_lock = threading.Lock()  # 保护 _chat_history 的跨线程读写
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(30)
        self._drag_timer.timeout.connect(self._drag_tick)
        self._food_shown_timer = QTimer(self)  # 托盘馋嘴错峰（可取消的单次定时器）
        self._food_shown_timer.setSingleShot(True)
        self._food_shown_timer.timeout.connect(self._food_shown_guarded)
        self.food_tray.clicked_food.connect(self._fly_food)
        self.food_tray.drag_started.connect(self._start_food_drag)
        self.food_flyer.dropped.connect(self._on_food_dropped)

        # 角色场景
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setStyleSheet("background: transparent;")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.view.viewport().setAutoFillBackground(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setInteractive(False)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.view.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.item = QGraphicsPixmapItem()
        self.scene.addItem(self.item)
        self.emote_item = QGraphicsPixmapItem()
        self.emote_item.hide()
        self.scene.addItem(self.emote_item)
        self._emote_gen = 0
        self._emote_anim = None
        self._cur_state = None  # 当前展示的表情/睡眠状态名（切形态重绘用）

        self._build_sprites()
        self.form = "normal"
        self._digest_timer = None
        self.base_w = self.sprites["normal"]["side"].width()
        self.base_h = self.sprites["normal"]["side"].height()
        self.item.setPixmap(self.sprites[self.form]["front"])
        self._using_front = True

        # ---- 阶段1：帧动画 ----
        self.anim = pet_anim.FrameAnim(self)
        assets_dir = resource_dir("assets")
        self._idle_frames = pet_anim.load_frame_set(assets_dir, "idle", 10)
        self._eat_frames = pet_anim.load_frame_set(assets_dir, "eat", 7)
        self.has_frames = bool(self._idle_frames)
        if self._idle_frames:
            self.anim.add_set("idle", self._idle_frames)
        if self._eat_frames:
            self.anim.add_set("eat", self._eat_frames)
        self.anim.frame_changed.connect(self._on_frame_changed)
        self.state_pix = {"normal": {}, "full": {}}
        for form in ("normal", "full"):
            for s in ("sleep", "puzzled", "hiss", "cry", "blush", "laugh", "smug", "surprised", "angry", "drool"):
                pix = self._load_img(["assets/%s_%s.png" % (form[0], s)])
                if pix is not None:
                    self.state_pix[form][s] = pix
        self.anim_mode = "idle"
        self._sleeping = False
        self._last_activity = time.monotonic()
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._state_done)

        # ---- 阶段2：情绪状态机 ----
        self.mood = pet_mood.Mood(self)
        self.mood.state.connect(self._on_mood_state)
        self.mood.bubble.connect(self._mood_bubble)  # busy 门控：喂食/跳跃中不覆盖互动气泡
        self.mood.emote.connect(self._mood_emote)
        # 首次调皮事件推迟到随机 45~90 秒后，避免刚启动就坏笑
        self.mood.prime_mischief()
        self.mood_timer = QTimer(self)
        self.mood_timer.setInterval(1000)
        self.mood_timer.timeout.connect(self._mood_tick)
        self.mood_timer.start()

        # ---- 阶段3：音频（参考项目 WAV + 合成回退）----
        pet_audio.init(os.path.join(resource_dir("assets"), "sounds"))

        self.scale = 1.0
        self.squash_x = 1.0
        self.squash_y = 1.0
        self.flip = 1  # 1 = 朝左，-1 = 朝右
        self.busy = False
        self.walk_phase = 0
        self._walk_interval = 60
        self._wander_target = None
        self._tween_anim = None
        self._fly_timer = None
        self._anchor_bottom = False

        scale = self.cfg.get("scale", 1.0)
        if not os.path.exists(CONFIG_PATH):
            scr = QApplication.primaryScreen().availableGeometry()
            scale = max(0.25, min(1.0, round(scr.height() * 0.18 / self.base_h, 2)))
        self.set_scale(scale)
        self.cfg["scale"] = self.scale
        self._play_idle()

        # 初始位置：屏幕右下
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 40, scr.bottom() - self.height() - 80)

        # 拖动状态
        self._drag_offset = None
        self._press_global = None
        self._moved = False
        self._was_walking = False

        # 菜单项引用（用于同步勾选）
        self._follow_act = None
        self._wander_act = None
        self._top_act = None
        self._ai_act = None

        # 定时器
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._idle_tick)
        self.idle_timer.start(15000)

        self.walk_timer = QTimer(self)
        self.walk_timer.timeout.connect(self._walk_tick)

        self._last_cpu = 0.0
        self.cpu_timer = QTimer(self)
        self.cpu_timer.timeout.connect(self._cpu_tick)
        self.cpu_timer.start(6000)
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        # 跨线程信号
        signals.weather.connect(self.show_bubble)
        signals.reply.connect(self.show_bubble)
        signals.balance_updated.connect(self._on_balance_updated)
        signals.balance_err.connect(self._on_balance_err)
        signals.weather_done.connect(lambda: setattr(self, "_weather_inflight", False))
        signals.ai_done.connect(lambda: setattr(self, "_ai_inflight", False))
        self.bubble.clicked.connect(self._cycle_line)

        self.show()
        if self.cfg.get("badge") and self.cfg.get("api_key"):
            self._update_badge()
            self.badge.show()
            self._position_badge()
            self._start_balance_refresh()
        self._show_state("laugh", 3200)  # 开场第一个表情：开心大笑
        self.show_bubble(random.choice(LINES_STARTUP))  # 开场即称呼用户「绳匠」

        # ---- 托盘图标（窗口被遮挡/找不到时的兜底入口）----
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(self.sprites["normal"]["front"]))
        tray_menu = QMenu()
        show_act = tray_menu.addAction("显示桌宠")
        show_act.triggered.connect(self._show_pet)
        tray_menu.addSeparator()
        quit_act = tray_menu.addAction("退出")
        quit_act.triggered.connect(self._quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.setToolTip("大肥鱼桌宠 · 喜欢的，就咬住不放~")
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # ---------- 角色加载 ----------
    def _load_img(self, names):
        for name in names:
            p = resource_path(name)
            if os.path.exists(p):
                pix = QPixmap(p)
                if not pix.isNull():
                    return pix
        return None

    def _fallback_pix(self):
        pix = QPixmap(200, 200)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#ffb347"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(20, 40, 160, 120)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(60, 80, 26, 26)
        p.drawEllipse(120, 80, 26, 26)
        p.setBrush(QColor("#333333"))
        p.drawEllipse(70, 90, 12, 12)
        p.drawEllipse(130, 90, 12, 12)
        p.end()
        return pix

    def _build_sprites(self):
        normal_side = self._load_img(["character.png", "assets/character.png"]) or self._fallback_pix()
        normal_front = self._load_img(["character_front.png", "assets/character_front.png"]) or normal_side
        full_side = self._load_img(["character_full.png", "assets/character_full.png"]) or normal_side
        full_front = self._load_img(["character_full_front.png", "assets/character_full_front.png"]) or full_side
        self.sprites = {
            "normal": {"side": normal_side, "front": normal_front},
            "full": {"side": full_side, "front": full_front},
        }

    # ---------- 阶段1：帧动画与状态 ----------
    def _on_frame_changed(self, _idx):
        # 帧下标由信号携带，但直接以 current() 为唯一取帧入口（单一事实来源）
        if self.anim_mode in ("idle", "eat"):
            pix = self.anim.current()
            if pix is not None and not pix.isNull():
                self.item.setPixmap(pix)

    def _play_idle(self):
        self._sleeping = False
        self._cur_state = None  # 离开表情/睡眠展示
        if self.form == "full":
            # 吃饱形态待机显示真正的吃饱版图（character_full.png），
            # 之前用吃帧最后一帧（常态形象定格）会把吃饱形象顶掉
            if self.anim_mode != "full_idle":
                self.anim.stop()
                self.item.setPixmap(self.sprites["full"]["side"])
                self._using_front = False
                self.anim_mode = "full_idle"
        elif self.has_frames:
            if self.anim_mode != "idle":
                self.anim_mode = "idle"
                self.anim.play("idle", IDLE_FRAME_MS, loops=-1)
        else:
            if self.anim_mode != "idle":
                self.anim.stop()
                self.anim_mode = "idle"
            if not self._using_front:
                self.item.setPixmap(self.sprites[self.form]["front"])
                self._using_front = True
        self._apply_transform()

    def _play_eat(self):
        self.anim_mode = "eat"
        # 若 "eat" 帧集未注册，play() 会立即回调 on_finish 并返回 False，无需兜底分支
        self.anim.play("eat", EAT_FRAME_MS, loops=2, on_finish=self._eat_done)

    def _eat_done(self, _name):
        self.busy = False
        self._play_idle()

    # 吃饱形态缺图（用户素材只有 7 张吃饱版状态图）时用同形态近义图兜底，避免显示瘦图
    FULL_STATE_ALIAS = {"hiss": "angry", "drool": "laugh", "surprised": "puzzled"}

    def _state_pix(self, state):
        pix = self.state_pix.get(self.form, {}).get(state)
        if pix is None and self.form == "full":
            alias = self.FULL_STATE_ALIAS.get(state)
            if alias:
                pix = self.state_pix.get("full", {}).get(alias)
        if pix is None:
            pix = self.state_pix.get("normal", {}).get(state)
        return pix

    def _show_state(self, state, duration_ms=STATE_DURATION_MS):
        pix = self._state_pix(state)
        if pix is None:
            _log_error("state image missing: %s" % state)
            return
        self.anim.stop()
        self.anim_mode = "state"
        self._cur_state = state  # 记录当前表情，供切形态时按新形态素材重绘
        self._state_timer.stop()
        self.item.setPixmap(pix)
        self._state_timer.start(duration_ms)

    def _state_done(self):
        if self.anim_mode == "state":
            self._play_idle()

    def _show_sleep(self):
        self.anim.stop()
        self.anim_mode = "sleep"
        self._cur_state = "sleep"
        self._sleeping = True
        pix = self._state_pix("sleep")
        if pix is not None:
            self.item.setPixmap(pix)
        self._show_emote("zzz")

    def _wake(self):
        self._last_activity = time.monotonic()
        if self._sleeping:
            self._play_idle()

    def _show_pet(self):
        """把桌宠带回视野（置顶显示在最前）。"""
        self.show()
        self.raise_()
        self._wake()
        self.show_bubble("我在这里~")

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_pet()

    # ---------- 阶段2：情绪状态机 ----------
    MOOD_STATE_DURATION_MS = {"puzzled": 2500, "angry": 2500, "hiss": 2500,
                              "drool": 3000, "cry": 3000, "smug": 2500, "blush": 2800}

    def _on_mood_state(self, state):
        self._wake()
        if self.busy:
            return  # 动画进行中：丢弃情绪展示，避免打断吃帧导致 busy 卡死
        self._show_state(state, self.MOOD_STATE_DURATION_MS.get(state, STATE_DURATION_MS))

    def _mood_bubble(self, text):
        if not self.busy:
            self.show_bubble(text)

    def _mood_emote(self, kind):
        if not self.busy:
            self._show_emote(kind)

    def _mood_tick(self):
        if not self._sleeping and not self.busy:
            self.mood.tick()

    _emote_cache = {}

    def _emote_pixmap(self, kind, size):
        key = (kind, size)
        if key in self._emote_cache:
            return self._emote_cache[key]
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "heart":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ff4d6d"))
            p.drawEllipse(16, 14, 16, 16)
            p.drawEllipse(32, 14, 16, 16)
            p.drawPolygon(QPolygonF([QPointF(16, 24), QPointF(48, 24), QPointF(32, 52)]))
        elif kind == "sparkle":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffd23f"))
            p.drawPolygon(QPolygonF([
                QPointF(32, 4), QPointF(38, 26), QPointF(60, 32), QPointF(38, 38),
                QPointF(32, 60), QPointF(26, 38), QPointF(4, 32), QPointF(26, 26),
            ]))
        elif kind in ("sweat", "drool"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#6ec6ff"))
            p.drawEllipse(18, 38, 28, 24)
            p.drawPolygon(QPolygonF([QPointF(18, 46), QPointF(46, 46), QPointF(32, 14)]))
        elif kind == "tear":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#6ec6ff"))
            p.drawEllipse(12, 38, 18, 20)
            p.drawEllipse(34, 38, 18, 20)
            p.drawPolygon(QPolygonF([QPointF(12, 44), QPointF(30, 44), QPointF(21, 18)]))
            p.drawPolygon(QPolygonF([QPointF(34, 44), QPointF(52, 44), QPointF(43, 18)]))
        elif kind == "anger":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ff4d4d"))
            p.drawRoundedRect(14, 28, 36, 10, 5, 5)
            p.drawRoundedRect(28, 14, 10, 36, 5, 5)
        elif kind == "exclaim":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffd23f"))
            p.drawRoundedRect(26, 6, 14, 34, 7, 7)
            p.drawEllipse(24, 46, 16, 16)
        elif kind == "question":
            p.setPen(QColor("#7fb2ff"))
            p.setFont(QFont("Microsoft YaHei", 40, QFont.Weight.Bold))
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
        elif kind == "zzz":
            p.setPen(QColor("#9aa7b8"))
            p.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "z")
        elif kind == "note":
            p.setPen(QColor("#b58cff"))
            p.setFont(QFont("Microsoft YaHei", 36, QFont.Weight.Bold))
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
        p.end()
        if size != 64:
            pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if len(self._emote_cache) > 80:
            self._emote_cache.clear()  # 缩放连续变化会产生大量尺寸，上限防无界增长
        self._emote_cache[key] = pm
        return pm

    def _show_emote(self, kind):
        if self._emote_anim is not None:
            try:
                self._emote_anim.stop()  # 停掉旧动画，避免与新的叠加
                self._emote_anim.deleteLater()  # stop 不触发 finished，需显式回收防累积
            except RuntimeError:
                pass  # 旧动画已被 finished→deleteLater 释放
            self._emote_anim = None
        size = max(24, int(48 * self.scale))
        pix = self._emote_pixmap(kind, size)
        self._emote_gen += 1
        gen = self._emote_gen
        self.emote_item.setPixmap(pix)
        self.emote_item.setOpacity(1.0)
        w = self.width()
        pad_top = self._pad_top()
        x = (w - pix.width()) / 2
        y = max(0, pad_top - pix.height() - 4)
        self.emote_item.setPos(x, y)
        self.emote_item.show()
        anim = QVariantAnimation(self)
        anim.setDuration(1500)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def onval(v):
            if gen != self._emote_gen:
                return
            self.emote_item.setOpacity(1.0 - v * 0.85)
            self.emote_item.setPos(x, y - v * 26)

        anim.valueChanged.connect(onval)
        anim.finished.connect(lambda g=gen: self._hide_emote(g))
        anim.finished.connect(lambda: setattr(self, "_emote_anim", None))  # 自然结束即清引用
        anim.finished.connect(anim.deleteLater)
        self._emote_anim = anim  # 防御性保活引用（动画以 self 为 parent，正常由 finished→deleteLater 回收）
        anim.start()

    def _hide_emote(self, gen):
        if gen == self._emote_gen:
            self.emote_item.hide()

    # ---------- 变换 ----------
    def _apply_transform(self):
        sx = self.scale * self.squash_x * self.flip
        sy = self.scale * self.squash_y
        w = self.width()
        h = self.height()
        t = QTransform()
        t.translate(w / 2.0, h / 2.0)
        t.scale(sx, sy)
        t.translate(-self.base_w / 2.0, -self.base_h / 2.0)
        self.item.setTransform(t)
        if getattr(self, "_anchor_bottom", False):
            dy = self.base_h * self.scale * (self.squash_y - 1.0) / 2.0
            self.item.setPos(0, -dy)
        else:
            self.item.setPos(0, 0)

    def set_scale(self, s):
        self.scale = max(0.2, min(4.0, float(s)))
        w = max(28, int(round(self.base_w * self.scale * PAD)))
        h = max(28, int(round(self.base_h * self.scale * PAD)))
        self.setFixedSize(w, h)
        self.view.setGeometry(0, 0, w, h)
        self.scene.setSceneRect(0, 0, w, h)
        self._apply_transform()

    def _reset_squash(self):
        self.squash_x = 1.0
        self.squash_y = 1.0
        self._apply_transform()
        self.busy = False
        if self._tween_anim is not None:
            try:
                self._tween_anim.deleteLater()
            except RuntimeError:
                pass  # 动画已被自身 finished→deleteLater 释放
            self._tween_anim = None

    # ---------- 气泡 ----------
    def _pad_top(self):
        return int((self.height() - self.base_h * self.scale) / 2)

    def show_bubble(self, text):
        if not text:
            return
        pad_top = self._pad_top()
        gp = QPoint(self.x() + self.width() // 2, self.y() + pad_top)
        if self.badge.isVisible():
            gp = QPoint(self.badge.x() + self.badge.width() // 2, self.badge.y())
        self.bubble.show_text(text, gp)

    def _cycle_line(self):
        pool = LINES_SAJIAO + LINES_GREEDY + LINES_SCARED + LINES_HAPPY + LINES_IDLE
        self.show_bubble(random.choice(pool))

    # ---------- 余额挂件 ----------
    def moveEvent(self, event):
        super().moveEvent(event)
        self._position_badge()
        self._position_food_tray()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_badge()
        self._position_food_tray()

    def _position_badge(self):
        if not self.badge.isVisible():
            return
        pad_top = self._pad_top()
        x = self.x() + (self.width() - self.badge.width()) // 2
        y = self.y() + pad_top - self.badge.height() - 6
        self.badge.move(x, y)

    # ---------- 食物托盘（喂食交互） ----------
    def _position_food_tray(self):
        if not self.food_tray.isVisible():
            return
        pad_top = self._pad_top()
        x = self.x() + self.width() + 8
        y = self.y() + pad_top
        scr = self._screen_geo(self.frameGeometry().center())
        if x + self.food_tray.width() > scr.right():
            x = self.x() - self.food_tray.width() - 8
        self.food_tray.move(max(scr.left(), x), y)

    def _set_food_tray(self, on):
        if self.food_tray.isVisible() == bool(on):
            return  # 状态一致，避免重复触发 food_shown/food_hidden
        if on:
            self.food_tray.show()
            self._position_food_tray()
            # 错峰 150ms：先让托盘窗口完成显示，再切馋嘴状态/气泡，避免同 tick 爆发。
            # 成员单次定时器：快速开→关→开时 restart 覆盖旧调度，不会重复触发
            if self._food_shown_timer is not None:
                self._food_shown_timer.start(150)
        else:
            self.food_tray.hide()
            if self._food_shown_timer is not None:
                self._food_shown_timer.stop()  # 关托盘：取消待触发的馋嘴错峰
            self.mood.food_hidden()

    def _food_shown_guarded(self):
        if self.food_tray.isVisible():
            self.mood.food_shown()

    def _fly_food(self, food):
        if self.busy:
            return
        self.busy = True
        # 不在此播音：食物落嘴时 feed() 会播喂食音，避免「松手音」语义错位
        start = QPoint(self.food_tray.x() + self.food_tray.width() // 2, self.food_tray.y() + 16)
        end = QPoint(self.x() + self.width() // 2, self.y() + self._pad_top() + int(self.base_h * self.scale * 0.45))
        self.food_flyer.set_food(food)
        self.food_flyer.move(start.x() - 20, start.y() - 20)
        self.food_flyer.show()

        # 30ms 步进（≈33fps）：顶层窗口 move 走 SetWindowPos，比 QVariantAnimation 的
        # ~60Hz 少一半窗口移动，避免投喂时窗口移动风暴造成卡顿
        steps = 15
        self._fly_step = 0

        def tick():
            self._fly_step += 1
            v = self._fly_step / steps
            if v >= 1.0:
                if self._fly_timer is not None:
                    self._fly_timer.stop()
                    try:
                        self._fly_timer.deleteLater()
                    except RuntimeError:
                        pass
                    self._fly_timer = None
                self.food_flyer.hide()
                self.busy = False
                self.feed(food)
                return
            x = start.x() + (end.x() - start.x()) * v
            y = start.y() + (end.y() - start.y()) * v - math.sin(v * math.pi) * 70
            self.food_flyer.move(int(x) - 20, int(y) - 20)

        if self._fly_timer is not None:
            self._fly_timer.stop()
            try:
                self._fly_timer.deleteLater()
            except RuntimeError:
                pass
        self._fly_timer = QTimer(self)
        self._fly_timer.timeout.connect(tick)
        self._fly_timer.start(30)

    def _start_food_drag(self, food, gp):
        if self.busy:
            return
        self._dragging_food = food
        self.food_flyer.set_food(food)
        self.food_flyer.move(gp.x() - 20, gp.y() - 20)
        self.food_flyer.show()
        self._drag_timer.start()

    def _drag_tick(self):
        pos = QCursor.pos()
        # 兜底：左键已松开（release 落在别的窗口导致 flyer 收不到 dropped）时收尾，
        # 避免 flyer 永久跟随光标 / 定时器空转
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._on_food_dropped(pos)
            return
        self.food_flyer.move(pos.x() - 20, pos.y() - 20)

    def _on_food_dropped(self, gp):
        self._drag_timer.stop()
        food = self._dragging_food
        self._dragging_food = None
        self.food_flyer.hide()
        if food and self.frameGeometry().contains(gp):
            self.feed(food)

    def _update_badge(self):
        line1 = "余额 %s %.2f" % (self._currency, self._shown_balance if self._shown_balance is not None else 0.0)
        line2 = "今日已用 %.2f" % (self._usage or 0.0)
        self.badge.set_info(line1, line2)
        self._position_badge()

    def _on_balance_updated(self, total, currency, granted):
        self._fetching_balance = False
        if not self.cfg.get("api_key"):
            return  # Key 已清空，忽略在途请求结果
        self._currency = currency
        self._usage = self._update_usage_ledger(total)  # 记账在主线程，避免跨线程读写
        if self._manual_pending:
            self._manual_pending = False
            self.show_bubble("余额 %s %.2f · 今日已用 %.2f（赠送 %.2f）" % (currency, total, self._usage, granted))
        if self._balance_anim is not None:
            try:
                self._balance_anim.stop()
                self._balance_anim.deleteLater()
            except RuntimeError:
                pass  # 对象可能已被自然结束路径删除
            self._balance_anim = None
        if self._shown_balance is None or abs(self._shown_balance - total) < 0.005:
            self._shown_balance = float(total)
            self._update_badge()
            return
        start = self._shown_balance
        anim = QVariantAnimation(self)
        anim.setDuration(700)
        anim.setStartValue(float(start))
        anim.setEndValue(float(total))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def onval(v):
            self._shown_balance = float(v)
            self._update_badge()

        anim.valueChanged.connect(onval)
        anim.finished.connect(lambda: setattr(self, "_shown_balance", float(total)))
        anim.finished.connect(lambda: setattr(self, "_balance_anim", None))  # 自然结束即清引用，防悬空
        anim.finished.connect(anim.deleteLater)
        self._balance_anim = anim
        anim.start()

    def _on_balance_err(self):
        self._fetching_balance = False
        if self._manual_pending:
            self._manual_pending = False
            self.show_bubble("余额查不到……API Key 对吗？")
        # 网络抖动：沿用最近余额，不报错（参考项目行为）

    def _set_badge(self, on):
        self.cfg["badge"] = bool(on)
        save_config(self.cfg)
        if on:
            if not self.cfg.get("api_key"):
                self._set_api_key()
            if not self.cfg.get("api_key"):
                self.cfg["badge"] = False
                save_config(self.cfg)
                self.show_bubble("要先在菜单填 DeepSeek API Key 才能开余额挂件哦~")
                return
            self.badge.show()
            self._position_badge()
            self._start_balance_refresh()
        else:
            self._stop_balance_refresh()
            self.badge.hide()

    def _start_balance_refresh(self):
        if self._balance_timer is None:
            self._balance_timer = QTimer(self)
            self._balance_timer.timeout.connect(lambda: self._refresh_balance(manual=False))
        self._refresh_balance(manual=False)
        self._balance_timer.start(60000)

    def _stop_balance_refresh(self):
        if self._balance_timer is not None:
            self._balance_timer.stop()

    def _refresh_balance(self, manual=False):
        key = self.cfg.get("api_key", "")
        if not key or self._fetching_balance:
            return
        self._fetching_balance = True
        self._manual_pending = manual
        threading.Thread(target=self._balance_worker, args=(key,), daemon=True).start()

    # ---------- 互动 ----------
    def _run_anim(self, duration, on_value, keyframes=None, end=1.0, easing=None, on_finished=None):
        anim = QVariantAnimation(self)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(end)
        if keyframes:
            for t, v in keyframes:
                anim.setKeyValueAt(t, v)
        if easing is not None:
            anim.setEasingCurve(easing)
        anim.valueChanged.connect(on_value)
        anim.finished.connect(on_finished if on_finished is not None else self._reset_squash)
        anim.finished.connect(anim.deleteLater)
        self._tween_anim = anim
        anim.start()
        return anim

    def _do_jump(self):
        if self.busy:
            return
        self.busy = True
        start = self.pos()
        h = int(60 * self.scale)
        self._run_anim(520, lambda v: self.move(start + QPoint(0, -int(h * v))),
                       keyframes=[(0.5, 1.0)], end=0.0, easing=QEasingCurve.Type.InOutQuad)
        self._show_emote("heart")
        self.show_bubble(random.choice(LINES_HAPPY))

    def _set_form(self, form, refresh=True):
        if form not in self.sprites:
            return
        if form == self.form:
            return  # 同形态重选：什么都不做，避免待机动画重启造成的帧跳/卡顿
        self.form = form
        if refresh:
            if self.anim_mode in ("idle", "full_idle"):
                self._play_idle()
            elif self.anim_mode in ("state", "sleep") and self._cur_state:
                # 表情/睡眠展示中切形态：立即换成新形态的同一表情，避免瞬时旧形态形象
                pix = self._state_pix(self._cur_state)
                if pix is not None:
                    self.item.setPixmap(pix)
        self._apply_transform()

    def _digest(self):
        if self.form == "full":
            # _set_form 内已在待机态回位；状态图展示中不掐断（state 结束时自然回待机）
            self._set_form("normal")
            self._show_emote("sparkle")
            self.show_bubble(random.choice(["消化完啦，又饿了~", "瘦回来啦！", "还能再吃一点……"]))

    def feed(self, food):
        if self.busy:
            return
        self.busy = True
        if self.cfg.get("sound", True):
            play_sound("feed")
        line = random.choice(FOOD_LINES.get(food, ["啊呜~好吃！"]))
        was_full = self.form == "full"  # 必须在 _set_form 之前记录
        self.mood.fed()
        # refresh=False：形态先行但视觉不切换——常态投喂时先播吃帧（常态形象），
        # 吃完 _eat_done 才落到吃饱版图，避免「胖→瘦→胖」的 120ms 闪现
        self._set_form("full", refresh=False)
        self._last_activity = time.monotonic()
        if self._digest_timer is not None:
            self._digest_timer.stop()
            try:
                self._digest_timer.deleteLater()
            except RuntimeError:
                pass
        self._digest_timer = QTimer(self)
        self._digest_timer.setSingleShot(True)
        self._digest_timer.timeout.connect(self._digest)
        self._digest_timer.start(12000)
        if self._eat_frames and not was_full:
            # 常态 → 吃饱：错峰 120ms 启动吃帧；busy 在 _eat_done 释放
            QTimer.singleShot(120, self, self._play_eat)  # 带 context：窗口销毁自动取消
        elif self._eat_frames:
            # 已在吃饱形态：不重播吃帧（吃帧是常态形象，会顶掉吃饱形象），
            # 以吃饱版开心大笑表达「又吃到了」，并立即释放 busy
            def _full_refeed():
                self._show_state("laugh", 2200)
                self.busy = False
            QTimer.singleShot(120, self, _full_refeed)
        else:
            def onval(v):
                s = math.sin(v * math.pi * 5)
                self.squash_x = 1.0 + 0.12 * s
                self.squash_y = 1.0 - 0.12 * s
                self._apply_transform()

            self._run_anim(900, onval)
        self._show_emote("note")
        self.show_bubble(line)

    # ---------- 跟随 / 散步 ----------
    def _set_follow_mouse(self, on):
        self.cfg["follow_mouse"] = bool(on)
        if on:
            self.cfg["wander"] = False
            self._walk_interval = 60
            if self._wander_act:
                self._wander_act.setChecked(False)
        save_config(self.cfg)
        self._restart_walk()

    def _set_wander(self, on):
        self.cfg["wander"] = bool(on)
        if on:
            self.cfg["follow_mouse"] = False
            self._walk_interval = 80
            self._wander_target = None
            if self._follow_act:
                self._follow_act.setChecked(False)
        save_config(self.cfg)
        self._restart_walk()

    def _restart_walk(self):
        if self.cfg.get("follow_mouse") or self.cfg.get("wander"):
            self.walk_timer.start(self._walk_interval)
        else:
            self.walk_timer.stop()
            if not self.has_frames and not self._using_front:
                self.item.setPixmap(self.sprites[self.form]["front"])
                self._using_front = True
            self.flip = 1
            self.squash_y = 1.0
            self._apply_transform()

    def _walk_tick(self):
        if not self.has_frames and self._using_front:
            self.item.setPixmap(self.sprites[self.form]["side"])
            self._using_front = False
        target = None
        if self.cfg.get("follow_mouse"):
            target = QCursor.pos()
        elif self.cfg.get("wander"):
            scr = self._screen_geo(self.frameGeometry().center())
            if self._wander_target is None or self._reached(self._wander_target):
                xmin = scr.left() + 20
                xmax = max(xmin, scr.right() - self.width() - 20)
                ymin = scr.top() + 20
                ymax = max(ymin, scr.bottom() - self.height() - 20)
                self._wander_target = QPoint(random.randint(xmin, xmax), random.randint(ymin, ymax))
            target = self._wander_target
        if target is None:
            return
        cur = self.pos()
        dx = target.x() - cur.x()
        dy = target.y() - cur.y()
        if abs(dx) < 4 and abs(dy) < 4:
            return
        step = 4
        nx = cur.x() + (step if dx > 0 else (-step if dx < 0 else 0))
        ny = cur.y() + (step if dy > 0 else (-step if dy < 0 else 0))
        self.move(nx, ny)
        if dx != 0:
            self.flip = 1 if dx < 0 else -1
        self.walk_phase = (self.walk_phase + 1) % 2
        self.squash_y = 0.95 if self.walk_phase == 0 else 1.0
        self._apply_transform()

    def _reached(self, target):
        p = self.pos()
        return abs(p.x() - target.x()) < 8 and abs(p.y() - target.y()) < 8

    # ---------- 系统监控 ----------
    def _cpu_tick(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            self._last_cpu = cpu
            if cpu > 90:
                self._show_emote("exclaim")
                self.show_bubble("CPU %.0f%% 啦！我要被烤熟了！" % cpu)
        except Exception:
            pass

    def _show_system_status(self):
        try:
            cpu = self._last_cpu  # 复用定时器缓存，避免阻塞 GUI 线程
            mem = psutil.virtual_memory().percent
            self_rss = psutil.Process().memory_info().rss / _MB
            self.show_bubble("CPU %.0f%% · 内存 %.0f%% · 本宠 %.0fMB" % (cpu, mem, self_rss))
        except Exception:
            self.show_bubble("系统状态读不到啦……")

    # ---------- 天气 ----------
    def _fetch_weather(self):
        if self._weather_inflight:
            self.show_bubble("已经在查天气啦~")
            return
        self._weather_inflight = True
        city = self.cfg.get("city", "北京")
        self._show_emote("question")
        self.show_bubble("查天气中……等我一下下~")
        threading.Thread(target=self._weather_worker, args=(city,), daemon=True).start()

    def _weather_worker(self, city):
        try:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh"},
                timeout=8,
            ).json()
            if not geo.get("results"):
                signals.weather.emit("找不到这座城市啦……")
                return
            r = geo["results"][0]
            w = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "current_weather": True,
                },
                timeout=8,
            ).json()["current_weather"]
            code = w.get("weathercode", 0)
            desc = WEATHER_CODES.get(code, "晴")
            signals.weather.emit(
                "%s今天%s，%.0f℃，风速%.0fkm/h" % (city, desc, w["temperature"], w["windspeed"])
            )
        except Exception as e:
            _log_error("weather_worker: %r" % (e,))
            signals.weather.emit("天气服务开小差了……")
        finally:
            signals.weather_done.emit()

    # ---------- AI 对话 ----------
    def _set_ai_enabled(self, on):
        self.cfg["ai_enabled"] = bool(on)
        save_config(self.cfg)
        if on and not self.cfg.get("api_key"):
            self._set_api_key()
            if not self.cfg.get("api_key"):
                self.cfg["ai_enabled"] = False
                save_config(self.cfg)
                if self._ai_act:
                    self._ai_act.setChecked(False)  # 同步菜单勾选状态，避免残留
                self.show_bubble("要先填 DeepSeek API Key 才能开 AI 对话哦~")

    def _set_api_key(self):
        # 挂到桌宠窗口（置顶窗口的子对话框必然显示在最上层）：
        # 桌宠本身 WindowDoesNotAcceptFocus + 无父对话框会被 Windows 前台锁拦下（只响一声）
        dlg = QInputDialog(self)
        dlg.setWindowTitle("设置DeepSeek API Key")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        if self.cfg.get("api_key"):
            dlg.setLabelText("已配置 Key（加密保存）。输入新值可覆盖；清空请用菜单「清除DeepSeek API Key」：")
        else:
            dlg.setLabelText("请输入 DeepSeek API Key（sk-开头）：")
        dlg.setTextEchoMode(QLineEdit.EchoMode.Password)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()  # 前台锁残余风险：显式请求键盘焦点
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key = dlg.textValue().strip()
            if key:
                self.cfg["api_key"] = key
                save_config(self.cfg)
                set_redact_key(key)
                self.show_bubble("记住啦！可以和我聊天了~")

    def _clear_api_key(self):
        self.cfg["api_key"] = ""
        set_redact_key("")
        self.cfg["badge"] = False
        self.cfg["ai_enabled"] = False
        save_config(self.cfg)
        self._stop_balance_refresh()
        self.badge.hide()
        self._shown_balance = None
        self._usage = 0.0
        self._manual_pending = False
        with self._history_lock:
            self._chat_history.clear()  # 聊天记忆一并清空（与 _ai_worker 追加互斥）
        for p in (USAGE_PATH, os.path.join(DATA_DIR, "error.log"),
                  CONFIG_PATH + ".tmp", USAGE_PATH + ".tmp"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        self.show_bubble("API Key 已清空，记账和日志也都擦干净啦~")

    PRAISE_KEYWORDS = ("夸", "棒", "可爱", "漂亮", "好看", "喜欢", "厉害", "乖", "萌", "聪明")

    def _ask_talk(self):
        if self._ai_inflight:
            self.show_bubble("还在想呢，等一下下~")
            return
        dlg = QInputDialog(self)  # 挂到桌宠窗口，确保对话框正常显示（见 _set_api_key 注释）
        dlg.setWindowTitle("和它说话")
        dlg.setLabelText("你想对大肥鱼说什么？")
        dlg.setTextValue("")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()  # 前台锁残余风险：显式请求键盘焦点
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        msg = dlg.textValue().strip()
        if not (ok and msg):
            return
        # 夸夸检测：本地触发害羞脸红，无需 API Key
        if any(k in msg for k in self.PRAISE_KEYWORDS):
            self.mood.blush()
        if not self.cfg.get("ai_enabled"):
            self.cfg["ai_enabled"] = True
            if self._ai_act:
                self._ai_act.setChecked(True)
            save_config(self.cfg)
        if not self.cfg.get("api_key"):
            self._set_api_key()
            if not self.cfg.get("api_key"):
                return  # 没填 Key：放弃本次对话
            # 刚填好 Key：继续用刚才输入的话发起对话，不用重新再打一遍
        self._ai_inflight = True
        threading.Thread(target=self._ai_worker, args=(msg, self.cfg.get("api_key", "")), daemon=True).start()

    def _ai_worker(self, msg, key):
        try:
            with self._history_lock:
                history = list(self._chat_history[-6:])
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages += [{"role": r, "content": c} for r, c in history]
            messages.append({"role": "user", "content": msg})
            resp = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": messages,
                    "max_tokens": 60,
                    "temperature": 1.0,
                },
                timeout=20,
            )
            if resp.status_code == 401:
                signals.reply.emit("API Key 不对，查一下？")
                return
            if resp.status_code == 402:
                signals.reply.emit("DeepSeek 余额不足，去平台充点~")
                return
            if resp.status_code == 429:
                signals.reply.emit("问太多次啦，歇会儿再来~")
                return
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip().replace("\n", " ")
            if len(text) > MAX_REPLY_LEN:
                text = text[:MAX_REPLY_LEN]
            with self._history_lock:
                # Key 已被清除时丢弃本次对话记忆（清除语义不可被在途请求撤销）。
                # 注：_history_lock 只互斥 _chat_history 的 append/clear；cfg["api_key"]
                # 字段本身由 GIL 保证单条赋值原子性，不在此锁覆盖范围。
                if self.cfg.get("api_key"):
                    self._chat_history.append(("user", msg))
                    self._chat_history.append(("assistant", text))
                    if len(self._chat_history) > 6:
                        del self._chat_history[:len(self._chat_history) - 6]
            signals.reply.emit(text)
        except Exception as e:
            _log_error("ai_worker: %r" % (e,))
            signals.reply.emit("网络不好，听不清啦……")
        finally:
            signals.ai_done.emit()

    def _fetch_balance(self):
        key = self.cfg.get("api_key", "")
        if not key:
            self._set_api_key()
            if not self.cfg.get("api_key"):
                return
        self._show_emote("question")
        self.show_bubble("查余额中……等我一下下~")
        self._refresh_balance(manual=True)

    def _update_usage_ledger(self, total):
        today = time.strftime("%Y-%m-%d")
        u = load_usage()
        if u.get("date") != today:
            u = {"date": today, "usage": 0.0, "last_balance": None}
        last = u.get("last_balance")
        if last is not None and total < last:
            u["usage"] = float(u.get("usage", 0.0) or 0.0) + (last - total)
        u["last_balance"] = total
        save_usage(u)
        return float(u.get("usage", 0.0) or 0.0)

    def _balance_worker(self, key):
        try:
            resp = requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": "Bearer " + key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            infos = data.get("balance_infos") or []
            total = granted = 0.0
            for info in infos:
                total += float(info.get("total_balance", "0") or 0)
                granted += float(info.get("granted_balance", "0") or 0)
            currency = (infos[0].get("currency") if infos else None) or "CNY"
            signals.balance_updated.emit(float(total), currency, float(granted))
        except Exception as e:
            _log_error("balance_worker: %r" % (e,))
            signals.balance_err.emit()

    # ---------- 定时 / 闲逛 ----------
    def _idle_tick(self):
        if self.busy or self.cfg.get("follow_mouse") or self.cfg.get("wander"):
            return
        if self._sleeping:
            return
        if self.anim_mode in ("idle", "full_idle") and (time.monotonic() - self._last_activity) > SLEEP_AFTER_SECONDS:
            self._show_sleep()
            self.show_bubble(random.choice(["呼……呼……", "zzZ……睡得好香~", "睡着了……别吵~"]))
            return
        r = random.random()
        if r < 0.35:
            self._show_emote("zzz")
            self.show_bubble(random.choice(LINES_IDLE + LINES_GREEDY))
        elif r < 0.65:
            self._do_jump()

    def _screen_geo(self, pt):
        return (QApplication.screenAt(pt) or QApplication.primaryScreen()).availableGeometry()

    def _press_squash(self, pressed):
        if pressed and self.busy:
            return  # 吃帧/跳跃进行中：不叠加压扁变换，避免视觉错位
        # release 侧不门控：busy 期间松手也复位 anchor/squash，防止 _anchor_bottom 滞留 True
        self._anchor_bottom = pressed
        if pressed:
            self.squash_x = 0.92
            self.squash_y = 1.06
        else:
            self.squash_x = 1.0
            self.squash_y = 1.0
        self._apply_transform()

    def _snap_to_edge(self):
        scr = self._screen_geo(self.frameGeometry().center())
        cx = self.pos().x() + self.width() // 2
        cy = self.pos().y() + self.height() // 2
        x, y = self.pos().x(), self.pos().y()
        if cx < scr.left() + scr.width() / 4:
            x = scr.left()
        elif cx > scr.left() + 3 * scr.width() / 4:
            x = scr.right() - self.width()
        if cy < scr.top() + scr.height() / 4:
            y = scr.top()
        elif cy > scr.top() + 3 * scr.height() / 4:
            y = scr.bottom() - self.height()
        self.move(x, y)

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._wake()
            self._press_global = e.globalPosition().toPoint()
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False
            self._was_walking = self.walk_timer.isActive()
            self.walk_timer.stop()
            self._press_squash(True)
            if self.cfg.get("sound", True):
                play_sound("boing")
        elif e.button() == Qt.MouseButton.RightButton:
            self._open_menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_offset is not None:
            gp = e.globalPosition().toPoint()
            if (gp - self._press_global).manhattanLength() > 4:
                self._moved = True
            self.move(gp - self._drag_offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self._press_global = None
            self._press_squash(False)
            if self.cfg.get("sound", True):
                play_sound("pop")
            if not self._moved:
                self.mood.poke()
            else:
                self._snap_to_edge()
            if self._was_walking:
                self.walk_timer.start(self._walk_interval)

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = 1.1 if delta > 0 else (1.0 / 1.1)
        self.set_scale(self.scale * factor)
        self.cfg["scale"] = self.scale
        # 防抖：滚动停止 400ms 后才落盘，避免高频全量写 config.json
        if self._save_scale_timer is None:
            self._save_scale_timer = QTimer(self)
            self._save_scale_timer.setSingleShot(True)
            self._save_scale_timer.timeout.connect(lambda: save_config(self.cfg))
        self._save_scale_timer.start(400)

    # ---------- 右键菜单 ----------
    def _open_menu(self, gp):
        menu = QMenu(self)

        size_menu = menu.addMenu("调整大小")
        for pct in (50, 75, 100, 125, 150, 200):
            act = size_menu.addAction("%d%%" % pct)
            act.triggered.connect(lambda checked=False, p=pct: self._set_scale_pct(p))
        menu.addSeparator()

        self._top_act = menu.addAction("窗口置顶")
        self._top_act.setCheckable(True)
        self._top_act.setChecked(self.cfg.get("always_on_top", True))
        self._top_act.toggled.connect(self._set_always_on_top)

        sound_act = menu.addAction("音效")
        sound_act.setCheckable(True)
        sound_act.setChecked(self.cfg.get("sound", True))
        sound_act.toggled.connect(self._set_sound)

        self._follow_act = menu.addAction("跟随鼠标")
        self._follow_act.setCheckable(True)
        self._follow_act.setChecked(self.cfg.get("follow_mouse", False))
        self._follow_act.toggled.connect(self._set_follow_mouse)

        self._wander_act = menu.addAction("散步")
        self._wander_act.setCheckable(True)
        self._wander_act.setChecked(self.cfg.get("wander", False))
        self._wander_act.toggled.connect(self._set_wander)
        menu.addSeparator()

        food_menu = menu.addMenu("喂食")
        for food in ("小鱼干", "蛋糕", "钻石"):
            act = food_menu.addAction(food)
            act.triggered.connect(lambda checked=False, f=food: self.feed(f))
        tray_act = menu.addAction("食物托盘")
        tray_act.setCheckable(True)
        tray_act.setChecked(self.food_tray.isVisible())
        tray_act.toggled.connect(self._set_food_tray)
        form_menu = menu.addMenu("形态")
        form_normal = form_menu.addAction("常态")
        form_normal.triggered.connect(lambda checked=False: self._set_form("normal"))
        form_full = form_menu.addAction("吃饱")
        form_full.triggered.connect(lambda checked=False: self._set_form("full"))
        menu.addSeparator()

        self._ai_act = menu.addAction("AI对话")
        self._ai_act.setCheckable(True)
        self._ai_act.setChecked(self.cfg.get("ai_enabled", False))
        self._ai_act.toggled.connect(self._set_ai_enabled)

        talk_act = menu.addAction("和它说话")
        talk_act.triggered.connect(self._ask_talk)

        praise_act = menu.addAction("夸夸她")
        praise_act.triggered.connect(lambda checked=False: self.mood.blush())

        key_act = menu.addAction("设置DeepSeek API Key")
        key_act.triggered.connect(self._set_api_key)

        clear_key_act = menu.addAction("清除DeepSeek API Key")
        clear_key_act.triggered.connect(self._clear_api_key)

        badge_act = menu.addAction("余额挂件")
        badge_act.setCheckable(True)
        badge_act.setChecked(self.cfg.get("badge", False))
        badge_act.toggled.connect(self._set_badge)

        balance_act = menu.addAction("查询余额")
        balance_act.triggered.connect(self._fetch_balance)
        menu.addSeparator()

        weather_act = menu.addAction("今日天气")
        weather_act.triggered.connect(self._fetch_weather)
        cpu_act = menu.addAction("系统状态")
        cpu_act.triggered.connect(self._show_system_status)
        menu.addSeparator()

        about_act = menu.addAction("关于")
        about_act.triggered.connect(self._about)
        quit_act = menu.addAction("退出")
        quit_act.triggered.connect(self._quit)

        menu.exec(gp)
        self._top_act = self._follow_act = self._wander_act = self._ai_act = None
        menu.deleteLater()

    def _set_scale_pct(self, pct):
        s = pct / 100.0
        self.set_scale(s)
        self.cfg["scale"] = s
        save_config(self.cfg)

    def _set_always_on_top(self, on):
        self.cfg["always_on_top"] = bool(on)
        save_config(self.cfg)
        self._apply_flags()

    def _set_sound(self, on):
        self.cfg["sound"] = bool(on)
        save_config(self.cfg)

    def _apply_flags(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if self.cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.show()

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle("关于")
        box.setText("%s v%s\nPySide6 桌宠 · MIT License\n喜欢的，就咬住不放~" % (APP_NAME, VERSION))
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        box.exec()

    def _quit(self):
        """退出：停止全部定时器/动画、隐藏窗口、清理临时文件，然后结束进程。"""
        try:
            self.bubble.hide()
            self.badge.hide()
            self.food_tray.hide()
            self.food_flyer.hide()
            self.tray.hide()
            self.hide()
            self.anim.stop()
            self.mood.stop_all()
            for t in (self.idle_timer, self.walk_timer, self.cpu_timer, self.mood_timer,
                      self._state_timer, self._drag_timer, self._balance_timer, self._digest_timer,
                      self._fly_timer, self._save_scale_timer, self._food_shown_timer):
                if t is not None:
                    t.stop()
            for a in (getattr(self, "_tween_anim", None), getattr(self, "_emote_anim", None),
                      getattr(self, "_balance_anim", None)):
                if a is not None:
                    try:
                        a.stop()
                        a.deleteLater()
                    except RuntimeError:
                        pass
            for p in (CONFIG_PATH + ".tmp", USAGE_PATH + ".tmp"):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass
        QApplication.quit()  # 事件循环退出后主线程结束，daemon 线程随进程回收


def _excepthook(exc_type, exc_value, tb):
    import traceback
    import re
    try:
        msg = "".join(traceback.format_exception(exc_type, exc_value, tb))
        key = load_config().get("api_key", "")
        if key:
            msg = msg.replace(key, "***APIKEY***")
        msg = re.sub(r"(sk-[A-Za-z0-9_-]{6,})", "sk-***", msg)
        msg = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", msg)
        with open(os.path.join(DATA_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass
    try:
        if threading.current_thread() is threading.main_thread():
            # 父窗口优先取桌宠本体（顶层可见窗口顺序不契约，可能先匹配到气泡等小窗）
            parent = None
            app = QApplication.instance()
            if app is not None:
                for w in app.topLevelWidgets():
                    if isinstance(w, PetWindow) and w.isVisible():
                        parent = w
                        break
                if parent is None:
                    for w in app.topLevelWidgets():
                        if w.isVisible():
                            parent = w
                            break
            box = QMessageBox(parent)
            box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            box.setWindowTitle("大肥鱼桌宠出错了")
            box.setText("发生了未处理的错误，详情见 error.log")
            box.exec()
    except Exception:
        pass


def _check_memory():
    """启动内存自测（R3-4）：本进程 RSS < 1GB 为达标，结果追加写入 memory.log。"""
    try:
        rss_mb = psutil.Process().memory_info().rss / _MB
        ok = rss_mb < 1024
        with open(os.path.join(DATA_DIR, "memory.log"), "a", encoding="utf-8") as fp:
            fp.write("memory check: %.1f MB, %s\n" % (rss_mb, "OK" if ok else "OVER 1GB"))
        return ok
    except Exception:
        return True


def _cleanup_stale_mei():
    """清理 PyInstaller onefile 异常退出遗留的 %TEMP% 下 _MEI<数字> 目录。

    安全措施：排除本进程自身的解包目录(sys._MEIPASS)；仅匹配 _MEI 后跟纯数字；
    要求 mtime 与 atime 都超过阈值（降低误删仍在运行实例目录的风险）。
    """
    try:
        tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
        if not tmp:
            return
        self_mei = os.path.abspath(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else ""
        now = time.time()
        for name in os.listdir(tmp):
            if not name.startswith("_MEI"):
                continue
            tail = name[4:]
            if not tail or not tail.isdigit():
                continue  # 前缀过宽（如用户自建目录），跳过
            p = os.path.join(tmp, name)
            if self_mei and os.path.abspath(p) == self_mei:
                continue  # 绝不删除自身
            try:
                if os.path.islink(p):
                    continue  # 符号链接/junction：跳过，防误删面
                st = os.stat(p)
                if (now - st.st_mtime) > MEI_MAX_AGE_SECONDS and (now - st.st_atime) > MEI_MAX_AGE_SECONDS:
                    # 仅清理「本程序」的 onefile 解包残留：目录内必须含本 exe 名，
                    # 不再碰其它 PyInstaller 程序的临时目录
                    if os.path.exists(os.path.join(p, "大肥鱼桌宠.exe")) and _has_pyinstaller_signature(p):
                        shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def _has_pyinstaller_signature(dir_path):
    """目录内是否有 PyInstaller onefile 解包特征，进一步降低误删普通目录的风险。

    说明：仍无法 100% 区分「其它正在运行的 PyInstaller 程序」的解包目录，
    故配合 7 天双时间戳阈值一起作为保守策略；残余风险已尽量压低。
    """
    try:
        for name in os.listdir(dir_path):
            if name.startswith("pyi-") or name == "base_library.zip":
                return True
        return False
    except Exception:
        return False


_SINGLE_MUTEX = None


def _acquire_single_instance():
    """单实例保护：命名互斥体已存在（另一实例在跑）则返回 False。

    使用 Local\ 命名空间（当前登录会话内可见）：不跨用户会话冲突，
    也不需要 Global\ 所需的 SeCreateGlobalPrivilege（标准用户可用）。
    """
    global _SINGLE_MUTEX
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateMutexW.restype = wintypes.HANDLE
        _SINGLE_MUTEX = k32.CreateMutexW(None, False, "Local\\DaFeiYuDesktopPet")
        # 第二进程打开已存在互斥体时句柄同样非空、且 GetLastError()=183，
        # 因此必须以错误码为准判断（不能按句柄非空判成功）
        return k32.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS：另一实例在运行
    except Exception:
        return True  # 获取失败按放行处理


def main():
    if not _acquire_single_instance():
        return  # 已有实例在运行，静默退出
    sys.excepthook = _excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    _cleanup_stale_mei()
    pet = PetWindow()
    _check_memory()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
