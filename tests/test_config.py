# -*- coding: utf-8 -*-
"""P1-3 配置 schema 版本 / 迁移 / diff 存储 / 坏值修正提示的纯逻辑回归。"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import 桌宠 as main  # noqa: E402


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    # 同时隔离 DATA_DIR：load_config 的日志（_log_error）也落在临时目录，不污染真实 error.log
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "MEMORY_PATH", str(tmp_path / "memory.json"))
    main.pet_log.set_data_dir(str(tmp_path))  # pet_* 直连日志同样隔离
    p = str(tmp_path / "config.json")
    monkeypatch.setattr(main, "CONFIG_PATH", p)
    yield p


# ---------------- diff 存储 ----------------

def test_diff_save_only_changes(cfg_path):
    cfg = dict(main.DEFAULT_CONFIG)
    cfg["city"] = "上海"
    cfg["scale"] = 1.5
    main.save_config(cfg)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == main.CONFIG_SCHEMA_VERSION
    assert data["city"] == "上海"
    assert data["scale"] == 1.5
    assert data["api_key"] == ""  # api_key 恒落盘（清空也要持久）
    assert "ai_enabled" not in data  # 默认值不落盘
    assert "wander" not in data


def test_load_merges_diff_over_defaults(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "city": "上海"}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["city"] == "上海"
    assert cfg["scale"] == 1.0  # 未存 → 默认值
    assert cfg["ai_model"] == "deepseek-chat"


def test_default_value_reverts_to_default_on_save(cfg_path):
    cfg = dict(main.DEFAULT_CONFIG)
    cfg["scale"] = 1.0
    main.save_config(cfg)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert "scale" not in data


# ---------------- 迁移 ----------------

def test_legacy_v1_migrates_and_resaves(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"city": "东京", "scale": 2.0, "old_unknown_key": 123}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["city"] == "东京"
    assert cfg["scale"] == 2.0
    assert "old_unknown_key" not in cfg
    assert cfg.get("_resave") is True  # 旧版配置触发重存
    main.save_config(cfg)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == main.CONFIG_SCHEMA_VERSION
    assert "old_unknown_key" not in data


def test_forward_compat_newer_schema_no_rewrite(cfg_path):
    # 未来版本配置 + 认识的键里含坏值：归一化仅内存生效，绝不触发回写降级
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 99, "city": "上海", "scale": 99, "fancy_new_key": "x"},
                  f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["city"] == "上海"
    assert cfg["scale"] == 4.0  # 内存里按当前规则归一化可用
    assert "fancy_new_key" not in cfg
    assert cfg.get("_resave") is not True  # 关键：不回写，防降级丢未来键
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == 99  # 文件未被改写
    assert "fancy_new_key" in data


def test_migrate_config_idempotent():
    d = {"city": "上海"}
    assert main.migrate_config(d, 1) is True
    assert d["schema_version"] == main.CONFIG_SCHEMA_VERSION
    assert main.migrate_config(d, main.CONFIG_SCHEMA_VERSION) is True  # 已最新：幂等
    assert d["schema_version"] == main.CONFIG_SCHEMA_VERSION


def test_migrate_missing_step_does_not_stamp(cfg_path, monkeypatch):
    monkeypatch.setitem(main._CONFIG_MIGRATIONS, 1, None)
    d = {"city": "上海", "schema_version": 1}
    assert main.migrate_config(d, 1) is False
    assert d.get("schema_version") == 1  # 失败不盖章，防半成品数据被标成最新


# ---------------- 坏值修正提示 ----------------

def test_bad_values_fixed_and_reported(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"scale": 99, "chat_memory_rounds": "abc", "city": 123}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["scale"] == 4.0
    assert cfg["chat_memory_rounds"] == 3
    assert cfg["city"] == "123"
    assert cfg.get("_resave") is True
    assert any("scale" in x for x in main.CONFIG_FIXES)
    assert any("chat_memory_rounds" in x for x in main.CONFIG_FIXES)
    # 提示条目有长度上限，防气泡爆炸
    assert all(len(x) < 60 for x in main.CONFIG_FIXES)


def test_bad_bubble_style_reported_short(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"bubble_style": {"bg": "not-a-color", "font_size": 99}}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["bubble_style"]["bg"] == "#ffffff"  # 回退默认
    assert cfg["bubble_style"]["font_size"] == 18  # 钳制上限
    assert any("bubble_style" in x for x in main.CONFIG_FIXES)
    assert all(len(x) < 60 for x in main.CONFIG_FIXES)


def test_soft_normalization_no_alert(cfg_path):
    # 语义合法值的美化（bool 字符串 / 尾斜杠 / 台词 trim）不弹"坏值"提示，但会静默重存
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"always_on_top": "true", "ai_base_url": "http://x/v1/",
                   "lines_extra": {"sajiao": [" 你好~ "], "greedy": [], "happy": [], "idle": []}},
                  f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["always_on_top"] is True
    assert cfg["ai_base_url"] == "http://x/v1"
    assert cfg["lines_extra"]["sajiao"] == ["你好~"]
    assert main.CONFIG_FIXES == []  # 不弹提示
    assert cfg.get("_resave") is True  # 但仍会重存规范化结果


def test_valid_values_no_fixes(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "scale": 1.5, "city": "上海"}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert main.CONFIG_FIXES == []
    assert cfg.get("_resave") is not True


# ---------------- schema_version 边界 ----------------

def test_schema_version_weird_values(cfg_path):
    # 浮点：int(2.5)=2 的静默截断必须被拒绝，按 v1 处理
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2.5, "city": "上海"}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["city"] == "上海"
    assert cfg.get("_resave") is True  # 视为 v1 → 迁移重存
    # 字符串非法 → v1
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": "abc", "city": "上海"}, f, ensure_ascii=False)
    assert main.load_config().get("_resave") is True
    # 负数 → v1
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": -3, "city": "上海"}, f, ensure_ascii=False)
    assert main.load_config().get("_resave") is True


# ---------------- api_key 特殊通道 ----------------

@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 仅 Windows（ctypes CryptProtectData）")
def test_api_key_roundtrip_dpapi(cfg_path):
    cfg = dict(main.DEFAULT_CONFIG)
    cfg["api_key"] = "sk-test1234567890"
    main.save_config(cfg)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["api_key"].startswith("dpapi:")  # 明文绝不落盘
    cfg2 = main.load_config()
    assert cfg2["api_key"] == "sk-test1234567890"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 仅 Windows（ctypes CryptProtectData）")
def test_plaintext_key_triggers_reencrypt(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"api_key": "sk-legacy-plaintext", "city": "上海"}, f, ensure_ascii=False)
    cfg = main.load_config()
    assert cfg["api_key"] == "sk-legacy-plaintext"
    assert cfg.get("_resave") is True  # 旧版明文 key 触发重加密
    cfg.pop("_resave", None)
    main.save_config(cfg)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert str(data["api_key"]).startswith("dpapi:")  # 落盘已是密文


def test_api_key_clear_persists(cfg_path):
    cfg = dict(main.DEFAULT_CONFIG)
    cfg["api_key"] = ""
    main.save_config(cfg)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["api_key"] == ""
    assert main.load_config()["api_key"] == ""


# ---------------- P3-5+：帧上限用户可调 ----------------

def test_role_frame_max_normalized(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "role_frame_max": 999}, f, ensure_ascii=False)
    assert main.load_config()["role_frame_max"] == 60  # 越界钳到上限
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "role_frame_max": "abc"}, f, ensure_ascii=False)
    assert main.load_config()["role_frame_max"] == 24  # 非法值回退默认
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2, "role_frame_max": 1}, f, ensure_ascii=False)
    assert main.load_config()["role_frame_max"] == 2  # 下限 2 帧


def test_pet_resources_frame_max_default():
    import pet_resources
    assert pet_resources.FRAME_MAX == 24  # 默认值；桌宠启动时按 cfg 同步


# ---------------- P1-手感：物理参数归一化 ----------------

def test_physics_default_off():
    assert main.DEFAULT_CONFIG["physics"]["enabled"] is False  # 默认关闭=行为不变


def test_physics_invalid_values_fall_back(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2,
                   "physics": {"enabled": True, "gravity": -5, "restitution": "abc",
                               "throwPower": 2.5}}, f, ensure_ascii=False)
    cfg = main.load_config()
    ph = cfg["physics"]
    assert ph["enabled"] is True
    assert ph["gravity"] == 1400.0   # 负数回退默认
    assert ph["restitution"] == 0.78  # 非数字回退默认
    assert ph["throwPower"] == 2.5    # 合法值保留
    # 软修正不弹「坏值」提示（physics 在 _SOFT_FIX_KEYS）
    assert not any("physics" in x for x in main.CONFIG_FIXES)


def test_physics_valid_values_kept(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2,
                   "physics": {"enabled": True, "gravity": 0, "ceilingBounce": False}},
                  f, ensure_ascii=False)
    ph = main.load_config()["physics"]
    assert ph["gravity"] == 0        # 漂浮模式
    assert ph["ceilingBounce"] is False


def test_physics_upper_bounds_clamped(cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 2,
                   "physics": {"restitution": 5.0, "gravity": 99999, "throwPower": 100}},
                  f, ensure_ascii=False)
    ph = main.load_config()["physics"]
    assert ph["restitution"] == 1.0   # 上界钳制（防反弹能量发散）
    assert ph["gravity"] == 10000.0
    assert ph["throwPower"] == 10.0


def test_physics_defaults_single_source():
    import pet_physics
    assert main.DEFAULT_CONFIG["physics"] == pet_physics.DEFAULT_PHYSICS  # 默认值单一来源锁定


def test_frame_max_read_and_import_side(tmp_path, monkeypatch):
    """FRAME_MAX 读侧截断与导入侧拒绝口径一致（monkeypatch 由 pytest 自动还原）。"""
    import pet_resources
    monkeypatch.setattr(pet_resources, "FRAME_MAX", 5)
    rid = "r1"
    frames = ["%s_f%02d.png" % (rid, i) for i in range(8)]
    with open(tmp_path / "roles.json", "w", encoding="utf-8") as f:
        json.dump({"roles": [{"id": rid, "name": "x", "file": "r1.png",
                              "frames": frames}], "active": ""},
                  f, ensure_ascii=False)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role = next((r for r in lib._data["roles"] if r.get("id") == rid), None)
    assert role is not None and len(role["frames"]) == 5  # 读侧截断到上限
    r2, e2 = lib.import_processed(None, None, "y",
                                  frames_src=["f%02d.png" % i for i in range(6)])
    assert r2 is None and "5" in (e2 or "")  # 导入侧拒绝且文案带当前上限

