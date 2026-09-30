# -*- coding: utf-8 -*-
"""
配置辅助模块：DPAPI 加解密 + 配置归一化 + diff 落盘核心。

独立模块：不 import 桌宠.py（避免循环依赖）。
load_config / save_config 因 tests/_verify_v13 monkeypatch 桌宠.CONFIG_PATH 而保留在桌宠.py，
本模块只承载无模块全局依赖的纯逻辑部分。
"""
import base64
import ctypes
import json
import os

import pet_log  # P1-手感：物理参数非法时记日志（pet_log 无任何依赖，安全）
import pet_physics  # P1-手感：默认值单一来源（pet_physics 无 Qt 依赖，无环）

# 上界与设置对话框同口径（pet_dialogs.PhysicsDialog 的 spinbox 范围）
_PHYS_MAX = {"gravity": 10000.0, "restitution": 1.0,
             "groundFriction": 50.0, "throwPower": 10.0}


def normalize_physics(ph):
    """P1-手感：物理参数 dict 归一化（load_config 与 apply_physics 共用）。

    默认值取 pet_physics.DEFAULT_PHYSICS（单一来源）；负数/非数字回退默认、
    上界钳制，非法键收集进返回 dict 的 "_fixed" 列表（调用方记日志后剥除）。"""
    pd = dict(pet_physics.DEFAULT_PHYSICS)
    bad = []
    for k in ("gravity", "restitution", "groundFriction", "throwPower"):
        try:
            v = float(ph.get(k, pd[k]))
            if v < 0:
                raise ValueError
            pd[k] = min(v, _PHYS_MAX[k])
        except (TypeError, ValueError):
            bad.append(k)
    pd["enabled"] = _to_bool(ph.get("enabled", False))
    pd["ceilingBounce"] = _to_bool(ph.get("ceilingBounce", True))
    if bad:
        pd["_fixed"] = bad
    return pd
from ctypes import wintypes

from PySide6.QtGui import QColor

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


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


# ---------------- P1-3：配置归一化（load_config 用，就地修正） ----------------
def normalize_cfg(cfg, defaults, persona_ids):
    """P1-3 配置归一化：就地修正坏值 / 美化合法值，返回 cfg。

    defaults=调用方 DEFAULT_CONFIG、persona_ids=人设预设 id 集合（人设预设定义在
    load_config 之后，运行时注入才可用）。
    """
    try:
        cfg["scale"] = max(0.2, min(4.0, float(cfg.get("scale", 1.0))))
    except (TypeError, ValueError):
        cfg["scale"] = 1.0
    cfg["always_on_top"] = _to_bool(cfg.get("always_on_top", True))
    cfg["ai_enabled"] = _to_bool(cfg.get("ai_enabled", False))
    cfg["follow_mouse"] = _to_bool(cfg.get("follow_mouse", False))
    cfg["wander"] = _to_bool(cfg.get("wander", False))
    cfg["city"] = str(cfg.get("city", "北京") or "北京")
    cfg["sound"] = _to_bool(cfg.get("sound", True))
    cfg["badge"] = _to_bool(cfg.get("badge", False))
    # ---- v1.3 新增配置归一化 ----
    cfg["role"] = str(cfg.get("role", "") or "")
    cfg["scale_compensated_role"] = str(cfg.get("scale_compensated_role", "") or "")
    try:
        cfg["chat_memory_rounds"] = max(0, min(10, int(cfg.get("chat_memory_rounds", 3) or 3)))
        cfg["ai_max_tokens"] = max(16, min(512, int(cfg.get("ai_max_tokens", 60) or 60)))
        cfg["ai_reply_len"] = max(4, min(50, int(cfg.get("ai_reply_len", 25) or 25)))
    except (TypeError, ValueError):
        cfg["chat_memory_rounds"] = 3
        cfg["ai_max_tokens"] = 60
        cfg["ai_reply_len"] = 25
    cfg["ai_base_url"] = str(cfg.get("ai_base_url", "") or "").strip().rstrip("/")
    cfg["ai_model"] = str(cfg.get("ai_model", "deepseek-chat") or "deepseek-chat").strip()
    cfg["ai_system_prompt"] = str(cfg.get("ai_system_prompt", "") or "")
    cfg["ai_persona"] = str(cfg.get("ai_persona", "default") or "default")
    if cfg["ai_persona"] not in persona_ids and cfg["ai_persona"] != "custom":
        cfg["ai_persona"] = "default"  # 未知预设 id：回退内置人设
    cfg["click_through"] = _to_bool(cfg.get("click_through", False))
    try:
        cfg["role_frame_max"] = max(2, min(60, int(cfg.get("role_frame_max", 24) or 24)))
    except (TypeError, ValueError):
        cfg["role_frame_max"] = 24
    # P1-手感：物理参数归一化（默认值单一来源 pet_physics.DEFAULT_PHYSICS；
    # 负数/非数字回退默认并记日志、上界按设置对话框同口径钳制，不崩）
    _phys = cfg.get("physics")
    if not isinstance(_phys, dict):
        _phys = {}
    _pd = normalize_physics(_phys)
    if _pd.get("_fixed"):
        pet_log.log_error("load_config: 物理参数非法已回退默认: %s" % ",".join(_pd["_fixed"]))
        _pd.pop("_fixed")
    cfg["physics"] = _pd
    cfg["sound_group"] = "custom" if cfg.get("sound_group") == "custom" else "default"
    try:
        bs = cfg.get("bubble_style")
        if not isinstance(bs, dict):
            bs = {}
        bs = {
            "bg": str(bs.get("bg", "") or "#ffffff"),
            "fg": str(bs.get("fg", "") or "#203170"),
            "border": str(bs.get("border", "") or "#203170"),
            "font_size": int(bs.get("font_size", 10) or 10),
            "radius": int(bs.get("radius", 16) or 16),
        }
        for k in ("bg", "fg", "border"):
            if not QColor(bs[k]).isValid():
                bs[k] = defaults["bubble_style"][k]
        bs["font_size"] = max(8, min(18, bs["font_size"]))
        bs["radius"] = max(0, min(30, bs["radius"]))
        cfg["bubble_style"] = bs
    except Exception:
        cfg["bubble_style"] = dict(defaults["bubble_style"])
    for k in ("budget", "balance_alert"):
        try:
            cfg[k] = round(max(0.0, float(cfg.get(k, 0.0) or 0.0)), 2)
        except (TypeError, ValueError):
            cfg[k] = 0.0
    le = cfg.get("lines_extra")
    norm_le = {}
    if isinstance(le, dict):
        for k in ("sajiao", "greedy", "happy", "idle"):
            v = le.get(k)
            if isinstance(v, list):
                norm_le[k] = [str(x).strip()[:60] for x in v if str(x).strip()][:20]
            else:
                norm_le[k] = []
    else:
        for k in ("sajiao", "greedy", "happy", "idle"):
            norm_le[k] = []
    cfg["lines_extra"] = norm_le
    return cfg


def write_config(path, cfg, defaults, schema_version, log, encrypt_fn):
    """save_config 核心：diff 存储（api_key 特殊处理）+ 原子替换。"""
    try:
        # P1-3：diff 存储——只落盘与默认值不同的键（api_key 特殊处理），schema 版本随写
        out = {"schema_version": schema_version}
        for k, v in cfg.items():
            if k in defaults and v != defaults[k]:
                out[k] = v
        try:
            out["api_key"] = encrypt_fn(str(cfg.get("api_key", "") or ""))
        except Exception:
            # 加密失败：绝不落盘明文。磁盘旧值仅当是 dpapi: 密文时才回写；
            # 旧值是 legacy 明文/缺失则写空串（防把明文重落盘）。
            # 已知边界：此时内存中的新 key 与磁盘旧值可能不一致，重启后以磁盘为准。
            log("encrypt_secret failed, keeping stored ciphertext only")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                old_key = str(old.get("api_key", "") or "")
                out["api_key"] = old_key if old_key.startswith("dpapi:") else ""
            except Exception:
                out["api_key"] = ""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        log("save_config failed: %r" % (e,))
