# -*- coding: utf-8 -*-
"""v2.0.3 角色导出/导入回归：manifest 构造与敏感排除 / 引用收集与重映射 /
导出打包 / 包校验 / 导入 roundtrip / 冲突与缺资源报错。

纯逻辑（角色文件用假字节即可，导出导入不做图像解码）。
"""
import json
import os
import zipfile

import pytest

import pet_behaviors
import pet_export
import pet_resources


def _mk_role_files(tmp_path, role_id="r1"):
    """造一个双形态角色 + 全部素材假文件，写 roles.json。返回文件名字典。"""
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    files = {}
    for fn in ("base.png", "full.png", "f0.png", "f1.png", "front.png",
               "a1.png", "a2.png", "st.png"):
        p = roles_dir / fn
        p.write_bytes(b"\x89PNG fake " + fn.encode("utf-8"))
        files[fn] = p
    _index = {
        "roles": [{
            "id": role_id, "name": "分享角色", "file": "base.png", "form": "dual",
            "file_full": "full.png", "frames": ["f0.png"], "added": "",
            "forms": [
                {"name": "常态", "file": "f0.png", "front": "front.png",
                 "animations": {"idle": ["f0.png"], "dance": ["a1.png", "a2.png"]},
                 "states": {"blush": "st.png"}},
                {"name": "吃饱", "file": "f1.png"},
            ],
        }],
        "active": role_id,
    }
    (tmp_path / "roles.json").write_text(json.dumps(_index, ensure_ascii=False),
                                         encoding="utf-8")
    return files


def _cfg():
    return {"api_key": "SECRET-TOKEN", "role": "r1",
            "voice": {"enabled": True, "tts_mode": "api"},
            "sound_group": "custom", "bubble_style": {"font_size": 12},
            "lines_extra": {"sajiao": ["你好"]}, "idle_behavior": "abc12345",
            "city": "上海"}


# ---------------- manifest 构造与敏感排除 ----------------

def test_build_manifest_excludes_secrets():
    role = {"id": "r1", "name": "x", "file": "a.png", "form": "single",
            "frames": ["a.png"], "added": ""}
    m, err = pet_export.build_manifest(role, [{"id": "b1", "name": "hi",
                                               "steps": [{"act": "sleep"}]}], _cfg())
    assert m is not None and not err, err
    raw = json.dumps(m, ensure_ascii=False)
    assert "SECRET-TOKEN" not in raw  # 敏感值绝不进包
    assert "api_key" not in m["config"]  # 敏感键不在可分享配置里
    assert m["excluded"] == ["api_key"]  # 仅以键名记录被排除项（供导入侧提示）
    assert m["format"] == pet_export.BUNDLE_FORMAT
    assert m["alarms"] is None  # 不传 alarms → 不含闹钟设置（v2.0.5 起可选携带）
    assert m["config"]["voice"]["enabled"] is True  # 语音开关导出
    assert "city" not in m["config"]  # 白名单外键不导出
    assert m["behaviors"][0]["name"] == "hi"


def test_build_manifest_bad_role():
    m, err = pet_export.build_manifest(None, [], {})
    assert m is None and err
    m, err = pet_export.build_manifest({}, [], {})
    assert m is None and err


def test_role_file_refs_and_remap():
    role = {"file": "a.png", "file_full": "b.png",
            "forms": [{"file": "c.png", "front": "d.png",
                       "animations": {"idle": ["c.png", "e.png"]},
                       "states": {"blush": "f.png"}}]}
    refs = pet_export._role_file_refs(role)
    assert refs == ["a.png", "b.png", "c.png", "d.png", "e.png", "f.png"]  # 去重排序
    nm = {r: "N_" + r for r in refs}
    r2 = pet_export._remap_role_files(role, nm)
    assert r2["file"] == "N_a.png" and r2["file_full"] == "N_b.png"
    assert r2["forms"][0]["animations"]["idle"] == ["N_c.png", "N_e.png"]
    assert r2["forms"][0]["states"]["blush"] == "N_f.png"


# ---------------- 导出 / 校验 ----------------

def test_export_roundtrip(tmp_path):
    _mk_role_files(tmp_path)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    svc.add("wave", [{"act": "say", "text": "嗨"}])
    cfg = _cfg()
    out = str(tmp_path / "share.dfypet.zip")
    ok, err = pet_export.export_bundle(lib, svc, cfg, out)
    assert ok and not err, err
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        # 包内 = 归一化后角色实际引用的文件（f0/f1/front/a1/a2/st；
        # 旧的 base/full 是导入源名，归一化后不再被引用，不进包）
        for fn in ("f0.png", "f1.png", "front.png", "a1.png", "a2.png", "st.png"):
            assert "roles/" + fn in names  # 全部引用素材进包
        for fn in ("base.png", "full.png"):
            assert "roles/" + fn not in names
    m, err = pet_export.validate_bundle(out)
    assert m is not None and not err, err
    assert m["role"]["id"] == "r1" and len(m["behaviors"]) == 1


def test_export_no_role(tmp_path):
    _mk_role_files(tmp_path)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    ok, err = pet_export.export_bundle(lib, None, {"role": ""}, str(tmp_path / "x.zip"))
    assert not ok and "自定义角色" in err


def test_export_missing_file(tmp_path):
    _mk_role_files(tmp_path)
    (tmp_path / "roles" / "a2.png").unlink()  # 删掉 dance 第二帧
    lib = pet_resources.RoleLibrary(str(tmp_path))
    ok, err = pet_export.export_bundle(lib, None, _cfg(), str(tmp_path / "x.zip"))
    assert not ok and "缺失" in err and "a2.png" in err


def test_validate_bad_bundles(tmp_path):
    # 非 zip
    p1 = tmp_path / "bad.zip"
    p1.write_bytes(b"not a zip at all")
    m, err = pet_export.validate_bundle(str(p1))
    assert m is None and "zip" in err
    # 无 manifest
    p2 = tmp_path / "nomanifest.zip"
    with zipfile.ZipFile(p2, "w") as zf:
        zf.writestr("x.txt", "x")
    m, err = pet_export.validate_bundle(str(p2))
    assert m is None and "manifest" in err
    # format 不对
    p3 = tmp_path / "badformat.zip"
    with zipfile.ZipFile(p3, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "other", "role": {"file": "a.png"}}))
    m, err = pet_export.validate_bundle(str(p3))
    assert m is None and "角色包" in err
    # 素材缺失
    p4 = tmp_path / "missing.zip"
    with zipfile.ZipFile(p4, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"format": pet_export.BUNDLE_FORMAT,
             "role": {"id": "mm", "file": "gone.png"}}))
    m, err = pet_export.validate_bundle(str(p4))
    assert m is None and "缺失" in err


# ---------------- 导入 ----------------

def test_import_roundtrip_fresh(tmp_path):
    _mk_role_files(tmp_path)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    b1, _ = svc.add("wave", [{"act": "say", "text": "嗨"}])
    cfg = _cfg()
    cfg["idle_behavior"] = b1["id"]
    out = str(tmp_path / "share.zip")
    ok, err = pet_export.export_bundle(lib, svc, cfg, out)
    assert ok and not err, err
    # 导入到全新目录
    dst = tmp_path / "dst"
    dst.mkdir()
    lib2 = pet_resources.RoleLibrary(str(dst))
    svc2 = pet_behaviors.BehaviorService(str(dst))
    cfg2 = {"api_key": "KEEP-ME", "role": ""}
    res, err = pet_export.import_bundle(lib2, svc2, cfg2, out)
    assert res is not None and not err, err
    role2 = lib2.get(res["role_id"])
    assert role2 is not None and role2["name"] == "分享角色"
    # 素材已解包且文件名换新（与源目录文件名不同 → 无同名覆盖风险）
    assert role2["file"] != "base.png"
    assert os.path.isfile(lib2.resolve(role2["file"]))
    for fm in role2["forms"]:
        assert os.path.isfile(lib2.resolve(fm["file"]))
    assert os.path.isfile(lib2.resolve(role2["file_full"]))
    # 行为已导入且 id 换新
    assert len(svc2.list()) == 1 and svc2.list()[0]["id"] != b1["id"]
    # 配置白名单已应用；敏感键不受影响
    assert cfg2["voice"]["enabled"] is True
    assert cfg2["api_key"] == "KEEP-ME"
    # idle_behavior 经映射重指到新行为 id
    assert cfg2["idle_behavior"] == svc2.list()[0]["id"]
    assert not res["warnings"]


def test_import_id_collision_new_id(tmp_path):
    _mk_role_files(tmp_path)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    out = str(tmp_path / "share.zip")
    ok, err = pet_export.export_bundle(lib, None, _cfg(), out)
    assert ok and not err, err
    res, err = pet_export.import_bundle(lib, pet_behaviors.BehaviorService(str(tmp_path)),
                                        {"role": ""}, out)
    assert res is not None and not err, err
    assert res["role_id"] != "r1"  # 同库导入不覆盖原角色
    assert lib.get("r1") is not None


def test_import_idle_behavior_missing(tmp_path):
    _mk_role_files(tmp_path)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    out = str(tmp_path / "share.zip")
    cfg = _cfg()
    cfg["idle_behavior"] = "deadbeef"  # 引用不存在的行为
    ok, err = pet_export.export_bundle(lib, None, cfg, out)
    assert ok and not err, err
    dst = tmp_path / "dst2"
    dst.mkdir()
    cfg2 = {"role": ""}
    res, err = pet_export.import_bundle(pet_resources.RoleLibrary(str(dst)),
                                        pet_behaviors.BehaviorService(str(dst)),
                                        cfg2, out)
    assert res is not None and not err, err
    assert cfg2["idle_behavior"] == ""  # 映射不到 → 不启用
    assert any("待机行为" in w for w in res["warnings"])


def test_import_bad_zip(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"nope")
    res, err = pet_export.import_bundle(pet_resources.RoleLibrary(str(tmp_path)),
                                        pet_behaviors.BehaviorService(str(tmp_path)),
                                        {}, str(p))
    assert res is None and err


def test_validate_rejects_malicious(tmp_path):
    # 引用含路径（上级目录逃逸）→ 直接拒绝，不做 basename 归一
    p1 = tmp_path / "trav.zip"
    with zipfile.ZipFile(p1, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"format": pet_export.BUNDLE_FORMAT,
             "role": {"id": "tt", "file": "../../evil.png"}}))
        zf.writestr("roles/evil.png", b"x")
    m, err = pet_export.validate_bundle(str(p1))
    assert m is None and "非法" in err
    # 条目过多 → 拒绝（zip 炸弹防御；上限常量与导出同口径）
    p2 = tmp_path / "big.zip"
    with zipfile.ZipFile(p2, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"format": pet_export.BUNDLE_FORMAT,
             "role": {"id": "bb", "file": "a.png"}}))
        zf.writestr("roles/a.png", b"x")
        for i in range(pet_export.EXPORT_MAX_ENTRIES + 5):
            zf.writestr("roles/junk%d.png" % i, b"y")
    m, err = pet_export.validate_bundle(str(p2))
    assert m is None and ("过多" in err or "过大" in err)


def test_legacy_frames_bundle_refs_remap():
    """第三方旧格式包（file+frames 无 forms）：顶层 frames 参与收集与重映射。"""
    role = {"id": "L1", "name": "旧式", "file": "a.png", "form": "single",
            "frames": ["a.png", "b.png", "c.png"], "added": ""}
    refs = pet_export._role_file_refs(role)
    assert refs == ["a.png", "b.png", "c.png"]  # frames 全收集
    nm = {r: "N_" + r for r in refs}
    r2 = pet_export._remap_role_files(role, nm)
    assert r2["frames"] == ["N_a.png", "N_b.png", "N_c.png"]
    assert r2["file"] == "N_a.png"


def test_validate_rejects_missing_id(tmp_path):
    """坏结构明确报错：role.id 缺失/空/非字符串 → 拒绝（防幽灵角色）。"""
    for _i, bad_id in enumerate((None, "", 123)):
        p = tmp_path / ("idbad%d.zip" % _i)
        role = {"file": "a.png"}
        if bad_id is not None:
            role["id"] = bad_id
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("manifest.json", json.dumps(
                {"format": pet_export.BUNDLE_FORMAT, "role": role}))
            zf.writestr("roles/a.png", b"x")
        m, err = pet_export.validate_bundle(str(p))
        assert m is None and "id" in err, (bad_id, err)


def test_import_behaviors_not_list(tmp_path):
    # manifest.behaviors 非列表 → 不崩，导入角色本体成功且行为跳过
    p = tmp_path / "bhv.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"format": pet_export.BUNDLE_FORMAT,
             "role": {"id": "z1", "name": "z", "file": "a.png", "form": "single",
                      "frames": ["a.png"], "added": ""},
             "behaviors": {"not": "a list"}}))
        zf.writestr("roles/a.png", b"\x89PNG fake")
    dst = tmp_path / "dst3"
    dst.mkdir()
    res, err = pet_export.import_bundle(pet_resources.RoleLibrary(str(dst)),
                                        pet_behaviors.BehaviorService(str(dst)),
                                        {}, str(p))
    assert res is not None and not err, err
    assert res["role_id"] == "z1"
