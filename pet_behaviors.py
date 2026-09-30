# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 行为自定义服务（v2.0.2）
MIT License

职责：行为定义（动作序列）的增删改查、JSON 持久化（behaviors.json 原子写）、
导入/导出资源文件、序列校验与参数白名单。纯逻辑、Qt-free，可无 GUI 单测。

行为结构：{"id": "<8位hex>", "name": "ASCII 安全名", "steps": [{"act": ...}]}
动作类型与参数（UI 与校验共用 BEHAVIOR_ACTS 白名单）：
  play_action: {"act":"play_action","name":动作名}
  say:         {"act":"say","text":台词（截 80 字）}
  voice:       {"act":"voice","event":reply/feed/poke/sleep/wake}
  emote:       {"act":"emote","kind":note/sparkle/heart/zzz}
  form:        {"act":"form","name":形态键 f0/f1…（截 12 字符）}
  sleep:       {"act":"sleep"}（终止步：后续步骤不再执行）
  wait:        {"act":"wait","ms":100~30000}

执行调度由 PetWindow 主线程完成（_run_behavior/_behavior_step），本模块只做数据。
"""

import copy
import json
import os
import re
import tempfile
import time
import uuid

import pet_log

# v2.0.2：行为动作类型白名单（单一来源：校验 / 编辑对话框共用）
BEHAVIOR_ACTS = ("play_action", "say", "voice", "emote", "form", "sleep", "wait")
# 语音事件白名单（与 pet_voice.VOICE_EVENTS 同值；pet_behaviors 不依赖 pet_voice 的私有实现）
BEHAVIOR_VOICE_EVENTS = ("reply", "feed", "poke", "sleep", "wake")
BEHAVIOR_EMOTES = ("note", "sparkle", "heart", "zzz")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,23}$")
WAIT_MIN_MS, WAIT_MAX_MS = 100, 30000
STEPS_MAX = 20  # 单个行为最多 20 步

# v2.0.2：空闲/变身时长钳制界限（单一来源：normalize_cfg / 对话框 / 运行时共用；
# 空闲上界 60 = 入睡阈值，超过则入睡先于待机行为触发 → 死配置）
IDLE_SECS_MIN, IDLE_SECS_MAX = 5, 60
TRANSFORM_SECS_MIN, TRANSFORM_SECS_MAX = 3, 60

# 行为系统配置默认值（单一来源：桌宠 DEFAULT_CONFIG / pet_config.normalize_cfg 引用）
DEFAULT_BEHAVIOR_CFG = {
    "idle_behavior": "",          # 待机行为 id（"" = 不启用 → 现行为完全等价）
    "idle_behavior_seconds": 20,  # 无操作多少秒触发一次待机行为（默认 < 睡眠阈值 60s）
    "transform_seconds": 8,       # 变身持续秒数
}


def validate_name(name):
    """行为名：ASCII 安全名（英文字母开头，字母/数字/下划线 ≤24 字符）。"""
    return isinstance(name, str) and bool(NAME_RE.match(name))


def validate_steps(steps):
    """校验并归一化动作序列。返回 (norm_steps, err)；非法即 (None, 中文原因)。

    纯函数：UI 预览、导入、保存、测试共用同一口径（不静默丢步，错误明确）。
    """
    if not isinstance(steps, list) or not steps:
        return None, "动作序列不能为空"
    if len(steps) > STEPS_MAX:
        return None, "最多 %d 步" % STEPS_MAX
    out = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            return None, "第 %d 步不是有效动作" % (i + 1)
        act = st.get("act")
        if act not in BEHAVIOR_ACTS:
            return None, "第 %d 步动作类型不合法：%s" % (i + 1, act)
        item = {"act": act}
        if act == "play_action":
            name = str(st.get("name") or "").strip()
            if not name:
                return None, "第 %d 步缺少动作名" % (i + 1)
            item["name"] = name
        elif act == "say":
            text = str(st.get("text") or "").strip()
            if not text:
                return None, "第 %d 步台词为空" % (i + 1)
            item["text"] = text[:80]
        elif act == "voice":
            ev = str(st.get("event") or "")
            if ev not in BEHAVIOR_VOICE_EVENTS:
                return None, "第 %d 步语音事件不合法" % (i + 1)
            item["event"] = ev
        elif act == "emote":
            kind = str(st.get("kind") or "")
            if kind not in BEHAVIOR_EMOTES:
                return None, "第 %d 步表情不合法" % (i + 1)
            item["kind"] = kind
        elif act == "form":
            fname = str(st.get("name") or "").strip()
            if not fname:
                return None, "第 %d 步缺少形态名" % (i + 1)
            item["name"] = fname[:12]
        elif act == "sleep":
            pass
        elif act == "wait":
            try:
                ms = int(st.get("ms", 500))
            except (TypeError, ValueError):
                ms = 500
            item["ms"] = min(WAIT_MAX_MS, max(WAIT_MIN_MS, ms))
        out.append(item)
    return out, ""


class BehaviorService:
    """行为库：behaviors.json 持久化 + 增删改查 + 导入导出。主线程调用。"""

    def __init__(self, data_dir, log=None):
        self._index = os.path.join(data_dir, "behaviors.json")
        self._log = log or pet_log.log_error
        self._behaviors = {}  # {id: behavior}
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        try:
            with open(self._index, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None  # 首次运行/损坏：空库（有意静默，首次运行常态）
        self._behaviors = {}
        if isinstance(data, dict):
            for b in (data.get("behaviors") or []):
                nb, err = self._norm_behavior(b)
                if nb is None:
                    # 坏条目=用户资产损坏：记日志留痕（不弹窗，静默恢复空库）
                    self._log("behavior index dropped bad entry: %s" % (err or "格式非法"))
                elif nb["id"] not in self._behaviors:
                    self._behaviors[nb["id"]] = nb

    def _save(self):
        try:
            tmp = self._index + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"behaviors": list(self._behaviors.values())},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._index)  # 原子写：半截文件不会被当作有效库
        except Exception as e:
            self._log("behavior index save failed: %r" % (e,))

    @staticmethod
    def _norm_behavior(b):
        """单条行为归一化：非法结构/非法名/非法序列返回 (None, err)。"""
        if not isinstance(b, dict):
            return None, "行为条目不是对象"
        bid = str(b.get("id") or "").strip()
        if len(bid) != 8 or any(c not in "0123456789abcdef" for c in bid):
            return None, "行为 id 非法"
        name = str(b.get("name") or "").strip()
        if not validate_name(name):
            return None, "行为名不合法（英文字母开头，字母/数字/下划线）"
        steps, err = validate_steps(b.get("steps"))
        if steps is None:
            return None, err
        return {"id": bid, "name": name, "steps": steps}, ""

    # ---------- 查改 ----------
    def list(self):
        """全部行为（深拷贝，按 id 排序稳定输出；调用方变异不影响库内数据）。"""
        return [copy.deepcopy(b) for b in sorted(self._behaviors.values(), key=lambda x: x["id"])]

    def get(self, bid):
        b = self._behaviors.get(str(bid or ""))
        return copy.deepcopy(b) if b is not None else None

    def add(self, name, steps):
        """新增行为。返回 (behavior|None, err)。"""
        name = str(name or "").strip()
        if not validate_name(name):
            return None, "行为名不合法（英文字母开头，字母/数字/下划线）"
        norm, err = validate_steps(steps)
        if norm is None:
            return None, err
        bid = uuid.uuid4().hex[:8]
        while bid in self._behaviors:
            bid = uuid.uuid4().hex[:8]
        b = {"id": bid, "name": name, "steps": norm}
        self._behaviors[bid] = b
        self._save()
        return dict(b), ""

    def update(self, bid, name, steps):
        """改名/改序列（id 不变）。返回 (ok, err)。"""
        bid = str(bid or "")
        if bid not in self._behaviors:
            return False, "行为不存在"
        name = str(name or "").strip()
        if not validate_name(name):
            return False, "行为名不合法（英文字母开头，字母/数字/下划线）"
        norm, err = validate_steps(steps)
        if norm is None:
            return False, err
        self._behaviors[bid]["name"] = name
        self._behaviors[bid]["steps"] = norm
        self._save()
        return True, ""

    def delete(self, bid):
        bid = str(bid or "")
        if bid not in self._behaviors:
            return False, "行为不存在"
        self._behaviors.pop(bid, None)
        self._save()
        return True, ""

    # ---------- 导入 / 导出（行为资源） ----------
    def import_file(self, path):
        """导入行为资源 JSON：单条 {"name","steps"} / {"behavior":{...}} /
        全库格式 {"behaviors":[...]}（取数组第一条）。坏结构明确报错不抛异常。
        成功返回 (behavior|None, err)；重复导入生成新 id。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return None, "文件读取失败：%s" % e
        if isinstance(data, dict) and "behavior" in data:
            data = data["behavior"]
        if isinstance(data, dict) and "behaviors" in data:
            bl = data.get("behaviors")
            if not isinstance(bl, list) or not bl:
                return None, "行为文件内容不合法：behaviors 应为非空数组"
            data = bl[0]
        nb, err = self._norm_behavior(data)
        if nb is None:
            return None, "行为文件内容不合法：%s" % err
        nb["id"] = uuid.uuid4().hex[:8]
        while nb["id"] in self._behaviors:
            nb["id"] = uuid.uuid4().hex[:8]
        self._behaviors[nb["id"]] = nb
        self._save()
        return dict(nb), ""

    def export_file(self, bid, path):
        """导出单条行为为 JSON 资源文件。返回 (ok, err)。"""
        b = self.get(bid)
        if b is None:
            return False, "行为不存在"
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"behavior": b}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True, ""
        except Exception as e:
            return False, "导出失败：%s" % e

    # ---------- 待机行为 ----------
    def idle(self, cfg_getter):
        """当前配置指定的待机行为（dict 或 None）；id 不存在/为空 → None（现行为）。"""
        cfg = cfg_getter() or {}
        bid = str(cfg.get("idle_behavior") or "").strip()
        return self.get(bid) if bid else None


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_behaviors.py）
    svc = BehaviorService(os.path.join(tempfile.mkdtemp(prefix="bhv_"), "x"))
    b, err = svc.add("wave", [{"act": "say", "text": "嗨~"}, {"act": "wait", "ms": 200}])
    assert b is not None and not err, err
    assert svc.get(b["id"])["steps"][0]["act"] == "say"
    assert svc.delete(b["id"]) == (True, "")
    _bad, _e = validate_steps([{"act": "fly"}])
    assert _bad is None and "不合法" in _e
    print("SMOKE OK")