# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 资源库模块（角色库 + 音频库，v1.3.0 新增）。

职责：参考 dsh-whale-widget 的「角色管理 / 音频片段管理 / 音效组」设计，把
自定义角色（透明 PNG）与自定义音频（wav/mp3）的导入、切换、重命名、删除，
以及自定义音效组（5 个事件槽位）的管理统一封装。供 pet_dialogs 的面板与
主程序（桌宠.py）调用。

对外接口：
- class RoleLibrary(data_dir)
    目录 data_dir/roles/，索引 data_dir/roles.json（{"roles":[...], "active":id}）。
    list_roles() -> [{"id","name","file","form","file_full","frames","added"}...]  # 默认角色不在列表
    active_id() -> str                                     # "" = 默认角色
    set_active(role_id) -> bool                            # "" 回默认
    active_path() -> str|None                              # 当前角色 png 绝对路径；默认角色 None
    path_for(role_id) -> str|None                          # 任意角色 png 绝对路径（面板预览用）
    path_for_full(role_id) -> str|None                     # 吃饱形态 png；单形态返回 None
    import_file(src, name=None) -> (role|None, err|None)   # 旧版单图导入（v1.3.0 兼容，单形态）
    import_processed(base_src, full_src=None, name=None,  # 单/双形态导入（面板新入口）
                      frames_src=None)                      #   full_src=None → form="single"；
                                                           #   frames_src=2~24 帧 → 帧动画角色
    delete(role_id) -> (bool, str)                         # 删全部素材文件+索引；active 则重置 ""
    get(role_id) -> dict|None
- class AudioLibrary(data_dir)
    目录 data_dir/audio/，索引 data_dir/audio.json
    （{"fragments":[...], "group":{"custom":{"press":...,"release":...,"feed":...,"reply":...,"coin":...}}}）。
    fragments() -> [{"id","name","file","ext","added","duration"}...]  # duration 仅 wav 探测
    fragment_path(fid) -> str|None
    import_file(src, name=None) -> (frag|None, err|None)   # 仅 .wav/.mp3，>20MB 拒绝
    delete(fid) -> (bool, str)                             # 被音效组槽位引用则同步置 ""
    rename(fid, new_name) -> (bool, str)
    group_slots() -> dict                                 # {"custom": {kind: fid|""|None}}
    set_slot(kind, fid) -> bool                           # kind 非法 False；""=静音；None=默认
    group_paths() -> dict                                 # {"press": path|""|None, ...}
                                                          #   None=未设置走内置默认；""=静音；
                                                          #   path=绝对路径（文件缺失返回 None）

实现要点：
- 纯标准库（os/json/time/uuid/shutil/wave），不依赖 PySide6，无 GUI 可运行。
- 全部文件 IO 走「写临时文件 + os.replace」原子替换；任何异常静默降级，
  以错误字符串返回，绝不向调用方抛异常。
- import_file 只校验扩展名与文件大小，不校验音频/图片内容（PNG 可加载性与
  透明通道由 pet_dialogs 用 QPixmap 把关）。
- 槽位三态：None（默认，走内置音效）/ ""（静音）/ 片段 id（自定义音）。

Python 3.8+ 兼容。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import json
import os
import shutil
import time
import uuid
import wave

# ---------------- 通用 IO 助手（原子替换，静默降级） ----------------
def _read_json(path, factory=dict):
    """读 JSON；文件缺失 / 损坏 / 结构非法时返回 factory() 默认值，绝不抛出。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return factory()


def _write_json(path, data):
    """原子写 JSON（临时文件 + os.replace）；成功返回 None，失败返回错误字符串。"""
    tmp = path + ".tmp"
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return None
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return str(e)


def _probe_png(path):
    """stdlib PNG 校验：魔数 + IHDR 尺寸合理。返回 (ok, err)。"""
    try:
        with open(path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return False, "不是有效的 PNG 文件"
            head = f.read(25)  # IHDR 长度(4) + 类型(4) + 数据(13) + CRC(4)
            if len(head) < 25 or head[4:8] != b"IHDR":
                return False, "PNG 头损坏"
            w = int.from_bytes(head[8:12], "big")
            h = int.from_bytes(head[12:16], "big")
            if w <= 0 or h <= 0 or w > 100000 or h > 100000:
                return False, "PNG 尺寸非法"
        return True, ""
    except Exception as e:
        return False, "无法读取：%s" % e


def _new_id():
    """生成片段/角色 id：8 位十六进制 uuid 前缀 + 时间戳，保证文件名安全且唯一。"""
    return uuid.uuid4().hex[:8] + "_" + str(int(time.time()))


def _probe_wav_ok(path):
    """WAV 头校验：PCM 且参数合理。返回 bool。"""
    try:
        with wave.open(path, "rb") as wf:
            nch, sw, fr, nf, ct, _ = wf.getparams()
        return ct == "NONE" and 0 < nf <= 25_000_000 and fr > 0 and nch > 0 and sw in (1, 2, 4)
    except Exception:
        return False


def _wav_duration(path):
    """用 wave 模块探测 WAV 时长（秒，两位小数）；失败 / 非 wav 返回 None。"""
    try:
        with wave.open(path, "rb") as wf:
            _nch, _sw, framerate, nframes, _ct, _x = wf.getparams()
        if framerate and nframes > 0:
            return round(nframes / float(framerate), 2)
    except Exception:
        pass
    return None


# ---------------- 角色库 ----------------
class RoleLibrary:
    """自定义角色管理：导入 / 切换 / 删除透明 PNG 角色，索引 roles.json。"""

    MAX_BYTES = 10 * 1024 * 1024  # 10MB 上限

    def __init__(self, data_dir):
        self._dir = os.path.join(data_dir, "roles")
        self._index = os.path.join(data_dir, "roles.json")
        self._data = {"roles": [], "active": ""}
        self._load()

    # ---------- 内部 ----------
    def _load(self):
        """读索引并归一化；active 指向已不存在的角色时重置为默认。"""
        data = _read_json(self._index)
        roles = data.get("roles") if isinstance(data.get("roles"), list) else []
        clean = []
        for r in roles:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id") or "")
            fname = str(r.get("file") or "")
            # 过滤非法条目：无 id / 无文件名 / 非 .png（否则 delete 会误删目录）
            if not rid or not fname or not fname.lower().endswith(".png"):
                continue
            file_full = str(r.get("file_full") or "")
            # form 归一化：只有带 file_full 的 dual 才算双形态，其余一律 single
            form = "dual" if (str(r.get("form") or "") == "dual" and file_full) else "single"
            frames = r.get("frames")
            if not isinstance(frames, list):
                frames = []
            frames = [str(x) for x in frames if str(x).lower().endswith(".png")][:60]
            # forms 归一化（v1.4 多形态）：新结构直接采用；旧 file/file_full 自动转换
            raw_forms = r.get("forms")
            if isinstance(raw_forms, list) and raw_forms:
                forms = []
                for fm in raw_forms[:8]:
                    if not isinstance(fm, dict):
                        continue
                    fn = str(fm.get("file") or "")
                    if not fn.lower().endswith(".png"):
                        continue
                    forms.append({
                        "name": str(fm.get("name") or "").strip()[:12] or "形态%d" % (len(forms) + 1),
                        "file": fn,
                    })
                if not forms:
                    forms = [{"name": "常态", "file": fname}]
            else:
                forms = [{"name": "常态", "file": fname}]
                if file_full:
                    forms.append({"name": "吃饱", "file": file_full})
            clean.append({
                "id": rid,
                "name": str(r.get("name") or "") or "未命名",
                "file": fname,
                "form": form,
                "file_full": file_full,
                "forms": forms,
                "frames": frames,
                "added": str(r.get("added") or ""),
            })
        active = str(data.get("active") or "")
        if active and not any(r["id"] == active for r in clean):
            active = ""
        self._data = {"roles": clean, "active": active}
        if active != str(data.get("active") or ""):
            _write_json(self._index, self._data)  # 修复损坏的 active 引用（失败静默）

    def _save(self):
        """原子落盘；返回错误字符串或 None。"""
        return _write_json(self._index, self._data)

    def _path(self, role):
        """角色 dict -> 文件绝对路径（file 为纯文件名时拼到 roles/ 目录下）。"""
        p = role.get("file") or ""
        if not os.path.isabs(p):
            p = os.path.join(self._dir, p)
        return p

    def _role_paths(self, role):
        """角色全部素材文件绝对路径（base + 各形态 + 动画帧，去重）。"""
        seen = set()
        out = []
        for p in [self._path(role)] + [
            (f if os.path.isabs(f) else os.path.join(self._dir, f))
            for f in [m.get("file") for m in role.get("forms") or []]
            + [role.get("file_full"), *[x for x in role.get("frames") or []]]
            if f
        ]:
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                out.append(p)
        return out

    @staticmethod
    def _cleanup_files(*paths):
        """尽力删除半成品文件（导入回滚用），任何异常静默。"""
        for p in paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # ---------- 对外 ----------
    def list_roles(self):
        """返回全部自定义角色
        [{"id","name","file","form","file_full","frames","added"}...]；
        默认角色不在列表。"""
        return [dict(r) for r in self._data["roles"]]

    def active_id(self):
        """当前角色 id；"" = 默认角色。"""
        return str(self._data.get("active") or "")

    def set_active(self, role_id):
        """切换角色；role_id="" 回默认。角色不存在返回 False。"""
        role_id = str(role_id or "")
        if role_id and self.get(role_id) is None:
            return False
        self._data["active"] = role_id
        return self._save() is None

    def active_path(self):
        """当前角色 png 绝对路径；默认角色或文件缺失返回 None。"""
        rid = self.active_id()
        if not rid:
            return None
        return self.path_for(rid)

    def path_for(self, role_id):
        """任意角色 png 绝对路径（存在才返回）；供面板预览使用。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return None
        p = self._path(r)
        try:
            return p if os.path.isfile(p) else None
        except Exception:
            return None

    def path_for_full(self, role_id):
        """角色第二形态 png 绝对路径（存在才返回）；单形态返回 None。

        v1.4 多形态下等价于 forms[1]；旧 file_full 记录由 _load 转进 forms。
        """
        metas = self.form_metas(role_id)
        if len(metas) >= 2:
            f = metas[1].get("file") or ""
            if not os.path.isabs(f):
                f = os.path.join(self._dir, f)
            try:
                return f if os.path.isfile(f) else None
            except Exception:
                return None
        return None

    def form_metas(self, role_id):
        """角色的形态列表 [{"name","file"}...]（v1.4 多形态）；旧角色由 _load 自动转换。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        return [dict(f) for f in r.get("forms") or []]

    def form_files(self, role_id):
        """各形态素材绝对路径（存在才保留）；全部缺失返回 []。"""
        return [p for p in self.form_paths(role_id) if p]

    def form_paths(self, role_id):
        """各形态素材绝对路径（与 form_metas 逐项对齐；缺失为 None）。

        主程序据此装配 sprites，保证 form_keys 与 sprites 键集一致（M2）。"""
        metas = self.form_metas(role_id)
        out = []
        for m in metas:
            p = m.get("file") or ""
            if not os.path.isabs(p):
                p = os.path.join(self._dir, p)
            try:
                out.append(p if os.path.isfile(p) else None)
            except Exception:
                out.append(None)
        return out

    def frames_for(self, role_id):
        """角色动画帧 png 绝对路径列表（都存在才返回）；无帧动画返回 []。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        out = []
        for fn in r.get("frames") or []:
            p = fn if os.path.isabs(fn) else os.path.join(self._dir, fn)
            try:
                if os.path.isfile(p):
                    out.append(p)
                else:
                    return []  # 帧文件缺失：整体视为无帧动画（回退静态）
            except Exception:
                return []
        return out

    def import_file(self, src, name=None):
        """旧版导入（v1.3.0 兼容）：只复制一张图，无「吃饱」变体（单形态）。

        面板入口已改用 import_processed（支持单/双形态 + 自动处理素材）。
        成功返回 (role, None)，失败 (None, err)。
        本库保持 Qt-free，只校验扩展名与大小；PNG 可加载性由调用方用 QPixmap 把关。"""
        try:
            if not src or not isinstance(src, str) or not os.path.isfile(src):
                return None, "文件不存在"
            if os.path.splitext(src)[1].lower() != ".png":
                return None, "仅支持 .png 角色图"
            try:
                if os.path.getsize(src) > self.MAX_BYTES:
                    return None, "文件超过 10MB，无法导入"
            except Exception:
                return None, "无法读取文件大小"
            _ok_png, _err_png = _probe_png(src)
            if not _ok_png:
                return None, _err_png  # D1：旧版入口也校验 PNG 内容，坏图不入库
            if name is None or not str(name).strip():
                name = os.path.splitext(os.path.basename(src))[0]
            name = str(name).strip()[:40] or "未命名"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建角色目录：%s" % e
            rid = _new_id()
            dst = os.path.join(self._dir, rid + ".png")
            try:
                shutil.copyfile(src, dst)
            except Exception:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)  # 半截文件清理，不留孤儿
                except Exception:
                    pass
                return None, "复制文件失败"
            role = {
                "id": rid,
                "name": name,
                "file": rid + ".png",
                "form": "single",
                "added": time.strftime("%Y-%m-%d"),
            }
            self._data["roles"].append(role)
            err = self._save()
            if err:
                # 索引写失败：回滚复制，避免孤儿文件
                try:
                    os.remove(dst)
                except Exception:
                    pass
                self._data["roles"].pop()
                return None, err
            return role, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def import_processed(self, base_src, full_src=None, name=None, frames_src=None, forms_src=None):
        """导入已自动处理的角色素材（面板新入口）。

        full_src 给路径 → 双形态（旧参数，等价 forms_src 两个形态）。
        frames_src 给 2~24 张已处理帧 → 帧动画角色：帧存为 <id>_f%02d.png，
        base 必须是首帧（"file" 指向 _f00），"frames" 记录全部帧文件名。
        forms_src 给 [(名字, png路径), ...]（1~8 个，v1.4 多形态）→
        形态文件存为 <id>_form%d.png，形态 0 即 base；记录 "forms"。
        成功返回 (role, None)，失败 (None, err)；任何失败都会清理半成品文件。
        """
        try:
            for label, src in (("常态", base_src), ("吃饱", full_src)):
                if src is None:
                    continue
                if not isinstance(src, str) or not os.path.isfile(src):
                    return None, "%s素材文件不存在" % label
                if os.path.splitext(src)[1].lower() != ".png":
                    return None, "%s素材必须是 png" % label
                try:
                    if os.path.getsize(src) > self.MAX_BYTES:
                        return None, "%s素材超过 10MB" % label
                except Exception:
                    return None, "无法读取文件大小"
            if frames_src is not None:
                if not isinstance(frames_src, list) or len(frames_src) < 2:
                    return None, "帧动画至少需要 2 帧"
                if len(frames_src) > 24:
                    return None, "帧动画最多 24 帧"
                for i, src in enumerate(frames_src):
                    if not isinstance(src, str) or not os.path.isfile(src):
                        return None, "第 %d 帧素材不存在" % (i + 1)
                    if os.path.splitext(src)[1].lower() != ".png":
                        return None, "第 %d 帧素材必须是 png" % (i + 1)
                    try:
                        if os.path.getsize(src) > self.MAX_BYTES:
                            return None, "第 %d 帧素材超过 10MB" % (i + 1)
                    except Exception:
                        return None, "无法读取文件大小"
            if forms_src is not None:
                if not isinstance(forms_src, list) or not (1 <= len(forms_src) <= 8):
                    return None, "形态数量必须在 1~8 之间"
                for i, fm in enumerate(forms_src):
                    if not isinstance(fm, (list, tuple)) or len(fm) != 2:
                        return None, "第 %d 个形态格式错误" % (i + 1)
                    src = fm[1]
                    if not isinstance(src, str) or not os.path.isfile(src):
                        return None, "第 %d 个形态素材不存在" % (i + 1)
                    if os.path.splitext(src)[1].lower() != ".png":
                        return None, "第 %d 个形态素材必须是 png" % (i + 1)
                    try:
                        if os.path.getsize(src) > self.MAX_BYTES:
                            return None, "第 %d 个形态素材超过 10MB" % (i + 1)
                    except Exception:
                        return None, "无法读取文件大小"
            if name is None or not str(name).strip():
                name = "未命名"  # base_src 是临时文件，不能用其文件名当角色名
            name = str(name).strip()[:40] or "未命名"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建角色目录：%s" % e
            rid = _new_id()
            dst_base = os.path.join(self._dir, rid + ".png")
            dst_full = os.path.join(self._dir, rid + "_full.png") if full_src else None
            dst_frames = []
            dst_forms = []
            try:
                if frames_src:
                    for i, src in enumerate(frames_src):
                        dst_frames.append(os.path.join(self._dir, "%s_f%02d.png" % (rid, i)))
                        shutil.copyfile(src, dst_frames[-1])
                    # 帧动画角色：base 即首帧（复制首帧到 <id>.png，保持静态预览/回退一致）
                    shutil.copyfile(frames_src[0], dst_base)
                else:
                    shutil.copyfile(base_src, dst_base)
                if dst_full is not None:
                    shutil.copyfile(full_src, dst_full)
                if forms_src is not None:
                    for i, (fm_name, fm_src) in enumerate(forms_src):
                        if i == 0:
                            dst_forms.append(dst_base)  # 形态 0 即 base
                        else:
                            d = os.path.join(self._dir, "%s_form%d.png" % (rid, i))
                            shutil.copyfile(fm_src, d)
                            dst_forms.append(d)
            except Exception:
                self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                return None, "复制文件失败"
            role = {
                "id": rid,
                "name": name,
                "file": rid + ".png",
                "form": ("multi" if (forms_src is not None and len(forms_src) >= 2)
                         else ("dual" if full_src else "single")),
                "added": time.strftime("%Y-%m-%d"),
            }
            if full_src:
                role["file_full"] = rid + "_full.png"
            if frames_src:
                role["frames"] = ["%s_f%02d.png" % (rid, i) for i in range(len(frames_src))]
            if forms_src is not None:
                role["forms"] = [
                    {"name": (fm[0].strip()[:12] if isinstance(fm[0], str) else "")
                             or "形态%d" % (i + 1),
                     "file": os.path.basename(dst_forms[i])}
                    for i, fm in enumerate(forms_src)
                ]
            else:
                # 旧参数路径（full_src）也落 forms，避免重启前后结构不一致
                role["forms"] = [{"name": "常态", "file": rid + ".png"}]
                if full_src:
                    role["forms"].append({"name": "吃饱", "file": rid + "_full.png"})
            self._data["roles"].append(role)
            err = self._save()
            if err:
                self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                self._data["roles"].pop()
                return None, err
            return role, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def delete(self, role_id):
        """删除角色（文件 + 索引项）；若为当前角色则重置为默认。返回 (bool, err)。

        边界：素材文件被占用时可能删第一张成功、第二张失败——此时索引未动，
        该角色仍在列表里但部分文件已消失（预览会提示文件缺失，重试删除即可）。"""
        role_id = str(role_id or "")
        r = self.get(role_id)
        if r is None:
            return False, "角色不存在"
        try:
            for p in self._role_paths(r):
                if os.path.exists(p):
                    os.remove(p)
        except Exception as e:
            return False, "删除文件失败：%s" % e
        self._data["roles"] = [x for x in self._data["roles"] if x["id"] != role_id]
        if self._data["active"] == role_id:
            self._data["active"] = ""
        err = self._save()
        if err:
            return False, err
        return True, ""

    def get(self, role_id):
        """按 id 取角色 dict（副本）；不存在返回 None。"""
        role_id = str(role_id or "")
        for r in self._data["roles"]:
            if r["id"] == role_id:
                return dict(r)
        return None


# ---------------- 音频库 ----------------
# 自定义音效组支持的 5 个事件槽位
SLOT_KINDS = ("press", "release", "feed", "reply", "coin")
_AUDIO_EXTS = (".wav", ".mp3")


class AudioLibrary:
    """自定义音频片段与音效组管理：导入 / 重命名 / 删除 / 槽位映射，索引 audio.json。"""

    MAX_BYTES = 20 * 1024 * 1024  # 20MB 上限

    def __init__(self, data_dir):
        self._dir = os.path.join(data_dir, "audio")
        self._index = os.path.join(data_dir, "audio.json")
        self._data = {
            "fragments": [],
            "group": {"custom": {k: None for k in SLOT_KINDS}},
        }
        self._load()

    # ---------- 内部 ----------
    def _load(self):
        """读索引并归一化：片段字段补齐、槽位三态（fid/""/None）校验。"""
        data = _read_json(self._index)
        frags = data.get("fragments") if isinstance(data.get("fragments"), list) else []
        clean = []
        for f in frags:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id") or "")
            if not fid:
                continue
            ext = str(f.get("ext") or "").lower()
            if ext and not ext.startswith("."):
                ext = "." + ext
            if ext not in _AUDIO_EXTS:
                continue  # 非法扩展名的残留项直接丢弃
            clean.append({
                "id": fid,
                "name": str(f.get("name") or "") or "未命名",
                "file": str(f.get("file") or ""),
                "ext": ext,
                "added": str(f.get("added") or ""),
                "duration": f.get("duration") if isinstance(f.get("duration"), (int, float)) else None,
            })
        group = data.get("group") if isinstance(data.get("group"), dict) else {}
        custom = group.get("custom") if isinstance(group.get("custom"), dict) else {}
        slots = {}
        for k in SLOT_KINDS:
            v = custom.get(k)
            if v is None or v == "" or isinstance(v, str):
                slots[k] = v
            else:
                slots[k] = None
        self._data = {"fragments": clean, "group": {"custom": slots}}

    def _save(self):
        """原子落盘；返回错误字符串或 None。"""
        return _write_json(self._index, self._data)

    def _get(self, fid):
        fid = str(fid or "")
        for f in self._data["fragments"]:
            if f["id"] == fid:
                return f
        return None

    # ---------- 对外 ----------
    def fragments(self):
        """全部片段 [{"id","name","file","ext","added","duration"}...]。"""
        return [dict(f) for f in self._data["fragments"]]

    def fragment_path(self, fid):
        """片段绝对路径；片段不存在或文件缺失返回 None。"""
        f = self._get(fid)
        if f is None:
            return None
        p = f.get("file") or ""
        if not os.path.isabs(p):
            p = os.path.join(self._dir, p)
        try:
            return p if os.path.isfile(p) else None
        except Exception:
            return None

    def import_file(self, src, name=None):
        """导入音频：复制到 audio/<id>.<ext>。仅 .wav/.mp3、>20MB 拒绝，不校验音频内容。"""
        try:
            if not src or not isinstance(src, str) or not os.path.isfile(src):
                return None, "文件不存在"
            ext = os.path.splitext(src)[1].lower()
            if ext not in _AUDIO_EXTS:
                return None, "仅支持 .wav / .mp3 音频"
            try:
                if os.path.getsize(src) > self.MAX_BYTES:
                    return None, "文件超过 20MB，无法导入"
            except Exception:
                return None, "无法读取文件大小"
            # D2：内容校验——损坏音频不入库（wav 走 wave 头校验；mp3 查 ID3/帧同步）
            if ext == ".wav":
                if _wav_duration(src) is None and _probe_wav_ok(src) is False:
                    return None, "WAV 文件损坏或不是 PCM 格式"
            else:
                with open(src, "rb") as f:
                    head = f.read(10)
                if not (head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)):
                    return None, "MP3 文件损坏"
            if name is None or not str(name).strip():
                name = os.path.splitext(os.path.basename(src))[0]
            name = str(name).strip()[:40] or "未命名"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建音频目录：%s" % e
            fid = _new_id()
            dst = os.path.join(self._dir, fid + ext)
            try:
                shutil.copyfile(src, dst)
            except Exception:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)  # 半截文件清理，不留孤儿
                except Exception:
                    pass
                return None, "复制文件失败"
            duration = _wav_duration(dst) if ext == ".wav" else None
            frag = {
                "id": fid,
                "name": name,
                "file": fid + ext,
                "ext": ext,
                "added": time.strftime("%Y-%m-%d"),
                "duration": duration,
            }
            self._data["fragments"].append(frag)
            err = self._save()
            if err:
                try:
                    os.remove(dst)
                except Exception:
                    pass
                self._data["fragments"].pop()
                return None, err
            return frag, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def delete(self, fid):
        """删除片段（文件 + 索引项）；被音效组槽位引用的槽位同步置 ""（静音）。"""
        f = self._get(fid)
        if f is None:
            return False, "音频片段不存在"
        try:
            p = f.get("file") or ""
            if not os.path.isabs(p):
                p = os.path.join(self._dir, p)
            if os.path.exists(p):
                os.remove(p)
        except Exception as e:
            return False, "删除文件失败：%s" % e
        self._data["fragments"] = [x for x in self._data["fragments"] if x["id"] != fid]
        for k, v in self._data["group"]["custom"].items():
            if v == fid:
                self._data["group"]["custom"][k] = ""
        err = self._save()
        if err:
            return False, err
        return True, ""

    def rename(self, fid, new_name):
        """重命名片段；空名字返回错误。返回 (bool, err)。"""
        f = self._get(fid)
        if f is None:
            return False, "音频片段不存在"
        name = str(new_name or "").strip()
        if not name:
            return False, "名字不能为空"
        f["name"] = name[:40]
        err = self._save()
        if err:
            return False, err
        return True, ""

    def group_slots(self):
        """音效组槽位原始值：{"custom": {kind: fid|""|None}}（副本，改它不影响内部）。"""
        return {"custom": dict(self._data["group"].get("custom", {}))}

    def set_slot(self, kind, fid):
        """设置槽位：fid=片段 id；""=静音；None=恢复默认。kind 非法返回 False。

        事件播放走 winsound 仅支持 wav：非 wav 片段拒绝入槽位（可试听但不可绑定）。
        """
        if kind not in SLOT_KINDS:
            return False
        if fid is None:
            val = None
        elif fid == "":
            val = ""
        else:
            fid = str(fid)
            f = self._get(fid)
            if f is None:
                return False
            if str(f.get("ext", "")).lower() != ".wav":
                return False  # 槽位仅支持 wav
            val = fid
        self._data["group"]["custom"][kind] = val
        return self._save() is None

    def group_paths(self):
        """解析槽位为可播放路径：{"press": path|""|None, ...}。

        None = 未设置（走内置默认音效）；"" = 静音；path = 片段绝对路径
        （文件缺失返回 None，等价于走默认）。
        """
        out = {}
        slots = self._data["group"].get("custom", {})
        for k in SLOT_KINDS:
            v = slots.get(k)
            if v is None or v == "":
                out[k] = v
            else:
                out[k] = self.fragment_path(v)
        return out


# ---------------- 冒烟测试（无 GUI，可直接运行本文件） ----------------
if __name__ == "__main__":
    import tempfile

    tmp = tempfile.mkdtemp(prefix="pet_resources_smoke_")

    print("=== 冒烟 1：RoleLibrary 导入 / 切换 / 删除 ===")
    rl = RoleLibrary(tmp)
    assert rl.active_id() == "" and rl.active_path() is None and rl.list_roles() == []
    import base64
    fake = os.path.join(tmp, "测试角色.png")
    with open(fake, "wb") as f:
        # 1x1 透明 PNG（D1 起 import 校验 PNG 头/IHDR 尺寸）
        f.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
    role, err = rl.import_file(fake)
    assert err is None and role is not None, err
    assert rl.list_roles()[0]["id"] and rl.list_roles()[0]["name"] == "测试角色"
    assert rl.get(role["id"]) is not None and rl.get("不存在") is None
    assert rl.set_active(role["id"]) is True
    p = rl.active_path()
    assert p and os.path.isfile(p) and p.lower().endswith(".png")
    assert rl.path_for(role["id"]) == p
    assert rl.set_active("不存在的id") is False
    assert rl.set_active("") is True and rl.active_path() is None
    big = os.path.join(tmp, "big.png")
    with open(big, "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * (10 * 1024 * 1024 + 1))
    r2, e2 = rl.import_file(big)
    assert r2 is None and e2
    txt = os.path.join(tmp, "note.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("hi")
    r3, e3 = rl.import_file(txt)
    assert r3 is None and e3
    assert rl.delete(role["id"]) == (True, "")
    assert rl.get(role["id"]) is None and rl.list_roles() == []
    assert rl.delete(role["id"]) == (False, "角色不存在")
    # 删除 active 角色应重置为默认
    role2, _ = rl.import_file(fake, "第二个")
    rl.set_active(role2["id"])
    rl.delete(role2["id"])
    assert rl.active_id() == ""

    print("=== 冒烟 2：AudioLibrary 导入 / 重命名 / 槽位 ===")
    al = AudioLibrary(tmp)
    assert al.fragments() == [] and al.group_slots()["custom"]["press"] is None
    wav = os.path.join(tmp, "clip.wav")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 100)  # 有效 PCM wav（D2 起 import 校验音频头）
    frag, err = al.import_file(wav)
    assert err is None and frag is not None, err
    assert frag["ext"] == ".wav" and isinstance(frag["duration"], float)
    assert os.path.isfile(al.fragment_path(frag["id"]))
    assert al.rename(frag["id"], "  新名字 ") == (True, "")
    assert al.fragments()[0]["name"] == "新名字"
    assert al.rename("不存在", "x") == (False, "音频片段不存在")
    assert al.set_slot("press", frag["id"]) is True
    assert al.set_slot("release", "") is True
    assert al.set_slot("feed", None) is True
    assert al.set_slot("bogus", frag["id"]) is False
    assert al.set_slot("coin", "不存在的片段") is False
    gp = al.group_paths()
    assert gp["press"] and os.path.isfile(gp["press"])
    assert gp["release"] == "" and gp["feed"] is None and gp["reply"] is None
    assert al.delete(frag["id"]) == (True, "")
    assert al.group_slots()["custom"]["press"] == ""  # 被引用的槽位同步置 ""
    assert al.group_paths()["press"] == ""
    assert al.delete(frag["id"]) == (False, "音频片段不存在")
    mp3 = os.path.join(tmp, "t.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3" + b"\x00" * 50)
    f2, e2 = al.import_file(mp3, "歌")
    assert e2 is None and f2["ext"] == ".mp3" and f2["duration"] is None
    bigm = os.path.join(tmp, "big.mp3")
    with open(bigm, "wb") as f:
        f.write(b"\x00" * (20 * 1024 * 1024 + 1))
    fb, eb = al.import_file(bigm)
    assert fb is None and eb
    r4, e4 = al.import_file(os.path.join(tmp, "不存在.wav"), None)  # 不存在 → 文件不存在
    assert r4 is None and e4 == "文件不存在"

    print("=== 冒烟 3：持久化重载 ===")
    rl2 = RoleLibrary(tmp)
    al2 = AudioLibrary(tmp)
    assert rl2.active_id() == ""
    assert [f["ext"] for f in al2.fragments()] == [".mp3"]
    assert al2.group_slots()["custom"]["press"] == ""

    shutil.rmtree(tmp, ignore_errors=True)
    print("RESOURCES SMOKE OK")
