# -*- coding: utf-8 -*-
"""v1.3 无头冒烟验证（QT_QPA_PLATFORM=offscreen，无人工交互）。

覆盖：角色导入/切换、音效组、记账账本、气泡样式、自定义台词、
新菜单构建、6 个对话框、托盘/退出路径。运行时数据全部落到临时目录，
不污染真实 DATA_DIR；退出时清理。用法：python _verify_v13.py
"""
import os
import sys
import shutil
import tempfile
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")  # 中文 Windows 默认 GBK：print 带 ¥ 会崩
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# env 变量对 stdio 无效（启动时已定死编码）：直接 reconfigure
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
CHECKS = []


def check(name, cond, extra=""):
    CHECKS.append((name, bool(cond)))
    if not cond:
        FAILS.append("%s %s" % (name, extra))
    print("%s %s" % ("PASS" if cond else "FAIL", name), extra)


# ---------------- 隔离运行时数据 ----------------
_tmp = tempfile.mkdtemp(prefix="dfy_v13_")
import pet_dialogs  # noqa: E402
import 桌宠 as main  # noqa: E402
main.DATA_DIR = _tmp
main.CONFIG_PATH = os.path.join(_tmp, "config.json")
main.USAGE_PATH = os.path.join(_tmp, "usage.json")


def make_test_png(path, w=256, h=256):
    """生成一张带透明底的测试 PNG（供角色导入用）。"""
    from PySide6.QtGui import QImage, QPainter, QColor
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setBrush(QColor("#ff5b7a"))
    p.drawEllipse(40, 40, w - 80, h - 80)
    p.end()
    ok = img.save(path, "PNG")
    return ok


def make_opaque_png(path, w=256, h=256):
    """生成一张真·不透明图（RGB32 无 alpha 通道，浅灰底 + 彩色圆），供自动去背景测试。"""
    from PySide6.QtGui import QImage, QPainter, QColor
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#f5f5f5"))
    p = QPainter(img)
    p.setPen(QColor("#333333"))
    p.setBrush(QColor("#ff5b7a"))
    p.drawEllipse(w // 4, h // 4, w // 2, h // 2)
    p.end()
    img.save(path, "PNG")


def make_test_wav(path):
    """生成 0.2s 静音 WAV（供音频导入用）。"""
    import struct
    import wave
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 4410)


def main_flow():
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyleSheet(main.MENU_QSS)

    pet = main.PetWindow()

    # ---- 1. 启动基础状态 ----
    check("startup cfg role default", pet.cfg.get("role") == "")
    check("book created", pet.book is not None)
    check("lines_pools built", set(pet.lines_pools) == {"sajiao", "greedy", "happy", "idle"})
    check("bubble style default", main.BUBBLE_STYLE.get("font_size") == 10)

    # ---- 2. 角色导入 + 切换（v1.3.1：单/双形态 + 素材自动处理） ----
    png = os.path.join(_tmp, "role_test.png")
    make_test_png(png)
    role, err = pet.role_lib.import_file(png, "测试角色")
    check("role import (legacy)", role is not None and err is None, "err=%r" % (err,))
    if role:
        pet.apply_role(role["id"])
        check("role active id", pet.role_lib.active_id() == role["id"])
        check("custom role sprites", pet._custom_role and not pet.has_frames)
        check("window size > 0", pet.width() > 20 and pet.height() > 20)
        # 旧版导入无吃饱变体：单形态（仅 f0 一个形态）
        check("legacy role single form", pet.form_keys == ["f0"] and len(pet.sprites) == 1)
        pet.apply_role("")  # 恢复默认
        check("role restore default", not pet._custom_role and pet.has_frames)

    # 素材自动处理：不透明图 → 去背景 + 裁剪 + 缩放
    from PySide6.QtGui import QImage
    opaque = os.path.join(_tmp, "opaque.png")
    make_opaque_png(opaque, 800, 600)
    out1 = os.path.join(_tmp, "proc_base.png")
    okp, notesp = pet_dialogs._prepare_role_png(opaque, out1)
    check("auto-process opaque", okp and os.path.isfile(out1), "err=%r" % (notesp,))
    check("bg removal actually ran", okp and "已自动去背景" in notesp, "notes=%r" % (notesp,))
    if okp:
        img1 = QImage(out1)
        check("processed has alpha", img1.hasAlphaChannel())
        check("processed trimmed+scaled", max(img1.width(), img1.height()) <= 512
              and img1.width() < 800)
    # 已有透明通道的图：去背景不误伤
    png2 = os.path.join(_tmp, "role_test2.png")
    make_test_png(png2)
    out2 = os.path.join(_tmp, "proc_alpha.png")
    okp2, notesp2 = pet_dialogs._prepare_role_png(png2, out2)
    check("auto-process alpha png", okp2, "err=%r" % (notesp2,))

    # 双形态导入：常态+吃饱两张 → 吃饱形态切到第二张图
    full_src = os.path.join(_tmp, "full_src.png")
    make_test_png(full_src, 512, 512)
    out_full = os.path.join(_tmp, "proc_full.png")
    okf, notesf = pet_dialogs._prepare_role_png(full_src, out_full)
    dual, errd = pet.role_lib.import_processed(out1, out_full, "双形态测试")
    check("import dual", dual is not None and errd is None, "err=%r" % (errd,))
    if dual:
        check("dual form recorded", dual.get("form") == "dual"
              and bool(pet.role_lib.path_for_full(dual["id"])))
        # 重启重载回归：重建 RoleLibrary（模拟再次启动）后双形态关联不丢
        lib2 = main.pet_resources.RoleLibrary(_tmp)
        check("role reload keeps file_full", lib2.path_for_full(dual["id"]) is not None
              and lib2.get(dual["id"]).get("form") == "dual")
        pet.apply_role(dual["id"])
        check("dual sprites differ",
              pet.sprites["f1"]["side"].cacheKey() != pet.sprites["f0"]["side"].cacheKey())
        check("dual state full built", pet.state_pix["f1"].get("blush") is not None
              and pet.state_pix["f0"].get("blush") is not None)
        # 中-3：状态展示中切形态 → 立即换新形态同表情；结束后落第二形态
        pet._show_state("angry", 1000)
        pet._set_form("f1")
        check("dual state switch form",
              pet.item.pixmap().cacheKey() == pet.state_pix["f1"]["angry"].cacheKey())
        pet._state_timer.stop()
        pet._state_done()
        check("dual state done falls f1 side",
              pet.item.pixmap().cacheKey() == pet.sprites["f1"]["side"].cacheKey())
        pet._set_form("f0")
        pet._set_form("f1")
        check("dual form shows full pix",
              pet.item.pixmap().cacheKey() == pet.sprites["f1"]["side"].cacheKey())
        pet._set_form("f0")
        # H1 回归：喂食路径（squash 动画收尾）也必须落到吃饱图
        pet.apply_role(dual["id"])
        pet.feed("小鱼干")
        t0 = time.time()
        while pet.busy and time.time() - t0 < 3:
            app.processEvents()
            time.sleep(0.02)
        check("feed shows f1 pix (dual)", pet.form == "f1"
              and pet.item.pixmap().cacheKey() == pet.sprites["f1"]["side"].cacheKey())
        pet._set_form("f0")
        # M4b：双形态删除——两张素材文件都删 + active 重置
        bpath = pet.role_lib.path_for(dual["id"])
        fpath = pet.role_lib.path_for_full(dual["id"])
        okd, errd2 = pet.role_lib.delete(dual["id"])
        check("dual delete both files", okd and not os.path.exists(bpath)
              and not os.path.exists(fpath)
              and pet.role_lib.get(dual["id"]) is None
              and pet.role_lib.active_id() == "")
        pet.apply_role("")
    # 单形态导入：只有一张图 → 两形态同图
    single, errs = pet.role_lib.import_processed(out2, None, "单形态测试")
    check("import single", single is not None and errs is None, "err=%r" % (errs,))
    if single:
        check("single form recorded", single.get("form") == "single"
              and pet.role_lib.path_for_full(single["id"]) is None)
        pet.apply_role(single["id"])
        check("single sprites equal", pet.form_keys == ["f0"] and len(pet.sprites) == 1)
        # v1.3.3：自定义角色程序化表情图（不再只有气泡+头顶表情）
        st = pet._state_pix("blush")
        check("custom state pix built", st is not None and st.width() > 0)
        if st is not None:
            pet._show_state("blush", 200)
            check("custom state shown",
                  pet.item.pixmap().cacheKey() == st.cacheKey()
                  and pet.item.pixmap().cacheKey() != pet.sprites["f0"]["side"].cacheKey())
            pet._state_timer.stop()
            pet._state_done()  # S1 回归：表情结束必须恢复待机贴图
            check("custom state restored",
                  pet.item.pixmap().cacheKey() == pet.sprites["f0"]["front"].cacheKey())
            # 睡眠/唤醒恢复（S1 同源回归）
            pet._show_sleep()
            pet._wake()
            check("custom sleep restored",
                  pet.item.pixmap().cacheKey() == pet.sprites["f0"]["front"].cacheKey())
        pet.apply_role("")

    # ---- 2c. 多帧素材 / 视频抽帧（v1.3.2）----
    frame_pngs = []
    for i in range(3):
        fp_src = os.path.join(_tmp, "fr%d.png" % i)
        make_test_png(fp_src, 128 + i * 8, 128 + i * 8)
        fp_out = os.path.join(_tmp, "fr%d_proc.png" % i)
        okfp, _n = pet_dialogs._prepare_role_png(fp_src, fp_out)
        check("frame prep %d" % i, okfp)
        frame_pngs.append(fp_out)
    frole, errf = pet.role_lib.import_processed(frame_pngs[0], None, "帧动画测试", frames_src=frame_pngs)
    check("import frames", frole is not None and errf is None, "err=%r" % (errf,))
    if frole:
        check("frames recorded", len(frole.get("frames", [])) == 3
              and len(pet.role_lib.frames_for(frole["id"])) == 3)
        lib3 = main.pet_resources.RoleLibrary(_tmp)
        check("reload keeps frames", len(lib3.frames_for(frole["id"])) == 3)
        pet.apply_role(frole["id"])
        check("frames role animates", pet._custom_role and pet.has_frames
              and pet.anim._sets.get("idle") is not None
              and len(pet.anim._sets["idle"]) == 3)
        # 中-4：帧动画角色 × 程序化表情组合（状态结束/唤醒后恢复帧循环）
        pet._show_state("cry", 100)
        check("frames role state shown", pet.anim_mode == "state"
              and pet.item.pixmap().cacheKey() == pet.state_pix["f0"]["cry"].cacheKey())
        pet._state_timer.stop()
        pet._state_done()
        check("frames role idle restored", pet.anim_mode == "idle" and pet.anim._timer.isActive())
        pet._show_sleep()
        pet._wake()
        check("frames role sleep restored", pet.anim_mode == "idle" and pet.anim._timer.isActive())
        pet.feed("小鱼干")
        t0 = time.time()
        while pet.busy and time.time() - t0 < 3:
            app.processEvents()
            time.sleep(0.02)
        check("frames feed ok", pet.form == "f0")  # 单形态帧角色：喂食循环回 f0
        pet._set_form("f0")
        fpaths = list(pet.role_lib.frames_for(frole["id"]))
        okfd, _errfd = pet.role_lib.delete(frole["id"])
        check("frames delete files", okfd and all(not os.path.exists(p) for p in fpaths))
        pet.apply_role("")
        # 高-2 回归：文件存在但无法解码 → 回退默认角色（不能静默消失）
        corrupt = os.path.join(_tmp, "roles", "corrupt.png")
        os.makedirs(os.path.dirname(corrupt), exist_ok=True)
        with open(corrupt, "wb") as fh:
            fh.write(b"not a png at all")
        # 直接塞索引（绕过 import_file 的内容校验）
        pet.role_lib._data["roles"].append({
            "id": "corrupt1", "name": "坏角色", "file": "corrupt.png",
            "form": "single", "file_full": "", "frames": [], "added": "",
        })
        pet.role_lib._save()
        pet.role_lib.set_active("corrupt1")
        pet.cfg["role"] = "corrupt1"
        pet.apply_role("corrupt1")
        check("corrupt role falls back default", not pet._custom_role
              and pet.sprites["normal"]["side"].width() > 20)
        pet.apply_role("")
        pet.role_lib.delete("corrupt1")
        # 中-1 回归：旧版超大角色加载时一次性补偿 scale（窗口不骤缩）
        big_src = os.path.join(_tmp, "big_role.png")
        make_test_png(big_src, 800, 800)
        bigrole, _errb = pet.role_lib.import_file(big_src, "超大旧角色")  # 旧版入口：不处理直接拷贝
        if bigrole:
            pet.cfg["scale"] = 1.0
            pet.cfg["scale_compensated_role"] = ""
            pet.apply_role(bigrole["id"])
            check("big role capped", pet.sprites["f0"]["side"].width() <= 512)
            check("big role scale compensated", pet.cfg.get("scale", 1.0) > 1.0,
                  "scale=%.2f" % pet.cfg.get("scale", 1.0))
            # 二次切换不重复补偿
            s_before = pet.cfg.get("scale", 1.0)
            pet.apply_role("")
            pet.apply_role(bigrole["id"])
            check("big role no re-compensate", abs(pet.cfg.get("scale", 1.0) - s_before) < 0.01)
            pet.apply_role("")
            pet.role_lib.delete(bigrole["id"])
        # 帧数边界：1 帧 / 25 帧拒绝
        rmin, emin = pet.role_lib.import_processed(frame_pngs[0], None, "边界", frames_src=[frame_pngs[0]])
        check("frames min2 rejected", rmin is None and "至少需要 2 帧" in (emin or ""), "err=%r" % (emin,))
        rmax, emax = pet.role_lib.import_processed(frame_pngs[0], None, "边界2", frames_src=[frame_pngs[0]] * 25)
        check("frames max24 rejected", rmax is None and "最多 24 帧" in (emax or ""), "err=%r" % (emax,))
    # 抽帧错误路径：单帧 GIF / 假视频
    from PySide6.QtGui import QImageWriter
    gif1 = os.path.join(_tmp, "one.gif")
    img1 = QImage(64, 64, QImage.Format.Format_ARGB32)
    img1.fill(0)
    w = QImageWriter(gif1, b"gif")
    w.write(img1)
    rawdir = tempfile.mkdtemp(prefix="role_raw_")
    raws, errg = pet_dialogs._extract_video_frames(gif1, rawdir)
    # offscreen 下 QImageWriter 写的 GIF 可能被 QMovie 判为无效：只断言拒绝路径
    check("gif rejected", raws is None and bool(errg), "err=%r" % (errg,))
    fake = os.path.join(_tmp, "fake.mp4")
    with open(fake, "wb") as fh:
        fh.write(b"not a video")
    raws2, errv = pet_dialogs._extract_video_frames(fake, rawdir)
    check("fake video rejected", raws2 is None, "err=%r" % (errv,))
    shutil.rmtree(rawdir, ignore_errors=True)
    # 正向抽帧（真实素材；S1 回归）：视频与多帧 GIF 都要能抽出 ≥2 帧
    vid = os.path.join(HERE, "_verify_assets", "sample.mp4")
    gif3 = os.path.join(HERE, "_verify_assets", "sample.gif")
    if os.path.isfile(vid):
        rd2 = tempfile.mkdtemp(prefix="role_raw2_")
        raws3, errv2 = pet_dialogs._extract_video_frames(vid, rd2)
        check("video extract positive", raws3 is not None and len(raws3) >= 2
              and all(os.path.isfile(p) for p in raws3),
              "n=%s err=%r" % (len(raws3) if raws3 else 0, errv2))
        shutil.rmtree(rd2, ignore_errors=True)
    else:
        check("video extract positive", False, "missing _verify_assets/sample.mp4")
    if os.path.isfile(gif3):
        rd3 = tempfile.mkdtemp(prefix="role_raw3_")
        raws4, errg2 = pet_dialogs._extract_video_frames(gif3, rd3)
        check("gif extract positive", raws4 is not None and len(raws4) >= 2
              and all(os.path.isfile(p) for p in raws4),
              "n=%s err=%r" % (len(raws4) if raws4 else 0, errg2))
        shutil.rmtree(rd3, ignore_errors=True)
    else:
        check("gif extract positive", False, "missing _verify_assets/sample.gif")
    # 统一画布：同源帧（平移保留）与多图帧（居中画布）输出尺寸一致
    if os.path.isfile(vid):
        rd4 = tempfile.mkdtemp(prefix="role_prep4_")
        raws5, _e = pet_dialogs._extract_video_frames(vid, rd4)
        if raws5:
            outs, notesu = pet_dialogs._prepare_role_frames(raws5, rd4, same_size=True)
            check("union canvas uniform", outs is not None and len(outs) == len(raws5),
                  "notes=%r" % (notesu,))
            if outs:
                from PySide6.QtGui import QImage as _QI
                dims = {( _QI(p).width(), _QI(p).height()) for p in outs}
                check("union canvas same dims", len(dims) == 1, "dims=%r" % (dims,))
        shutil.rmtree(rd4, ignore_errors=True)
        # 向导接线（高-1 回归）：_pick_video → frames_video=True → _do_import 传 same_size=True
        from PySide6.QtWidgets import QFileDialog
        real_gofn = QFileDialog.getOpenFileName
        real_prep = pet_dialogs._prepare_role_frames
        real_warn = pet_dialogs._warn
        calls = []
        def _rec(srcs, out_dir, same_size=True):
            calls.append(bool(same_size))
            return real_prep(srcs, out_dir, same_size)
        pet_dialogs._prepare_role_frames = _rec
        pet_dialogs._warn = lambda *a, **k: None
        QFileDialog.getOpenFileName = lambda *a, **k: (vid, "")
        try:
            wdlg = pet_dialogs.RoleImportDialog(pet)
            wdlg._pick_video()
            check("wizard video flag", wdlg._frames_video is True)
            wdlg._do_import()
            dataw = wdlg.result_data()
            check("wizard union path", bool(calls) and calls[-1] is True, "calls=%r" % (calls,))
            check("wizard frames result", dataw is not None and len(dataw.get("frames", [])) >= 2)
            wdlg.close()
        except Exception as e:
            check("wizard video flow", False, repr(e))
        finally:
            QFileDialog.getOpenFileName = real_gofn
            pet_dialogs._prepare_role_frames = real_prep
            pet_dialogs._warn = real_warn
    # 多图路径：不同尺寸两帧 → 输出同尺寸（居中画布）
    rd6 = tempfile.mkdtemp(prefix="role_prep6_")
    outs_m, notes_m = pet_dialogs._prepare_role_frames([out1, out2], rd6, same_size=False)
    check("multi canvas uniform", outs_m is not None and len(outs_m) == 2, "err=%r" % (notes_m,))
    if outs_m:
        from PySide6.QtGui import QImage as _QI2
        dims_m = {(_QI2(p).width(), _QI2(p).height()) for p in outs_m}
        check("multi canvas same dims", len(dims_m) == 1, "dims=%r" % (dims_m,))
    shutil.rmtree(rd6, ignore_errors=True)

    # ---- 2d. v1.4 多形态 + 开机自启 ----
    f3 = []
    for i in range(3):
        src3 = os.path.join(_tmp, "form%d_src.png" % i)
        make_test_png(src3, 150, 150)
        outp = os.path.join(_tmp, "form%d_out.png" % i)
        pet_dialogs._prepare_role_png(src3, outp)
        f3.append(("幼体" if i == 0 else ("成体" if i == 1 else "究极体"), outp))
    r3, e3 = pet.role_lib.import_processed(f3[0][1], None, "三形态", forms_src=f3)
    check("import 3 forms", r3 is not None and e3 is None, "err=%r" % (e3,))
    if r3:
        check("3 forms recorded", len(r3.get("forms", [])) == 3)
        pet.apply_role(r3["id"])
        check("3 form keys", pet.form_keys == ["f0", "f1", "f2"])
        for expect in ("f1", "f2", "f0"):
            pet.feed("小鱼干")
            t0 = time.time()
            while pet.busy and time.time() - t0 < 3:
                app.processEvents()
                time.sleep(0.02)
            check("feed cycle -> %s" % expect, pet.form == expect)
            # bug 审查回归：贴图必须同步切到目标形态（变量断言不够）
            check("feed pix -> %s" % expect,
                  pet.item.pixmap().cacheKey() == pet.sprites[expect]["side"].cacheKey())
        # 菜单 f1→f2 切换贴图断言
        pet._set_form("f1")
        pet._set_form("f2")
        check("menu form switch pix",
              pet.item.pixmap().cacheKey() == pet.sprites["f2"]["side"].cacheKey())
        # 消化回第一形态
        pet._set_form("f2")
        pet._digest()
        check("digest back to f0", pet.form == "f0")
        # 删除无孤儿：全部形态文件清理
        _form_files = [os.path.join(_tmp, "roles", m["file"]) for m in pet.role_lib.form_metas(r3["id"])]
        pet.role_lib.delete(r3["id"])
        check("3-form delete no orphans", all(not os.path.exists(p) for p in _form_files))
        pet.apply_role("")
    # bug 审查回归：形态文件缺失时启动不崩（file_full 孤儿场景）
    two = []
    for i in range(2):
        ts = os.path.join(_tmp, "t%d.png" % i)
        make_test_png(ts, 120, 120)
        to = os.path.join(_tmp, "t%d_o.png" % i)
        pet_dialogs._prepare_role_png(ts, to)
        two.append(("形态%d" % (i + 1), to))
    rt, et = pet.role_lib.import_processed(two[0][1], None, "缺文件测试", forms_src=two)
    if rt:
        f1_path = os.path.join(_tmp, "roles", pet.role_lib.form_metas(rt["id"])[1]["file"])
        os.remove(f1_path)  # 模拟 file_full 孤儿
        pet.apply_role(rt["id"])
        check("missing form no crash", pet.form_keys == ["f0", "f1"]
              and set(pet.sprites.keys()) == set(pet.form_keys))
        pet.apply_role("")
        pet.role_lib.delete(rt["id"])
    # 自启失败回弹不递归（stub set_autostart 恒失败）
    class _FakeAct:
        def __init__(self):
            self.checked = False
            self.blocked = 0
        def setChecked(self, v):
            self.checked = v
        def blockSignals(self, b):
            self.blocked += 1
    _real_setauto = main.set_autostart
    _real_act = pet._autostart_act
    _bubbles2 = []
    _real_sb2 = pet.show_bubble
    pet.show_bubble = lambda t: _bubbles2.append(t)
    main.set_autostart = lambda on: (False, "模拟失败")
    pet._autostart_act = _FakeAct()
    pet._autostart_busy = False
    try:
        pet._set_autostart(True)
        check("autostart fail no recursion", pet._autostart_act.checked is False
              and any("失败" in b for b in _bubbles2))
    finally:
        main.set_autostart = _real_setauto
        pet._autostart_act = _real_act
        pet.show_bubble = _real_sb2

    # 开机自启：保存原状 → 往返测试 → 恢复（不动用户真实设置）
    _was_auto = main.is_autostart_enabled()
    try:
        main.set_autostart(False)
        check("autostart default off", main.is_autostart_enabled() is False)
        ok_a, err_a = main.set_autostart(True)
        check("autostart set on", ok_a and main.is_autostart_enabled(), "err=%r" % (err_a,))
        ok_b, _err_b = main.set_autostart(False)
        check("autostart set off", ok_b and not main.is_autostart_enabled())
    finally:
        main.set_autostart(_was_auto)  # 恢复开发者本机原状

    # ---- 3. 音效导入 + 音效组 ----
    wav = os.path.join(_tmp, "tone.wav")
    make_test_wav(wav)
    frag, err2 = pet.audio_lib.import_file(wav, "测试音")
    check("audio import", frag is not None and err2 is None, "err=%r" % (err2,))
    if frag:
        pet.audio_lib.set_slot("press", frag["id"])
        pet.audio_lib.set_slot("coin", "")  # 静音槽
        paths = pet.audio_lib.group_paths()
        check("group paths press", isinstance(paths.get("press"), str) and os.path.isfile(paths["press"]))
        check("group paths coin silent", paths.get("coin") == "")
        # M4：面板改槽位 → apply_sound_group 实时同步进 pet_audio + 自动切自定义组
        pet.apply_sound_group(None, as_custom=True)
        check("sound group auto custom", pet.cfg.get("sound_group") == "custom")
        cg = getattr(main.pet_audio, "_custom_group", None) or {}
        check("pet_audio custom synced", cg.get("press") == paths.get("press") and cg.get("coin") == "")
        pet._set_sound_group("custom")
        check("sound group custom cfg", pet.cfg.get("sound_group") == "custom")
        pet._set_sound_group("default")
        check("sound group default cfg", pet.cfg.get("sound_group") == "default")

    # ---- 4. 记账账本 ----
    book = pet.book
    book.add_manual(12.5, "午饭")
    check("manual today usage", abs(book.today_usage() - 12.5) < 0.001)
    book.observe_balance(100.0)
    book.observe_balance(97.3)
    check("balance diff usage", abs(book.today_usage() - 15.2) < 0.001)
    # 预算口径仅 API 消费（2.7）：设 2.0 触发
    pet.cfg["budget"] = 2.0
    pet.cfg["balance_alert"] = 0.0
    msgs = book.check_alerts(97.3, pet.cfg["budget"], pet.cfg["balance_alert"])
    check("budget alert fires", len(msgs) >= 1, "msgs=%r" % (msgs,))
    msgs2 = book.check_alerts(97.3, pet.cfg["budget"], pet.cfg["balance_alert"])
    check("budget alert once/day", len(msgs2) == 0)
    pet.cfg["budget"] = 0.0
    pet.cfg["balance_alert"] = 98.0
    msgs3 = book.check_alerts(97.3, 0.0, 98.0)
    check("balance alert fires", len(msgs3) >= 1)
    csv_path = os.path.join(_tmp, "ledger.csv")
    ok_csv, err_csv = book.export_csv(csv_path)
    check("csv export", ok_csv and os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0)
    recs = book.search_records("午饭")
    check("search records", len(recs) >= 1)
    pet.on_ledger_changed()
    check("ledger changed usage", abs(pet._usage - book.today_usage()) < 0.001)

    # ---- 5. 气泡样式 + 自定义台词 ----
    pet.apply_bubble_style({"bg": "#ffe9c8", "fg": "#7a4a21", "border": "#b07030", "font_size": 12, "radius": 20})
    check("bubble style applied", main.BUBBLE_STYLE.get("bg") == "#ffe9c8" and main.BUBBLE_STYLE.get("font_size") == 12)
    pet.apply_bubble_style({"bg": "#ffffff", "fg": "#203170", "border": "#203170", "font_size": 10, "radius": 16})
    pet.save_lines("sajiao", ["这是自定义台词一", "这是自定义台词二"])
    check("lines saved", len(pet.lines_pools["sajiao"]) == len(main.LINES_SAJIAO) + 2)
    # M4 / H1 回归：台词对话框必须能预填已保存的自定义台词（lines_extra 键）
    try:
        ldlg = pet_dialogs.LinesDialog(pet)
        prefill = ldlg._edits["sajiao"].toPlainText()
        check("lines dialog prefill", "这是自定义台词一" in prefill and "这是自定义台词二" in prefill,
              "prefill=%r" % (prefill[:60],))
        ldlg.close()
    except Exception as e:
        check("lines dialog prefill", False, repr(e))

    # ---- 6. 菜单构建（stub exec，断言分区与动作数量）----
    class _Menu(main.QMenu):
        def exec(self, *_a, **_k):
            self._captured = self.actions()
            return None

    real_menu_cls = main.QMenu
    main.QMenu = _Menu
    captured = {}
    try:
        pet._open_menu(QPoint(100, 100))
        # deleteLater 后菜单仍在 Python 引用内；从最近构建的 _Menu 拿 actions
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, _Menu) and getattr(obj, "_captured", None) is not None:
                captured = obj
                break
    except Exception as e:
        check("menu build", False, repr(e))
    finally:
        main.QMenu = real_menu_cls
    if captured:
        def _all_texts(acts):
            out = []
            for a in acts:
                if a.text():
                    out.append(a.text())
                m2 = a.menu()
                if m2 is not None:
                    out.extend(_all_texts(m2.actions()))
            return out
        texts = _all_texts(captured._captured)
        top = [a.text() for a in captured._captured if a.text()]
        check("menu compact top-level", len(top) <= 18, "top=%d" % len(top))
        check("menu all items", len(texts) >= 35, "count=%d" % len(texts))
        check("menu ledger item", any("账本" in t for t in texts))
        check("menu resource item", any("资源管理" in t for t in texts))
        check("menu role item", any("角色" in t for t in texts))
        check("menu has size slider", any(isinstance(a, main.QWidgetAction) for a in captured._captured))
        check("menu city item", any("天气城市" in t for t in texts))
        # 中-2：_set_city 对话框全路径（stub QInputDialog）
        real_qid = main.QInputDialog
        fake = {"result": main.QDialog.DialogCode.Accepted, "val": ""}
        class _FakeInput:
            def __init__(self, parent=None):
                pass
            def setWindowTitle(self, t): pass
            def setLabelText(self, t): pass
            def setTextValue(self, t): self._val = t
            def setWindowFlags(self, f): pass
            def windowFlags(self): return 0
            def show(self): pass
            def raise_(self): pass
            def activateWindow(self): pass
            def setFocus(self): pass
            def exec(self): return fake["result"]
            def textValue(self): return fake["val"]
        main.QInputDialog = _FakeInput
        bubbles = []
        real_show_bubble = pet.show_bubble
        pet.show_bubble = lambda t: bubbles.append(t)
        try:
            pet.cfg["city"] = "北京"
            fake["result"] = main.QDialog.DialogCode.Accepted
            fake["val"] = "上海"
            pet._set_city()
            check("city dialog accept", pet.cfg["city"] == "上海"
                  and main.load_config().get("city") == "上海")
            fake["val"] = ""
            pet._set_city()
            check("city dialog empty", pet.cfg["city"] == "上海"
                  and any("不能为空" in b for b in bubbles))
            fake["result"] = main.QDialog.DialogCode.Rejected
            fake["val"] = "东京"
            pet._set_city()
            check("city dialog reject", pet.cfg["city"] == "上海")
        finally:
            main.QInputDialog = real_qid
            pet.show_bubble = real_show_bubble
        pet.cfg["city"] = "北京"
        main.save_config(pet.cfg)
    else:
        check("menu captured", False, "no menu object captured")

    # ---- 7. 对话框冒烟：构建 + show + close ----
    for name, mk in (
        ("ResourceManager", lambda: pet_dialogs.ResourceManagerDialog(pet, 0)),
        ("Ledger", lambda: pet_dialogs.LedgerDialog(pet)),
        ("BubbleStyle", lambda: pet_dialogs.BubbleStyleDialog(pet)),
        ("Lines", lambda: pet_dialogs.LinesDialog(pet)),
        ("AmountNote", lambda: pet_dialogs.AmountNoteDialog(pet)),
        ("RoleImport", lambda: pet_dialogs.RoleImportDialog(pet)),
    ):
        try:
            dlg = mk()
            dlg.show()
            app.processEvents()
            dlg.close()
            check("dialog %s" % name, True)
        except Exception as e:
            check("dialog %s" % name, False, repr(e))

    # ---- 7b. RoleImportDialog 拒绝路径（stub _warn 防弹窗阻塞）----
    _real_warn = pet_dialogs._warn
    pet_dialogs._warn = lambda *a, **k: None
    try:
        ridlg = pet_dialogs.RoleImportDialog(pet)
        ridlg._do_import()  # 形态 0 无图 → 提示并拒绝
        check("import reject: no form img", ridlg.result_data() is None)
        ridlg._add_form("第二形态")
        ridlg._form_rows[0]["src"] = os.path.join(_tmp, "opaque.png")
        ridlg._form_views()
        ridlg._do_import()  # 形态 1 无图 → 提示并拒绝
        check("import reject: form2 missing", ridlg.result_data() is None)
        ridlg.close()
    except Exception as e:
        check("import reject paths", False, repr(e))
    finally:
        pet_dialogs._warn = _real_warn

    # ---- 8. 清理与退出 ----
    pet._quit()  # 内部调 QApplication.quit()
    shutil.rmtree(_tmp, ignore_errors=True)


def run_module_smokes():
    """逐个跑无 GUI 模块的冒烟测试（子进程，失败即 FAIL）。"""
    import subprocess
    py = sys.executable
    here = HERE
    for mod in ("pet_anim", "pet_mood", "pet_fx", "pet_resources", "pet_book", "pet_audio"):
        p = subprocess.run(
            [py, os.path.join(here, mod + ".py")],
            cwd=here, capture_output=True, timeout=120,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
        )
        stdout = (p.stdout or b"").decode("utf-8", errors="replace")
        stderr = (p.stderr or b"").decode("utf-8", errors="replace")
        tail = stdout[-300:]
        ok = p.returncode == 0 and "SMOKE OK" in stdout
        check("module smoke %s" % mod, ok, "rc=%d tail=%r err=%r" % (p.returncode, tail, stderr[-120:]))


if __name__ == "__main__":
    run_module_smokes()
    main_flow()
    print("=" * 40)
    print("TOTAL CHECKS: %d, FAILS: %d" % (len(CHECKS), len(FAILS)))
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("V13 VERIFY ALL OK")