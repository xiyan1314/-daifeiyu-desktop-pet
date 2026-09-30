# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 角色导出/导入（v2.0.3）
MIT License

职责：把「角色（含全部素材文件）+ 行为库 + 可分享配置（语音开关/音效组/气泡样式/
自定义台词/待机行为选择）」打包成单个 .dfypet.zip 分享文件；导入侧解包、
校验素材完整性、生成新 id 防覆盖、缺资源明确报错。纯逻辑、Qt-free，可无 GUI 单测。

敏感内容默认不导出：config 只取白名单键（api_key 等密钥一律排除，manifest 里
记录被排除的键名）；语音只导出开关/合成参数，不导出用户音频片段文件。

包结构：
  manifest.json  {"format":"dfypet-role","version":1,"role":{...},"behaviors":[...],
                  "config":{...},"excluded":["api_key",...],"alarms":[闹钟设置]}
  roles/<文件名>  角色引用的全部 png（manifest.role 内以文件名引用）

闹钟设置（系统⑥）v2.0.5 已启用：manifest.alarms 携带闹钟列表
（铃声文件不随包，导入侧换默认提示音并明确警告）；缺失/未知字段宽容处理。
"""

import json
import os
import uuid
import zipfile

BUNDLE_FORMAT = "dfypet-role"
BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"

# 包容量上限（导出/校验同口径单一来源）：放宽到合法大角色必然往返成功
# （role_frame_max 可调至 60 帧 × 8 形态 × 多动作 + 各形态 side/front/states）
EXPORT_MAX_ENTRIES = 2000
EXPORT_MAX_BYTES = 512 * 1024 * 1024

# 可分享配置键白名单（导出/导入共用；api_key 等敏感键永不在此列）
EXPORT_CONFIG_KEYS = ("voice", "sound_group", "bubble_style", "lines_extra", "idle_behavior")
# 敏感键：默认不导出（manifest.excluded 记录，导入侧自然缺省）
SENSITIVE_KEYS = ("api_key",)


def _role_file_refs(role):
    """角色 dict 引用的全部相对文件名（file/file_full/顶层 frames 兼容视图/
    forms 的 file·front·animations 各动作帧·states 状态图），去重排序。

    与 RoleLibrary._role_paths 同口径 + 顶层 frames（第三方旧格式包兼容）；
    非字符串值（坏数据）一律跳过，防逐字符/整 list 冒充文件名造成乱码报错。"""
    names = []
    for v in (role.get("file"), role.get("file_full")):
        if isinstance(v, str) and v:
            names.append(v)
    if isinstance(role.get("frames"), list):
        names.extend(x for x in role["frames"] if isinstance(x, str))
    for fm in role.get("forms") or []:
        if not isinstance(fm, dict):
            continue
        for v in (fm.get("file"), fm.get("front")):
            if isinstance(v, str) and v:
                names.append(v)
        anims = fm.get("animations")
        if isinstance(anims, dict):
            for act in anims:
                lst = anims.get(act)
                if isinstance(lst, list):
                    names.extend(x for x in lst if isinstance(x, str))
        states = fm.get("states")
        if isinstance(states, dict):
            names.extend(v for v in states.values() if isinstance(v, str))
    return sorted(set(names))


def _remap_role_files(role, name_map):
    """把 role dict 里的全部文件名按 name_map 换成新名（导入防同名覆盖）。"""
    def _map(v):
        return name_map.get(str(v), str(v))
    out = dict(role)
    if out.get("file"):
        out["file"] = _map(out["file"])
    if out.get("file_full"):
        out["file_full"] = _map(out["file_full"])
    if isinstance(out.get("frames"), list):
        out["frames"] = [_map(x) for x in out["frames"] if isinstance(x, str)]
    forms = []
    for fm in out.get("forms") or []:
        if not isinstance(fm, dict):
            forms.append(fm)
            continue
        f2 = dict(fm)
        if f2.get("file"):
            f2["file"] = _map(f2["file"])
        if f2.get("front"):
            f2["front"] = _map(f2["front"])
        if isinstance(f2.get("animations"), dict):
            f2["animations"] = {a: [_map(x) for x in lst] if isinstance(lst, list) else lst
                                for a, lst in f2["animations"].items()}
        if isinstance(f2.get("states"), dict):
            f2["states"] = {s: _map(p) if isinstance(p, str) else p
                            for s, p in f2["states"].items()}
        forms.append(f2)
    if forms:
        out["forms"] = forms
    return out


def build_manifest(role, behaviors, cfg, alarms=None):
    """构造导出 manifest。返回 (manifest, err)；角色缺文件引用报错。

    role=role_lib.get(rid)；behaviors=行为 dict 列表；cfg=当前配置 dict；
    alarms=闹钟 dict 列表（v2.0.5 起启用；None=不含闹钟设置）。
    """
    if not isinstance(role, dict) or not role.get("id"):
        return None, "角色不存在或数据为空"
    config = {}
    for k in EXPORT_CONFIG_KEYS:
        if k in cfg:
            config[k] = cfg[k]
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "role": dict(role),
        "behaviors": [dict(b) for b in (behaviors or []) if isinstance(b, dict)],
        "config": config,
        # 记录本次实际被排除的敏感键（cfg 里存在的那些；白名单才是真防线）
        "excluded": [k for k in SENSITIVE_KEYS if k in cfg],
        # v2.0.5：闹钟设置（铃声文件不随包，导入侧明确提示换默认音）
        "alarms": list(alarms) if isinstance(alarms, list) else None,
    }
    return manifest, ""


def export_bundle(role_lib, behaviors_svc, cfg, out_path, alarms_getter=None):
    """导出角色包到 out_path（zip）。返回 (ok, err)。

    收集 role_lib 当前角色的全部素材文件进 roles/ 子目录；缺文件明确报错。
    alarms_getter（可选）：返回闹钟 dict 列表，随包导出设置（不含铃声文件）。
    """
    rid = str((cfg or {}).get("role") or "")
    role = role_lib.get(rid) if rid else None
    if role is None:
        return False, "请先在「角色」面板选择一个自定义角色再导出"
    try:
        entries = []
        for ref in _role_file_refs(role):
            if ref != os.path.basename(ref):
                # 引用含路径分隔符 = 角色数据异常（正常管线不产生），拒绝自产坏包
                return False, "角色数据异常：引用含路径「%s」，请重新导入该角色" % ref
            p = role_lib.resolve(ref)
            if not os.path.isfile(p):
                return False, "角色素材缺失，无法导出：%s" % ref
            entries.append((ref, p))
        _behaviors = behaviors_svc.list() if behaviors_svc is not None else []
        _alarms = alarms_getter() if alarms_getter is not None else None
        manifest, err = build_manifest(role, _behaviors, cfg or {}, _alarms)
        if manifest is None:
            return False, err
        tmp = out_path + ".tmp"
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
                for ref, p in entries:
                    zf.write(p, "roles/" + os.path.basename(ref))
            os.replace(tmp, out_path)  # 原子替换：半截包不会被当作有效文件
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass  # 有意忽略：残留临时文件清理尽力而为
            return False, "写入失败：%s" % e
        # 导出侧自校验：容量上限同口径，导出时即报错而不是让接收方导入才踩坑
        _m, _err = validate_bundle(out_path)
        if _m is None:
            try:
                os.remove(out_path)
            except Exception:
                pass  # 有意忽略：自校验失败包的清理尽力而为
            return False, "导出包自校验失败：%s" % _err
        return True, ""
    except Exception as e:
        return False, "导出失败：%s" % e


def validate_bundle(zip_path):
    """校验角色包结构与素材完整性。返回 (manifest, err)。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 恶意包防御：条目数/解压总量上限（防 zip 炸弹）——先于任何解压读取
            info = zf.infolist()
            if len(info) > EXPORT_MAX_ENTRIES or sum(i.file_size for i in info) > EXPORT_MAX_BYTES:
                return None, "角色包条目过多或体积过大，已拒绝"
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            except KeyError:
                return None, "不是角色包：缺少 manifest.json"
            except Exception as e:
                return None, "manifest.json 无法解析：%s" % e
            if not isinstance(manifest, dict):
                return None, "manifest 不是对象"
            if manifest.get("format") != BUNDLE_FORMAT:
                return None, "不是大肥鱼角色包（format=%r）" % manifest.get("format")
            role = manifest.get("role")
            if not isinstance(role, dict) or not role.get("file"):
                return None, "角色包缺少角色数据"
            # 坏结构明确报错：id 必须为非空字符串（缺失/数字 id 会产出幽灵角色）
            if not isinstance(role.get("id"), str) or not role.get("id", "").strip():
                return None, "角色包缺少角色 id"
            names = zf.namelist()
            missing = []
            for ref in _role_file_refs(role):
                if ref != os.path.basename(ref):
                    # 非法引用（含路径分隔符/上级目录）：直接拒绝，不做 basename 归一
                    return None, "角色包引用非法文件名：%s" % ref
                if "roles/" + ref not in names:
                    missing.append(ref)
            if missing:
                return None, "角色包素材缺失：%s" % "、".join(missing[:5])
            return manifest, ""
    except zipfile.BadZipFile:
        return None, "文件不是有效的 zip 包"
    except Exception as e:
        return None, "打开失败：%s" % e


def import_bundle(role_lib, behaviors_svc, cfg, zip_path, alarms_apply=None):
    """导入角色包：解包素材（换新文件名防覆盖）、注册角色与行为（新 id）、
    应用可分享配置与闹钟设置。返回 (result|None, err)；任何缺资源/坏结构明确报错。

    alarms_apply（可选）：接收包内闹钟设置列表、返回警告列表的回调
    （v2.0.5 起启用；未提供则按旧口径提示「尚未支持」）。
    result = {"role_id", "behavior_map": {旧id: 新id}, "warnings": [...]}
    """
    manifest, err = validate_bundle(zip_path)
    if manifest is None:
        return None, err
    warnings = []
    written = []          # 本次已解包的文件（异常时回滚）
    role_appended = False
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            role = dict(manifest["role"])
            # 素材换新文件名（防与现有角色文件同名覆盖），并重写全部引用
            name_map = {}
            for ref in _role_file_refs(role):
                new_name = "%s_i%s.png" % (uuid.uuid4().hex[:8], uuid.uuid4().hex[:6])
                src = zf.read("roles/" + os.path.basename(ref))
                dst = role_lib.resolve(new_name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(src)
                name_map[ref] = new_name
                written.append(dst)
            role = _remap_role_files(role, name_map)
            # 行为：全部换新 id 导入，记录旧→新映射（供 idle_behavior 重映射）
            # 恶意/坏结构防御：behaviors 非列表或条目非对象 → 跳过并记警告，不崩
            behavior_map = {}
            _bhvs = manifest.get("behaviors")
            if not isinstance(_bhvs, list):
                warnings.append("包内行为数据格式非法，已跳过")
                _bhvs = []
            for b in _bhvs:
                if not isinstance(b, dict):
                    warnings.append("跳过非法行为条目")
                    continue
                nb, berr = behaviors_svc.add(str(b.get("name") or "imported"),
                                             b.get("steps"))
                if nb is not None:
                    behavior_map[str(b.get("id") or "")] = nb["id"]
                else:
                    warnings.append("行为「%s」未导入：%s" % (b.get("name"), berr))
            # 应用可分享配置（白名单键；idle_behavior 经映射重指；
            # 坏值跳过并记警告——伪造包不得污染运行配置）
            _cfg = manifest.get("config") or {}
            if "idle_behavior" in _cfg:
                if not isinstance(_cfg["idle_behavior"], str):
                    warnings.append("包内待机行为配置非法，已跳过")
                    _cfg.pop("idle_behavior", None)
                else:
                    _old = str(_cfg["idle_behavior"] or "")
                    _cfg["idle_behavior"] = behavior_map.get(_old, "")
                    if _old and not _cfg["idle_behavior"]:
                        warnings.append("待机行为不在包内，已置为不启用")
            for k in ("voice", "bubble_style", "lines_extra"):
                if k in _cfg and not isinstance(_cfg[k], dict):
                    warnings.append("包内「%s」配置格式非法，已跳过" % k)
                    _cfg.pop(k, None)
            if "sound_group" in _cfg and _cfg["sound_group"] not in ("default", "custom"):
                warnings.append("包内音效组配置非法，已跳过")
                _cfg.pop("sound_group", None)
            for k in EXPORT_CONFIG_KEYS:
                if k in _cfg:
                    cfg[k] = _cfg[k]
            try:
                _ver = int(manifest.get("version") or BUNDLE_VERSION)
            except (TypeError, ValueError):
                _ver = BUNDLE_VERSION
            if _ver > BUNDLE_VERSION:
                warnings.append("包版本高于当前支持，部分内容可能未生效")
            # 角色最后入库：id 冲突换新（不覆盖现有角色）；写索引失败必须回滚
            if role_lib.get(str(role.get("id") or "")) is not None:
                role["id"] = uuid.uuid4().hex[:8]
            role["added"] = ""
            role_lib._data.setdefault("roles", []).append(role)
            role_appended = True
            _serr = role_lib._save()
            if _serr:
                role_lib._data["roles"] = [x for x in role_lib._data.get("roles", [])
                                           if x is not role]
                role_appended = False
                for p in written:
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except Exception:
                        pass  # 有意忽略：回滚清理尽力而为
                return None, "保存角色失败：%s" % _serr
            # 闹钟设置最后应用：角色入库成功才落地（导入事务性）；
            # 应用回调异常转警告，不撤销已成功的角色导入
            _alarms = manifest.get("alarms")
            if _alarms is not None:
                if not isinstance(_alarms, list):
                    warnings.append("包内闹钟设置格式非法，已跳过")
                elif alarms_apply is not None:
                    try:
                        warnings.extend(alarms_apply(list(_alarms)))
                    except Exception as e:
                        warnings.append("闹钟设置应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含闹钟设置，当前版本尚未支持，已忽略")
            return {"role_id": role["id"], "behavior_map": behavior_map,
                    "warnings": warnings}, ""
    except Exception as e:
        # 非事务回滚：清理本次已入索引的角色条目与已解包文件（尽力而为）
        if role_appended:
            try:
                role_lib._data["roles"].remove(role)
                role_lib._save()
            except Exception:
                pass  # 有意忽略：回滚保存尽力而为
        for p in written:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：回滚清理尽力而为
        return None, "导入失败：%s" % e


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_export.py）
    import tempfile
    _d = tempfile.mkdtemp(prefix="exp_")
    _role = {"id": "r1", "name": "x", "file": "a.png", "form": "single",
             "frames": ["a.png"], "added": ""}
    _m, _e = build_manifest(_role, [], {"api_key": "SECRET", "voice": {"enabled": False},
                                       "bubble_style": {}})
    assert _m is not None and not _e
    # 与 pytest 同口径：敏感值不进包、敏感键不进 config；excluded 记录键名（有意设计）
    assert "SECRET" not in json.dumps(_m)
    assert "api_key" not in _m["config"]
    assert _m["excluded"] == ["api_key"]
    assert "voice" in _m["config"] and "bubble_style" in _m["config"]
    print("SMOKE OK")
