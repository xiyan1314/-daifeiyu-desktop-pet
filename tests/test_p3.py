# -*- coding: utf-8 -*-
"""P3 可选项 + 人设自定义的纯逻辑回归：表情标记解析 / 加权动作目录 / 人设预设。"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import 桌宠 as main  # noqa: E402


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "MEMORY_PATH", str(tmp_path / "memory.json"))
    main.pet_log.set_data_dir(str(tmp_path))
    p = str(tmp_path / "config.json")
    monkeypatch.setattr(main, "CONFIG_PATH", p)
    yield p


# ---------------- P3-3：AI 表情标记解析 ----------------

def test_parse_emote_tag_hit():
    mode, kind, rest = main.parse_emote_tag("【happy】今天心情不错~")
    assert (mode, kind) == ("emote", "heart")
    assert rest == "今天心情不错~"


def test_parse_emote_tag_many_kinds():
    cases = {
        "【laugh】哈！": ("state", "laugh"),
        "【angry】哼！": ("state", "angry"),
        "【blush】才没有~": ("state", "blush"),
        "【cry】呜……": ("state", "cry"),
        "【smug】嘿嘿~": ("state", "smug"),
        "【puzzled】嗯？": ("state", "puzzled"),
        "【note】♪": ("emote", "note"),
        "【sparkle】✨": ("emote", "sparkle"),
    }
    for text, expect in cases.items():
        mode, kind, _rest = main.parse_emote_tag(text)
        assert (mode, kind) == expect, text


def test_parse_emote_tag_english_s_start():
    # 审查 M1 回归：】后的空白必须跳过（s*），英文 s 开头回复不能吞首字母
    mode, kind, rest = main.parse_emote_tag("【happy】so cute!")
    assert (mode, kind) == ("emote", "heart")
    assert rest == "so cute!"


def test_parse_emote_tag_pure_tag_returns_empty():
    # 纯标记回复：剥除后返回空文本，调用方兜底，绝不原样显示标记
    mode, kind, rest = main.parse_emote_tag("【happy】")
    assert (mode, kind) == ("emote", "heart")
    assert rest == ""


def test_parse_emote_tag_no_tag():
    mode, kind, rest = main.parse_emote_tag("普通回复没有标记")
    assert (mode, kind) == (None, None)
    assert rest == "普通回复没有标记"


def test_parse_emote_tag_unknown_tag_kept():
    mode, kind, rest = main.parse_emote_tag("【跳舞】自定义标记")
    assert (mode, kind) == (None, None)
    assert rest == "【跳舞】自定义标记"


def test_parse_emote_tag_empty():
    assert main.parse_emote_tag("") == (None, None, "")
    assert main.parse_emote_tag(None) == (None, None, "")


# ---------------- P3-2：加权动作目录 ----------------

def test_pick_idle_action_deterministic():
    # rnd=0.0 → 第一个动作（none 安静待着）；rnd≈1 → 最后一个（heart）
    name0, arg0 = main.pick_idle_action(lambda: 0.0)
    assert (name0, arg0) == ("none", None)
    name1, arg1 = main.pick_idle_action(lambda: 0.999)
    assert (name1, arg1) == ("emote", "heart")


def test_pick_idle_action_boundaries():
    # 权重边界：none[0,0.35) zzz[0.35,0.65) jump[0.65,0.9) note[0.9,0.94) sparkle[0.94,0.97) heart[0.97,1)
    assert main.pick_idle_action(lambda: 0.35) == ("emote", "zzz")
    assert main.pick_idle_action(lambda: 0.65) == ("jump", None)
    assert main.pick_idle_action(lambda: 0.9) == ("emote", "note")
    # rnd=1.0（越界防御）：回退第一个动作
    assert main.pick_idle_action(lambda: 1.0) == ("none", None)


def test_pick_idle_action_mid():
    name, arg = main.pick_idle_action(lambda: 0.4)
    assert (name, arg) == ("emote", "zzz")


def test_idle_actions_catalog_sane():
    total = sum(w for _, _, w in main.IDLE_ACTIONS)
    assert total == 100
    names = {n for n, _, _ in main.IDLE_ACTIONS}
    assert names == {"emote", "jump", "none"}
    # 有动作概率 ≈65%（none 35%），与旧 0.35/0.65 节奏相当
    active = sum(w for n, _, w in main.IDLE_ACTIONS if n != "none")
    assert active == 65


# ---------------- 人设预设（用户自定义人设） ----------------

def test_persona_presets_complete():
    assert set(main.PERSONA_PRESETS) == {"default", "sheshe", "tsundere"}
    assert "大肥鱼" in main.PERSONA_PRESETS["default"]
    assert "本专员" in main.PERSONA_PRESETS["sheshe"]
    assert "傲娇" in main.PERSONA_PRESETS["tsundere"]
    assert "绳匠" in main.PERSONA_PRESETS["sheshe"]


def test_load_config_normalizes_new_keys(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "ai_persona": "xxx", "click_through": "true"},
                  f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["ai_persona"] == "default"  # 未知预设 → 回退内置
    assert cfg["click_through"] is True   # 字符串布尔 → 归一化
    assert not any("ai_persona" in x for x in main.CONFIG_FIXES)  # 软修正不弹提示
    assert not any("click_through" in x for x in main.CONFIG_FIXES)


def test_load_config_custom_persona_kept(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "ai_persona": "custom",
                   "ai_system_prompt": "你是一只猫猫"}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["ai_persona"] == "custom"
    assert cfg["ai_system_prompt"] == "你是一只猫猫"


# ---------------- P3-1 配置默认值 ----------------

def test_click_through_default_off():
    assert main.DEFAULT_CONFIG["click_through"] is False
