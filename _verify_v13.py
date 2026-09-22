# -*- coding: utf-8 -*-
"""v1.3 无头冒烟验证（QT_QPA_PLATFORM=offscreen，无人工交互）。

覆盖：角色导入/切换、音效组、记账账本、气泡样式、自定义台词、
新菜单构建、5 个新对话框、托盘/退出路径。运行时数据全部落到临时目录，
不污染真实 DATA_DIR；退出时清理。用法：python _verify_v13.py
"""
import os
import sys
import json
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
    from PySide6.QtCore import QTimer, QPoint
    from PySide6.QtWidgets import QApplication, QDialog

    app = QApplication(sys.argv)
    app.setStyleSheet(main.MENU_QSS)

    pet = main.PetWindow()

    # ---- 1. 启动基础状态 ----
    check("startup cfg role default", pet.cfg.get("role") == "")
    check("book created", pet.book is not None)
    check("lines_pools built", set(pet.lines_pools) == {"sajiao", "greedy", "happy", "idle"})
    check("bubble style default", main.BUBBLE_STYLE.get("font_size") == 10)

    # ---- 2. 角色导入 + 切换 ----
    png = os.path.join(_tmp, "role_test.png")
    make_test_png(png)
    role, err = pet.role_lib.import_file(png, "测试角色")
    check("role import", role is not None and err is None, "err=%r" % (err,))
    if role:
        pet.apply_role(role["id"])
        check("role active id", pet.role_lib.active_id() == role["id"])
        check("custom role sprites", pet._custom_role and not pet.has_frames)
        check("window size > 0", pet.width() > 20 and pet.height() > 20)
        pet.apply_role("")  # 恢复默认
        check("role restore default", not pet._custom_role and pet.has_frames)

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
    pet.cfg["budget"] = 10.0
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
        texts = [a.text() for a in captured._captured if a.text()]
        check("menu has sections+items", len(texts) >= 25, "count=%d" % len(texts))
        check("menu ledger item", any("账本" in t for t in texts))
        check("menu resource item", any("资源管理" in t for t in texts))
        check("menu role item", any("角色" in t for t in texts))
    else:
        check("menu captured", False, "no menu object captured")

    # ---- 7. 对话框冒烟：构建 + show + close ----
    for name, mk in (
        ("ResourceManager", lambda: pet_dialogs.ResourceManagerDialog(pet, 0)),
        ("Ledger", lambda: pet_dialogs.LedgerDialog(pet)),
        ("BubbleStyle", lambda: pet_dialogs.BubbleStyleDialog(pet)),
        ("Lines", lambda: pet_dialogs.LinesDialog(pet)),
        ("AmountNote", lambda: pet_dialogs.AmountNoteDialog(pet)),
    ):
        try:
            dlg = mk()
            dlg.show()
            app.processEvents()
            dlg.close()
            check("dialog %s" % name, True)
        except Exception as e:
            check("dialog %s" % name, False, repr(e))

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