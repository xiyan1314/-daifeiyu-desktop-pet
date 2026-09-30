# -*- coding: utf-8 -*-
"""pet_resources 纯逻辑回归（forms 迁移/帧数边界/内容校验）。"""
import json

import pytest

import pet_resources


@pytest.fixture()
def rl(tmp_path):
    return pet_resources.RoleLibrary(str(tmp_path))


def test_legacy_dual_migrates_to_forms(tmp_path):
    roles = {
        "roles": [{
            "id": "a1", "name": "旧双形态", "file": "a1.png",
            "form": "dual", "file_full": "a1_full.png", "added": "",
        }],
        "active": "a1",
    }
    (tmp_path / "roles.json").write_text(json.dumps(roles, ensure_ascii=False), encoding="utf-8")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    metas = lib.form_metas("a1")
    assert [m["name"] for m in metas] == ["常态", "吃饱"]


def test_legacy_single_one_form(tmp_path):
    roles = {"roles": [{"id": "a1", "name": "旧单形态", "file": "a1.png", "added": ""}], "active": ""}
    (tmp_path / "roles.json").write_text(json.dumps(roles, ensure_ascii=False), encoding="utf-8")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    assert len(lib.form_metas("a1")) == 1


def test_frames_min2_rejected(rl, tmp_path):
    p = tmp_path / "f.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)
    role, err = rl.import_processed(str(p), None, "n", frames_src=[str(p)])
    assert role is None and "至少需要 2 帧" in err


def test_forms_count_bounds(rl, tmp_path):
    p = tmp_path / "f.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)
    role, err = rl.import_processed(str(p), None, "n", forms_src=[("a", str(p))] * 9)
    assert role is None and "1~8" in err


def test_invalid_png_rejected(rl, tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(b"not a png")
    role, err = rl.import_file(str(p))
    assert role is None and err

