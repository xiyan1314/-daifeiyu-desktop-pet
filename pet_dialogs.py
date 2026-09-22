# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 全部 Qt 对话框 / 面板（v1.3.0 新增）。

职责：参考 dsh-whale-widget 的「角色管理 / 音频片段管理 / 音效组 / 记账账本」
面板设计，提供资源管理、记账账本、气泡样式、台词设置四个交互界面。

对外接口（全部在主线程使用；构造签名 parent 为桌宠主窗口）：
- DIALOG_QSS（常量）：统一深色圆角主题（#1e2234 底 / #2e3560 控件底 /
  #e8ecff 文字 / #ffd65a 强调 / 圆角 8px），覆盖 QDialog/QPushButton/
  QListWidget/QTableWidget/QComboBox/QTabWidget/QLineEdit/QPlainTextEdit/
  QSpinBox/QDoubleSpinBox/QLabel。
- modal(dlg)：加 WindowStaysOnTopHint + show/raise_/activateWindow/setFocus
  后 exec（应对 Windows 前台锁，参考主程序 _set_api_key）。
- class RolePanel(QWidget)：角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。
- class SoundPanel(QWidget)：音频片段列表（试听 / 导入 / 重命名 / 删除）+
  自定义音效组 5 行槽位（默认 / 静音 / 片段）。
- class ResourceManagerDialog(QDialog)：QTabWidget 两页签（角色 / 音效），
  内嵌上述两个面板；initial_tab=0/1。
- class LedgerDialog(QDialog)：今日 / 近 7 天 / 全部 三个页签 + 实时搜索 +
  记一笔（AmountNoteDialog）+ 导出 CSV。
- class AmountNoteDialog(QDialog)：金额 QDoubleSpinBox(0.01~99999) + 备注输入。
- class BubbleStyleDialog(QDialog)：背景 / 文字 / 描边三色 + 字号 8~18 +
  圆角 0~30 + 实时预览，保存回调 pet.apply_bubble_style。
- class LinesDialog(QDialog)：撒娇 / 贪吃 / 开心 / 闲逛 四页台词编辑
  （每行一条，最多 20 行、每行最长 60 字），保存回调 pet.save_lines。

与主程序的耦合方式（全部防御性 getattr，缺省不崩）：
- pet.cfg（配置 dict）、pet.role_lib、pet.audio_lib、pet.book（可能 None）
- pet.apply_role(role_id)：立即切换角色（主线实现）
- pet.preview_audio(path|fid)：试听（主线实现：pet_audio.preview_file，
  wav 用 winsound；mp3 用 QMediaPlayer；失败弹提示）
- pet.apply_sound_group(group)：保存音效组后同步进 pet_audio（主线实现）
- pet.apply_bubble_style(style)：应用气泡样式（主线实现）
- pet.save_lines(pool, lines)：保存自定义台词（主线实现）
- pet.on_ledger_changed()：刷新挂件今日已用（主线实现）
- pet.show_bubble(text)

实现要点：
- 不 import 桌宠.py（避免循环依赖）；顶层 import PySide6 没问题。
- 所有对话框统一 DIALOG_QSS 深色主题；文件导入前先做大小 / 尺寸 /
  透明通道校验（角色 PNG 必须可加载且 hasAlphaChannel）。
- 金额统一 "%.2f" 显示，表格金额列右对齐。

Python 3.8+ 兼容。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import os
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import pet_audio

# ---------------- 主题 ----------------
DIALOG_QSS = """
QDialog {
    background-color: #1e2234;
    color: #e8ecff;
    font-family: "Microsoft YaHei";
    font-size: 12px;
}
QWidget { color: #e8ecff; }
QLabel { color: #e8ecff; background: transparent; }
QPushButton {
    background-color: #2e3560;
    color: #e8ecff;
    border: 1px solid #3d477f;
    border-radius: 8px;
    padding: 5px 14px;
}
QPushButton:hover { background-color: #3d477f; }
QPushButton:pressed { background-color: #27304f; }
QPushButton:default {
    background-color: #ffd65a;
    color: #1e2234;
    border: 1px solid #ffd65a;
    font-weight: bold;
}
QPushButton:disabled { color: #6b7290; background-color: #262b40; border-color: #2e3560; }
QListWidget, QTableWidget, QComboBox, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2e3560;
    color: #e8ecff;
    border: 1px solid #3d477f;
    border-radius: 8px;
    padding: 4px 6px;
}
QListWidget::item, QTableWidget::item { padding: 4px; }
QListWidget::item:selected, QTableWidget::item:selected { background-color: #4a5590; color: #ffffff; }
QListWidget::item:hover { background-color: #3a4375; }
QComboBox QAbstractItemView {
    background-color: #2e3560;
    color: #e8ecff;
    border: 1px solid #3d477f;
    selection-background-color: #4a5590;
    selection-color: #ffffff;
}
QTabWidget::pane { border: 1px solid #3d477f; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background-color: #2e3560;
    color: #8f97c0;
    padding: 6px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected { background-color: #3d477f; color: #ffd65a; }
QTabBar::tab:hover:!selected { color: #e8ecff; }
QTableWidget { gridline-color: #3d477f; alternate-background-color: #232842; }
QHeaderView::section {
    background-color: #2e3560;
    color: #8f97c0;
    border: none;
    border-right: 1px solid #3d477f;
    border-bottom: 1px solid #3d477f;
    padding: 5px 8px;
}
QTableCornerButton::section { background-color: #2e3560; border: none; }
QScrollBar:vertical { background: #262b40; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #3d477f; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #262b40; height: 10px; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #3d477f; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMessageBox, QInputDialog, QFileDialog { background-color: #1e2234; color: #e8ecff; }
"""

# 音效组槽位：kind -> 面板行标签
_SLOT_LABELS = (("press", "戳一下"), ("release", "松开"), ("feed", "喂食"),
                ("reply", "AI 回复"), ("coin", "金币"))

# 台词池：页签名 -> pool 名（与主程序 save_lines 的 pool 约定一致）
_LINE_POOLS = (("撒娇", "sajiao"), ("贪吃", "greedy"), ("开心", "happy"), ("闲逛", "idle"))

# 气泡默认样式（与现有 Bubble.paintEvent 一致：#ffffff 底、#203170 描边/文字）
_DEFAULT_BUBBLE_STYLE = {"bg": "#ffffff", "fg": "#203170", "border": "#203170",
                         "font_size": 10, "radius": 16}

# QMediaPlayer 保活引用（异步播放期间防 GC 回收，最多保留 4 个）
_MEDIA_KEEPALIVE = []


# ---------------- 通用助手 ----------------
def modal(dlg):
    """置顶 + 显式请求焦点后 exec（桌宠主窗口 WindowDoesNotAcceptFocus，
    子对话框不这么做会被 Windows 前台锁拦下）。返回 exec() 结果。"""
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.setFocus()
    return dlg.exec()


def _get(pet, name):
    """防御性取 pet 属性；任何异常返回 None。"""
    try:
        return getattr(pet, name, None)
    except Exception:
        return None


def _call(pet, name, *args):
    """防御性调用 pet 方法；缺失或抛异常返回 None。"""
    try:
        fn = getattr(pet, name, None)
        if callable(fn):
            return fn(*args)
    except Exception:
        pass
    return None


def _box(parent, icon, title, text):
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStyleSheet(DIALOG_QSS)
    return box


def _warn(parent, title, text):
    modal(_box(parent, QMessageBox.Icon.Warning, title, text))


def _info(parent, title, text):
    modal(_box(parent, QMessageBox.Icon.Information, title, text))


def _confirm(parent, title, text):
    """确认框：确定 / 取消；返回是否确定。"""
    box = _box(parent, QMessageBox.Icon.Question, title, text)
    yes = box.addButton("确定", QMessageBox.ButtonRole.YesRole)
    box.addButton("取消", QMessageBox.ButtonRole.NoRole)
    modal(box)
    return box.clickedButton() is yes


def _preview_audio(pet, path):
    """试听：优先 pet.preview_audio；缺省时本地兜底
    （wav → pet_audio.preview_file；mp3 → QMediaPlayer）。返回是否已播出。"""
    if not path:
        return False
    if _call(pet, "preview_audio", path) is True:
        return True
    try:
        if pet_audio.preview_file(path):
            return True
    except Exception:
        pass
    if os.path.splitext(str(path))[1].lower() == ".mp3":
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            player = QMediaPlayer()
            out = QAudioOutput()
            player.setAudioOutput(out)  # Qt 6.11 默认 audioOutput 为 None：不设会静音
            player.setSource(QUrl.fromLocalFile(str(path)))
            player.play()
            _MEDIA_KEEPALIVE.append((player, out))
            if len(_MEDIA_KEEPALIVE) > 4:
                old_p, _old_o = _MEDIA_KEEPALIVE.pop(0)
                try:
                    old_p.stop()  # 先停再释放，避免正在播放的兜底音被 GC 掐断
                except Exception:
                    pass
            return True
        except Exception:
            pass
    return False


def _detail_table(headers):
    """构建统一风格的明细 QTableWidget。"""
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.setStyleSheet(DIALOG_QSS)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    hh.setStretchLastSection(True)
    return t


def _fill_detail(table, records):
    """明细表填充：日期/时间/类型(API消费/手动)/金额/备注；金额右对齐 %.2f。"""
    table.setRowCount(len(records))
    for i, r in enumerate(records):
        kind = "API消费" if r["kind"] == "api" else "手动"
        cells = (r["date"], r["time"], kind, "%.2f" % r["amount"], r["note"] or "")
        for j, text in enumerate(cells):
            item = QTableWidgetItem(str(text))
            if j == 3:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, j, item)


def _png_has_alpha(src):
    """PNG 是否带透明：QPixmap 判定优先；另兼容「调色板+tRNS」的合法透明 PNG。"""
    try:
        pix = QPixmap(src)
        if pix.isNull():
            return False
        if pix.hasAlphaChannel():
            return True
        import struct
        with open(src, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return False
            while True:
                head = f.read(8)
                if len(head) < 8:
                    return False
                (length,) = struct.unpack(">I", head[:4])
                ctype = head[4:8]
                if ctype == b"tRNS":
                    return True  # tRNS 出现在 IDAT 之前即视为有透明
                if ctype == b"IDAT":
                    return False
                f.seek(length + 4, 1)
    except Exception:
        return False


def _qt_parent(pet):
    """pet 必须是 Qt 窗口才能作父对象；否则用 None（缺省不崩）。"""
    return pet if isinstance(pet, QWidget) else None


# ---------------- a) 角色面板 ----------------
class RolePanel(QWidget):
    """角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。"""

    MAX_BYTES = 10 * 1024 * 1024
    MAX_PX = 2048

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "role_lib")
        self.setStyleSheet(DIALOG_QSS)

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self._info = QLabel("当前：默认角色")
        left.addWidget(self._info)
        self._list = QListWidget()
        self._list.setMinimumWidth(340)
        self._list.currentItemChanged.connect(self._on_select)
        left.addWidget(self._list, 1)
        btns = QHBoxLayout()
        self._btn_import = QPushButton("导入角色…")
        self._btn_set = QPushButton("设为当前")
        self._btn_del = QPushButton("删除")
        self._btn_default = QPushButton("恢复默认")
        for b in (self._btn_import, self._btn_set, self._btn_del, self._btn_default):
            btns.addWidget(b)
        self._btn_import.clicked.connect(self._import)
        self._btn_set.clicked.connect(self._set_active)
        self._btn_del.clicked.connect(self._delete)
        self._btn_default.clicked.connect(self._reset_default)
        left.addLayout(btns)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        self._preview = QLabel("预览")
        self._preview.setFixedSize(200, 200)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview)
        self._meta = QLabel("")
        right.addWidget(self._meta)
        right.addStretch(1)
        root.addLayout(right)

        self._refresh()

    # ---------- 内部 ----------
    def _refresh(self):
        self._list.clear()
        if self._lib is None:
            self._list.addItem("角色库不可用")
            for b in (self._btn_import, self._btn_set, self._btn_del, self._btn_default):
                b.setEnabled(False)
            self._info.setText("当前：默认角色")
            self._preview.setText("角色库不可用")
            self._preview.setPixmap(QPixmap())
            self._meta.setText("")
            return
        for b in (self._btn_import, self._btn_set, self._btn_del, self._btn_default):
            b.setEnabled(True)
        active = self._lib.active_id()
        active_name = ""
        for role in self._lib.list_roles():
            size_text = "?x?"
            p = self._lib.path_for(role["id"])
            if p:
                try:
                    pix = QPixmap(p)
                    if not pix.isNull():
                        size_text = "%dx%d" % (pix.width(), pix.height())
                except Exception:
                    pass
            mark = " [当前]" if role["id"] == active else ""
            it = QListWidgetItem("%s  %s  %s%s" % (role["name"], size_text, role.get("added", ""), mark))
            it.setData(Qt.ItemDataRole.UserRole, role["id"])
            self._list.addItem(it)
            if role["id"] == active:
                active_name = role["name"]
                self._list.setCurrentItem(it)
        self._info.setText(("当前：%s" % active_name) if active else "当前：默认角色")
        if self._list.count() == 0:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("暂无角色\n导入透明底 PNG 即可换装")
            self._meta.setText("")

    def _on_select(self, item, _prev):
        if item is None or self._lib is None:
            self._preview.setPixmap(QPixmap())
            self._meta.setText("")
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        p = self._lib.path_for(rid)
        if not p:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("文件缺失，无法预览")
            self._meta.setText("")
            return
        pix = QPixmap(p)
        if pix.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText("无法预览")
            self._meta.setText("")
            return
        scaled = pix.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        self._preview.setText("")
        self._preview.setPixmap(scaled)
        self._meta.setText("%dx%d" % (pix.width(), pix.height()))

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    # ---------- 动作 ----------
    def _import(self):
        if self._lib is None:
            return
        src, _f = QFileDialog.getOpenFileName(self._parent_widget(), "导入角色", "", "PNG 图片 (*.png)")
        if not src:
            return
        try:
            if os.path.getsize(src) > self.MAX_BYTES:
                _warn(self._parent_widget(), "导入角色", "文件超过 10MB，无法导入")
                return
            pix = QPixmap(src)
            if pix.isNull():
                _warn(self._parent_widget(), "导入角色", "无法加载该图片，可能不是有效的 PNG")
                return
            if pix.width() > self.MAX_PX or pix.height() > self.MAX_PX:
                _warn(self._parent_widget(), "导入角色", "图片超过 %dpx，无法导入" % self.MAX_PX)
                return
            if not _png_has_alpha(src):
                _warn(self._parent_widget(), "导入角色",
                      "需要透明背景 PNG（可用「去背景.py」处理后再导入）")
                return
        except Exception:
            _warn(self._parent_widget(), "导入角色", "读取图片失败")
            return
        role, err = self._lib.import_file(src)
        if role is None:
            _warn(self._parent_widget(), "导入角色", err or "导入失败")
            return
        _call(self._pet, "apply_role", role["id"])  # 导入即切换为新角色
        self._refresh()

    def _set_active(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        if hasattr(self._pet, "apply_role"):
            _call(self._pet, "apply_role", rid)  # 主线内部 set_active + 保存 + 重载贴图
        elif not self._lib.set_active(rid):
            _warn(self._parent_widget(), "切换角色", "切换失败")
            return
        self._refresh()

    def _delete(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        role = self._lib.get(rid) or {}
        if not _confirm(self._parent_widget(), "删除角色",
                        "确定删除角色「%s」吗？" % role.get("name", "")):
            return
        ok, err = self._lib.delete(rid)
        if not ok:
            _warn(self._parent_widget(), "删除角色", err or "删除失败")
            return
        self._refresh()
        _call(self._pet, "apply_role", self._lib.active_id())

    def _reset_default(self):
        if self._lib is None:
            return
        if hasattr(self._pet, "apply_role"):
            _call(self._pet, "apply_role", "")
        else:
            self._lib.set_active("")
        self._refresh()


# ---------------- b) 音效面板 ----------------
class SoundPanel(QWidget):
    """音频片段列表（试听 / 导入 / 重命名 / 删除）+ 自定义音效组 5 行槽位。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "audio_lib")
        self.setStyleSheet(DIALOG_QSS)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("音频片段（自定义音效素材）"))
        top = QHBoxLayout()
        self._list = QListWidget()
        self._list.setMinimumHeight(130)
        top.addWidget(self._list, 1)
        rbtns = QVBoxLayout()
        b_preview = QPushButton("试听")
        b_import = QPushButton("导入音频…")
        b_rename = QPushButton("重命名")
        b_del = QPushButton("删除")
        for b in (b_preview, b_import, b_rename, b_del):
            rbtns.addWidget(b)
        b_preview.clicked.connect(self._preview_selected)
        b_import.clicked.connect(self._import_audio)
        b_rename.clicked.connect(self._rename)
        b_del.clicked.connect(self._delete_audio)
        rbtns.addStretch(1)
        top.addLayout(rbtns)
        root.addLayout(top)

        root.addWidget(QLabel("自定义音效组（留默认 = 用内置音效，静音 = 该事件不出声）"))
        grid = QGridLayout()
        self._combos = {}
        for i, (kind, label) in enumerate(_SLOT_LABELS):
            cb = QComboBox()
            cb.currentIndexChanged.connect(lambda _idx, k=kind: self._on_slot(k))
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(cb, i, 1)
            self._combos[kind] = cb
        root.addLayout(grid)

        self._refresh()

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    # ---------- 内部 ----------
    def _refresh(self):
        self._list.clear()
        frags = self._lib.fragments() if self._lib else []
        for f in frags:
            dur = f.get("duration")
            dur_text = ("%.1fs" % dur) if isinstance(dur, (int, float)) else "?s"
            it = QListWidgetItem("%s  ·  %s  ·  %s" % (f["name"], dur_text, f.get("ext", "")))
            it.setData(Qt.ItemDataRole.UserRole, f["id"])
            self._list.addItem(it)
        slots = None
        if self._lib is not None:
            try:
                slots = self._lib.group_slots().get("custom", {})
            except Exception:
                slots = None
        for kind, cb in self._combos.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("默认")
            cb.addItem("静音")
            for f in frags:
                cb.addItem(f["name"])
            val = slots.get(kind) if slots else None
            if val == "":
                cb.setCurrentIndex(1)
            elif val:
                idx = -1
                for i, f in enumerate(frags):
                    if f["id"] == val:
                        idx = i
                        break
                cb.setCurrentIndex(2 + idx if idx >= 0 else 0)
            else:
                cb.setCurrentIndex(0)
            cb.setEnabled(self._lib is not None)
            cb.blockSignals(False)

    def _on_slot(self, kind):
        if self._lib is None:
            return
        cb = self._combos[kind]
        idx = cb.currentIndex()
        frags = self._lib.fragments()
        if idx == 0:
            fid = None      # 默认：走内置音效
        elif idx == 1:
            fid = ""        # 静音
        else:
            fi = idx - 2
            fid = frags[fi]["id"] if 0 <= fi < len(frags) else None
        if not self._lib.set_slot(kind, fid):
            _warn(self._parent_widget(), "音效组",
                  "该槽位仅支持 wav 片段（mp3 可以试听，但事件播放不支持）")
            self._refresh()  # 回滚组合框显示
            return
        _call(self._pet, "apply_sound_group", self._lib.group_paths())

    # ---------- 动作 ----------
    def _preview_selected(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "试听", "先在列表里选中一个音频片段")
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        path = self._lib.fragment_path(fid)
        if not path:
            _warn(self._parent_widget(), "试听", "音频文件丢失，无法试听")
            return
        if not _preview_audio(self._pet, path):
            _warn(self._parent_widget(), "试听", "该音频暂不支持试听（仅 wav/mp3）")

    def _import_audio(self):
        if self._lib is None:
            return
        src, _f = QFileDialog.getOpenFileName(self._parent_widget(), "导入音频", "",
                                              "音频文件 (*.wav *.mp3)")
        if not src:
            return
        frag, err = self._lib.import_file(src)
        if frag is None:
            _warn(self._parent_widget(), "导入音频", err or "导入失败")
            return
        self._refresh()

    def _rename(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        f = None
        for x in self._lib.fragments():
            if x["id"] == fid:
                f = x
                break
        if f is None:
            return
        dlg = QInputDialog(self._parent_widget())
        dlg.setWindowTitle("重命名片段")
        dlg.setLabelText("新名字：")
        dlg.setTextValue(f["name"])
        dlg.setStyleSheet(DIALOG_QSS)
        if modal(dlg) != QDialog.DialogCode.Accepted:
            return
        name = dlg.textValue().strip()
        if not name:
            return
        ok, err = self._lib.rename(fid, name)
        if not ok:
            _warn(self._parent_widget(), "重命名", err or "重命名失败")
            return
        self._refresh()

    def _delete_audio(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        f = None
        for x in self._lib.fragments():
            if x["id"] == fid:
                f = x
                break
        if f is None:
            return
        if not _confirm(self._parent_widget(), "删除音频",
                        "确定删除片段「%s」吗？\n引用它的音效组槽位将变为静音。" % f["name"]):
            return
        ok, err = self._lib.delete(fid)
        if not ok:
            _warn(self._parent_widget(), "删除音频", err or "删除失败")
            return
        self._refresh()
        _call(self._pet, "apply_sound_group", self._lib.group_paths())


# ---------------- c) 资源管理对话框 ----------------
class ResourceManagerDialog(QDialog):
    """QTabWidget 两页签（角色 / 音效），内嵌 RolePanel / SoundPanel。"""

    def __init__(self, parent=None, initial_tab=0):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("资源管理")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(680, 520)

        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.addTab(RolePanel(parent), "角色")
        self._tabs.addTab(SoundPanel(parent), "音效")
        self._tabs.setCurrentIndex(1 if initial_tab == 1 else 0)
        root.addWidget(self._tabs, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        row.addWidget(close_btn)
        root.addLayout(row)


# ---------------- d) 记账账本对话框 ----------------
class AmountNoteDialog(QDialog):
    """记一笔：金额 QDoubleSpinBox(0.01~99999) + 备注 QLineEdit + 确定/取消。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self.setWindowTitle("记一笔")
        self.setStyleSheet(DIALOG_QSS)
        root = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("金额："), 0, 0)
        self._amount = QDoubleSpinBox()
        self._amount.setRange(0.01, 99999.0)
        self._amount.setDecimals(2)
        self._amount.setValue(1.0)
        self._amount.setSuffix(" ¥")
        grid.addWidget(self._amount, 0, 1)
        grid.addWidget(QLabel("备注："), 1, 0)
        self._note = QLineEdit()
        self._note.setPlaceholderText("例如：买了小鱼干（可留空）")
        grid.addWidget(self._note, 1, 1)
        root.addLayout(grid)
        row = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)
        root.addLayout(row)

    def values(self):
        """返回 (金额 float 保留两位, 备注 str)。"""
        return round(float(self._amount.value()), 2), self._note.text().strip()


class LedgerDialog(QDialog):
    """账本：汇总 + 实时搜索 + 今日 / 近 7 天 / 全部 三页签 + 记一笔 / 导出 CSV。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._book = _get(parent, "book")
        self.setWindowTitle("记账账本")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(680, 540)

        root = QVBoxLayout(self)
        self._summary = QLabel("")
        self._summary.setStyleSheet("font-weight:bold;color:#ffd65a;")
        root.addWidget(self._summary)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("搜索："))
        self._search = QLineEdit()
        self._search.setPlaceholderText("按日期或备注搜索（实时过滤）")
        self._search.textChanged.connect(self._refresh)
        srow.addWidget(self._search, 1)
        root.addLayout(srow)

        self._tabs = QTabWidget()
        self._today_table = _detail_table(("日期", "时间", "类型", "金额", "备注"))
        self._week_table = _detail_table(("日期", "金额", "笔数"))
        self._all_table = _detail_table(("日期", "时间", "类型", "金额", "备注"))
        self._tabs.addTab(self._today_table, "今日")
        self._tabs.addTab(self._week_table, "近 7 天")
        self._tabs.addTab(self._all_table, "全部")
        self._tabs.currentChanged.connect(lambda _i: self._refresh())
        root.addWidget(self._tabs, 1)

        row = QHBoxLayout()
        self._btn_add = QPushButton("记一笔…")
        self._btn_export = QPushButton("导出 CSV…")
        close_btn = QPushButton("关闭")
        self._btn_add.clicked.connect(self._add_manual)
        self._btn_export.clicked.connect(self._export)
        close_btn.clicked.connect(self.reject)
        row.addWidget(self._btn_add)
        row.addWidget(self._btn_export)
        row.addStretch(1)
        row.addWidget(close_btn)
        root.addLayout(row)

        if self._book is None:
            self._btn_add.setEnabled(False)
            self._btn_export.setEnabled(False)
        self._refresh()

    # ---------- 内部 ----------
    def _refresh(self):
        book = self._book
        if book is None:
            self._summary.setText("账本不可用")
            for t in (self._today_table, self._week_table, self._all_table):
                t.setRowCount(0)
            return
        today = book.today_usage()
        week = book.week_usage()
        total = book.total_amount()
        count = book.total_count()
        self._summary.setText("今日 ¥%.2f · 近7天 ¥%.2f · 累计 ¥%.2f / %d 笔"
                              % (today, week, total, count))
        term = self._search.text().strip().lower()

        # 今日明细
        tdate = time.strftime("%Y-%m-%d")
        today_recs = [r for r in book.all_records() if r["date"] == tdate]
        if term:
            today_recs = [r for r in today_recs
                          if term in r["date"].lower() or term in (r["note"] or "").lower()]
        _fill_detail(self._today_table, today_recs)

        # 近 7 天按日汇总
        counts = {}
        for r in book.all_records():
            counts[r["date"]] = counts.get(r["date"], 0) + 1
        week_rows = [(d, amt, counts.get(d, 0)) for d, amt in book.daily_totals(7)]
        if term:
            week_rows = [w for w in week_rows if term in w[0].lower()]
        self._week_table.setRowCount(len(week_rows))
        for i, (d, amt, n) in enumerate(week_rows):
            for j, text in enumerate((d, "%.2f" % amt, str(n))):
                item = QTableWidgetItem(text)
                if j == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._week_table.setItem(i, j, item)

        # 全部明细
        all_recs = book.search_records(term) if term else book.all_records()
        _fill_detail(self._all_table, all_recs)

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    # ---------- 动作 ----------
    def _add_manual(self):
        book = self._book
        if book is None:
            return
        dlg = AmountNoteDialog(self)
        if modal(dlg) != QDialog.DialogCode.Accepted:
            return
        amount, note = dlg.values()
        if amount <= 0:
            return
        book.add_manual(amount, note)
        self._refresh()
        _call(self._pet, "on_ledger_changed")
        _call(self._pet, "show_bubble", "记下啦：¥%.2f" % amount)

    def _export(self):
        book = self._book
        if book is None:
            return
        default_path = os.path.join(os.path.expanduser("~"), "ledger.csv")
        path, _f = QFileDialog.getSaveFileName(self._parent_widget(), "导出 CSV",
                                               default_path, "CSV 文件 (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        ok, err = book.export_csv(path)
        if ok:
            _info(self._parent_widget(), "导出成功", "已导出到：\n%s" % path)
        else:
            _warn(self._parent_widget(), "导出失败", err or "导出失败")


# ---------------- e) 气泡样式对话框 ----------------
class BubbleStyleDialog(QDialog):
    """气泡样式：三色 + 字号 8~18 + 圆角 0~30 + 实时预览。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("气泡样式")
        self.setStyleSheet(DIALOG_QSS)
        self._style = dict(_DEFAULT_BUBBLE_STYLE)
        # 从配置取当前样式（防御性：缺键 / 类型非法都回退默认）
        try:
            cfg = _get(parent, "cfg") or {}
            s = cfg.get("bubble_style") if isinstance(cfg, dict) else None
            if isinstance(s, dict):
                for k in self._style:
                    v = s.get(k)
                    if v is not None:
                        self._style[k] = v
        except Exception:
            pass

        root = QVBoxLayout(self)
        grid = QGridLayout()
        self._color_btns = {}
        for i, (label, key) in enumerate((("背景色", "bg"), ("文字色", "fg"), ("描边色", "border"))):
            btn = QPushButton()
            btn.setFixedSize(72, 26)
            btn.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            self._color_btns[key] = btn
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(btn, i, 1)
        grid.addWidget(QLabel("字号"), 3, 0)
        self._font_spin = QSpinBox()
        self._font_spin.setRange(8, 18)
        self._font_spin.valueChanged.connect(lambda _v: self._apply_preview())
        grid.addWidget(self._font_spin, 3, 1)
        grid.addWidget(QLabel("圆角"), 4, 0)
        self._radius_spin = QSpinBox()
        self._radius_spin.setRange(0, 30)
        self._radius_spin.valueChanged.connect(lambda _v: self._apply_preview())
        grid.addWidget(self._radius_spin, 4, 1)
        root.addLayout(grid)

        self._preview = QLabel("绳匠，小鱼干呢？")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(260, 84)
        root.addWidget(self._preview)

        row = QHBoxLayout()
        save_btn = QPushButton("保存")
        reset_btn = QPushButton("恢复默认")
        cancel_btn = QPushButton("取消")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        reset_btn.clicked.connect(self._reset_default)
        cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(save_btn)
        row.addWidget(reset_btn)
        row.addWidget(cancel_btn)
        root.addLayout(row)

        self._update_color_buttons()
        self._apply_preview()

    # ---------- 内部 ----------
    @staticmethod
    def _to_int(v, default):
        try:
            return int(v)
        except Exception:
            return default

    def _update_color_buttons(self):
        for key, btn in self._color_btns.items():
            c = str(self._style.get(key, "#ffffff"))
            btn.setStyleSheet(
                "QPushButton { background-color: %s; border: 1px solid #3d477f;"
                " border-radius: 6px; }" % c)

    def _apply_preview(self):
        s = self._style
        s["font_size"] = self._font_spin.value()
        s["radius"] = self._radius_spin.value()
        self._preview.setStyleSheet(
            "QLabel { background-color: %s; color: %s; border: 2px solid %s;"
            " border-radius: %dpx; padding: 12px 16px; font-size: %dpt; }"
            % (s["bg"], s["fg"], s["border"], self._to_int(s["radius"], 16),
               self._to_int(s["font_size"], 10)))

    def _pick(self, key):
        cur = QColor(str(self._style.get(key, "#ffffff")))
        c = QColorDialog.getColor(cur, self, "选择颜色")
        if c.isValid():
            self._style[key] = c.name()
            self._update_color_buttons()
            self._apply_preview()

    # ---------- 动作 ----------
    def _save(self):
        self._style["font_size"] = self._font_spin.value()
        self._style["radius"] = self._radius_spin.value()
        style = {
            "bg": str(self._style["bg"]),
            "fg": str(self._style["fg"]),
            "border": str(self._style["border"]),
            "font_size": self._to_int(self._style["font_size"], 10),
            "radius": self._to_int(self._style["radius"], 16),
        }
        _call(self._pet, "apply_bubble_style", style)
        self.accept()

    def _reset_default(self):
        self._style = dict(_DEFAULT_BUBBLE_STYLE)
        self._font_spin.setValue(10)
        self._radius_spin.setValue(16)
        self._update_color_buttons()
        self._apply_preview()


# ---------------- f) 台词设置对话框 ----------------
class LinesDialog(QDialog):
    """台词设置：撒娇 / 贪吃 / 开心 / 闲逛 四页，每行一条台词。"""

    MAX_LINES = 20
    MAX_CHARS = 60

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("台词设置")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(540, 440)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("每行一条台词；最多 %d 行、每行最多 %d 字。留空 = 使用内置台词。"
                              % (self.MAX_LINES, self.MAX_CHARS)))
        self._tabs = QTabWidget()
        self._edits = {}
        for label, pool in _LINE_POOLS:
            ed = QPlainTextEdit()
            ed.setPlaceholderText("每行一条，留空 = 使用内置「%s」台词" % label)
            self._edits[pool] = ed
            self._tabs.addTab(ed, label)
        root.addWidget(self._tabs, 1)

        row = QHBoxLayout()
        save_btn = QPushButton("保存")
        reset_btn = QPushButton("恢复默认")
        cancel_btn = QPushButton("取消")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        reset_btn.clicked.connect(self._reset_default)
        cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(save_btn)
        row.addWidget(reset_btn)
        row.addWidget(cancel_btn)
        root.addLayout(row)

        self._load_current()

    # ---------- 内部 ----------
    def _load_current(self):
        """从 pet.cfg["lines_extra"] 读现有自定义台词；缺失则留空（= 使用内置）。"""
        custom = {}
        try:
            cfg = _get(self._pet, "cfg") or {}
            if isinstance(cfg, dict):
                lines = cfg.get("lines_extra")
                if isinstance(lines, dict):
                    custom = lines
        except Exception:
            custom = {}
        for _label, pool in _LINE_POOLS:
            ed = self._edits[pool]
            pool_lines = custom.get(pool)
            text = "\n".join(str(x) for x in pool_lines) if isinstance(pool_lines, list) else ""
            ed.setPlainText(text)

    @staticmethod
    def _parse(ed):
        return [ln.strip() for ln in ed.toPlainText().splitlines() if ln.strip()]

    # ---------- 动作 ----------
    def _save(self):
        for label, pool in _LINE_POOLS:
            ed = self._edits[pool]
            lines = self._parse(ed)
            if len(lines) > self.MAX_LINES:
                _warn(self, "保存失败", "「%s」最多 %d 行（当前 %d 行）"
                      % (label, self.MAX_LINES, len(lines)))
                self._tabs.setCurrentWidget(ed)
                return
            for ln in lines:
                if len(ln) > self.MAX_CHARS:
                    _warn(self, "保存失败", "「%s」有台词超过 %d 字：%s…"
                          % (label, self.MAX_CHARS, ln[:12]))
                    self._tabs.setCurrentWidget(ed)
                    return
        for _label, pool in _LINE_POOLS:
            _call(self._pet, "save_lines", pool, self._parse(self._edits[pool]))
        self.accept()

    def _reset_default(self):
        """把当前页签的自定义台词清空（保存空列表 = 主线回落到内置台词）。"""
        idx = self._tabs.currentIndex()
        label, pool = _LINE_POOLS[idx]
        self._edits[pool].clear()
        _call(self._pet, "save_lines", pool, [])
        _call(self._pet, "show_bubble", "「%s」台词恢复默认啦~" % label)
