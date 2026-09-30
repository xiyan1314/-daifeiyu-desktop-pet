# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 全部 Qt 对话框 / 面板（v1.3.0 新增）。

职责：参考 dsh-whale-widget 的「角色管理 / 音频片段管理 / 音效组 / 记账账本」
面板设计，提供资源管理、记账账本、气泡样式、台词设置四个交互界面。

对外接口（全部在主线程使用；构造签名 parent 为桌宠主窗口）：
- DIALOG_QSS（常量）：统一深色圆角主题（#1e2234 底 / #2e3560 控件底 /
  #e8ecff 文字 / #ffd65a 强调 / 圆角 8px），覆盖 QDialog/QPushButton/
  QListWidget/QTableWidget/QComboBox/QTabWidget/QLineEdit/QPlainTextEdit/
  QSpinBox/QDoubleSpinBox/QLabel/QRadioButton，以及弹窗类
  QMessageBox/QInputDialog/QFileDialog 与滚动条/表头等辅助控件。
- modal(dlg)：加 WindowStaysOnTopHint + show/raise_/activateWindow/setFocus
  后 exec（应对 Windows 前台锁，参考主程序 _set_api_key）。
- class RolePanel(QWidget)：角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。
- class RoleImportDialog(QDialog)：角色导入向导——1~8 个形态自由增删、
  每个形态独立命名选图；素材自动处理（去背景/裁剪/缩放）；
  支持多帧动画素材（多选图片 = 帧序列、视频/GIF 自动抽帧，统一画布处理）。
  P1-1 起：素材处理与视频/GIF 抽帧在 _ImportWorker 工作线程执行（可取消、
  进度信号回主线程），UI 不阻塞、无 QApplication.processEvents。
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
- 所有对话框统一 DIALOG_QSS 深色主题；角色导入支持多形态（1~8 个，
  名字自定义），素材导入时自动处理（无透明通道自动去背景、裁剪透明边距、
  超大图等比缩小）。
- 金额统一 "%.2f" 显示，表格金额列右对齐。

Python 3.8+ 兼容。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import copy
import os
import shutil
import tempfile
import time

import pet_log

from PySide6.QtCore import QEventLoop, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
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
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import pet_audio
import pet_resources  # P3-5+：FRAME_MAX（帧上限用户可调）

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
        return None  # 有意忽略：防御性取属性，异常按缺失处理（缺省不崩）


def _call(pet, name, *args):
    """防御性调用 pet 方法；缺失或抛异常返回 None。"""
    try:
        fn = getattr(pet, name, None)
        if callable(fn):
            return fn(*args)
    except Exception:
        pass  # 有意忽略：防御性调用，缺失/异常按失败处理（缺省不崩）
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
        pass  # 有意忽略：本地试听失败继续尝试 mp3 兜底
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
                    pass  # 有意忽略：停旧播放器失败直接丢弃（尽力而为）
            return True
        except Exception as e:
            pet_log.log_error("pet_dialogs._preview_audio: mp3 兜底播放失败 %r" % (e,))
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


# ---------------- 角色素材自动处理（导入向导用） ----------------
_IMG_MAX_PROCESS_PX = 2048   # 去背景前的预缩放上限（限制泛洪耗时）
_IMG_TARGET_MAX_PX = 512     # 输出统一上限（角色太大/太小都不合适）
_IMG_BG_TOL = 40             # 去背景颜色容差（RGB 各通道最大差值）
_IMG_MIN_PX = 8


class ImportCancelled(Exception):
    """P1-1：用户取消导入/抽帧处理（工作线程内抛出，上层转为友好提示）。"""


def _remove_background(img, cancel=None):
    """无透明通道图自动去背景：从四边泛洪「与边界同色相连」的区域并置透明。

    返回处理后的 QImage；若剩余内容不足 1%（背景色与主体大面积同色相连）
    判定失败并返回 None（调用方保留原图并提示）。
    """
    from collections import deque
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return None
    try:
        raw = bytearray(img.bits())
    except Exception:
        return None  # 有意忽略：像素读取失败按处理失败返回（调用方保留原图并提示）
    bpl = img.bytesPerLine()
    n = w * h
    visited = bytearray(n)
    dq = deque()
    for x in range(w):
        dq.append((x, 0))
        dq.append((x, h - 1))
    for y in range(1, h - 1):
        dq.append((0, y))
        dq.append((w - 1, y))
    processed = 0
    while dq:
        x, y = dq.popleft()
        i = y * w + x
        if visited[i]:
            continue
        visited[i] = 1
        processed += 1
        if processed % 8192 == 0:
            if cancel is not None and cancel():
                raise ImportCancelled()
        p = y * bpl + x * 4  # 行对齐：与 _content_bbox 的 y*bpl+x*4 一致
        r, g, b = raw[p], raw[p + 1], raw[p + 2]
        if x > 0 and not visited[i - 1]:
            q = p - 4
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x - 1, y))
        if x < w - 1 and not visited[i + 1]:
            q = p + 4
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x + 1, y))
        if y > 0 and not visited[i - w]:
            q = p - bpl
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x, y - 1))
        if y < h - 1 and not visited[i + w]:
            q = p + bpl
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x, y + 1))
    keep = 0
    for y in range(h):
        row = y * bpl
        for x in range(w):
            i = y * w + x
            if visited[i]:
                raw[row + x * 4 + 3] = 0
            elif raw[row + x * 4 + 3] > 0:
                keep += 1
    if keep < max(64, n // 100):
        return None  # 几乎全被吃：判定失败，保留原图
    out = QImage(raw, w, h, bpl, QImage.Format.Format_ARGB32)
    return out.copy()


def _content_bbox(img, cancel=None):
    """非透明像素包围盒 (x, y, w, h)；全透明返回 None。"""
    w, h = img.width(), img.height()
    try:
        raw = bytearray(img.bits())
    except Exception:
        return None  # 有意忽略：像素读取失败按包围盒计算失败返回（调用方保留原图）
    bpl = img.bytesPerLine()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * bpl
        if y % 256 == 0:
            if cancel is not None and cancel():
                raise ImportCancelled()
        for x in range(w):
            if raw[row + x * 4 + 3] > 8:
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    if maxx < 0:
        return None
    return (minx, miny, maxx - minx + 1, maxy - miny + 1)


def _load_prepared(src, max_px=None, cancel=None, remove_bg=True):
    """加载素材并做通用预处理：预缩放 → 无透明通道自动去背景（P1-7 可关）。

    max_px=None 用全局 _IMG_MAX_PROCESS_PX（2048）；帧动画可传 1024 控制峰值。
    remove_bg=False 跳过自动去背景（P1-7 高级选项；默认 True = 现行为）。
    返回 (img, notes) 或 (None, None)。notes 为这一阶段的说明列表。
    cancel 为可调用的取消检测（工作线程内周期询问），取消时抛 ImportCancelled。
    """
    img = QImage(src)
    if img.isNull():
        return None, None
    # 必须先查原图的 alpha（convertToFormat 成 ARGB32 后 hasAlphaChannel 恒为 True）
    had_alpha = img.hasAlphaChannel()
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    notes = []
    cap = int(max_px) if max_px else _IMG_MAX_PROCESS_PX
    if max(img.width(), img.height()) > cap:
        img = img.scaled(cap, cap,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        notes.append("超大图已预缩放")
    if not had_alpha:
        if remove_bg:
            removed = _remove_background(img, cancel=cancel)
            if removed is None:
                notes.append("背景与主体相连，保留原图")
            else:
                img = removed
                notes.append("已自动去背景")
        else:
            notes.append("未去背景（高级选项）")
    return img, notes


def _prepare_role_png(src, out_path, cancel=None, remove_bg=True, trim=True):
    """导入素材自动处理：无透明通道→去背景；裁剪透明边距；>512px 等比缩小。

    P1-7 高级选项：remove_bg=False 跳过去背景、trim=False 跳过透明边距裁剪
    （均默认 True = 现行为）。成功返回 (True, notes)；失败返回 (False, err)。
    notes 为中文说明列表。
    """
    img, notes = _load_prepared(src, cancel=cancel, remove_bg=remove_bg)
    if img is None:
        return False, "无法加载该图片"
    if trim:
        bbox = _content_bbox(img, cancel=cancel)
        if bbox is None:
            return False, "图片没有可见内容"
        x, y, w, h = bbox
        if (x, y, w, h) != (0, 0, img.width(), img.height()):
            img = img.copy(x, y, w, h)
            notes.append("已裁剪透明边距")
    else:
        notes.append("未裁剪透明边距（高级选项）")
    if max(img.width(), img.height()) > _IMG_TARGET_MAX_PX:
        img = img.scaled(_IMG_TARGET_MAX_PX, _IMG_TARGET_MAX_PX,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        notes.append("已等比缩放（最长边 ≤%dpx）" % _IMG_TARGET_MAX_PX)
    if img.width() < _IMG_MIN_PX or img.height() < _IMG_MIN_PX:
        return False, "图片内容太小"
    if not img.save(out_path, "PNG"):
        return False, "保存处理结果失败"
    return True, notes


def _prepare_role_frames(srcs, out_dir, same_size=True, cancel=None, progress=None,
                          remove_bg=True):
    """批量处理帧素材到统一画布（帧动画导入用）。

    same_size=True（视频/GIF 抽帧，原始尺寸一致）：先算全部帧的内容**并集 bbox**，
    所有帧裁到同一矩形（保留主体平移的动画信息），再统一等比缩放（长边 ≤512）。
    same_size=False（多选图片，尺寸可能不一）：逐帧独立处理（去背景/裁剪/缩放），
    最后把每帧内容居中放进最大帧尺寸的透明画布（尺寸一致、防帧间跳动）。
    P1-7：remove_bg=False 跳过自动去背景（高级选项，默认 True = 现行为）；
    帧间对齐依赖统一画布，裁剪恒开（不做 trim 开关）。
    返回 (out_paths, notes) 或 (None, err)。
    cancel 为取消检测回调（工作线程内周期询问）；progress 为进度文本回调。
    """
    n = len(srcs)
    imgs = []
    for i, s in enumerate(srcs):
        if cancel is not None and cancel():
            raise ImportCancelled()
        if progress is not None:
            progress("处理帧 %d/%d…" % (i + 1, n))
        img, _load_notes = _load_prepared(s, max_px=1024, cancel=cancel,
                                          remove_bg=remove_bg)  # 帧序列峰值控制（输出 ≤512）
        if img is None:
            return None, "第 %d 帧无法加载" % (i + 1)
        imgs.append(img)
    if same_size:
        # 并集 bbox：所有帧裁到同一矩形，保留帧间平移
        union = None
        for img in imgs:
            b = _content_bbox(img, cancel=cancel)
            if b is None:
                return None, "存在空白帧"
            if union is None:
                union = (b[0], b[1], b[0] + b[2], b[1] + b[3])
            else:
                union = (min(union[0], b[0]), min(union[1], b[1]),
                         max(union[2], b[0] + b[2]), max(union[3], b[1] + b[3]))
        ux, uy, ux2, uy2 = union
        uw, uh = ux2 - ux, uy2 - uy
        scale = min(1.0, _IMG_TARGET_MAX_PX / float(max(uw, uh)))
        cw, ch = max(1, int(round(uw * scale))), max(1, int(round(uh * scale)))
        outs = []
        for i, img in enumerate(imgs):
            if cancel is not None and cancel():
                raise ImportCancelled()
            crop = img.copy(ux, uy, uw, uh)
            if scale < 1.0:
                crop = crop.scaled(cw, ch, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            out = os.path.join(out_dir, "frame_f%02d.png" % i)
            if not crop.save(out, "PNG"):
                return None, "保存第 %d 帧失败" % (i + 1)
            outs.append(out)
        notes = ["统一画布 %dx%d（并集裁剪，保留平移）" % (cw, ch)]
        if scale < 1.0:
            notes.append("已等比缩放（最长边 ≤%dpx）" % _IMG_TARGET_MAX_PX)
        return outs, notes
    # 多选图片：逐帧独立处理 → 居中放进统一画布
    processed = []
    for i, img in enumerate(imgs):
        if cancel is not None and cancel():
            raise ImportCancelled()
        b = _content_bbox(img, cancel=cancel)
        if b is None:
            return None, "第 %d 帧没有可见内容" % (i + 1)
        x, y, w, h = b
        crop = img.copy(x, y, w, h)
        if max(w, h) > _IMG_TARGET_MAX_PX:
            crop = crop.scaled(_IMG_TARGET_MAX_PX, _IMG_TARGET_MAX_PX,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        processed.append(crop)
    max_w = max(p.width() for p in processed)
    max_h = max(p.height() for p in processed)
    outs = []
    for i, p in enumerate(processed):
        if cancel is not None and cancel():
            raise ImportCancelled()
        canvas = QImage(max_w, max_h, QImage.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        painter.drawImage((max_w - p.width()) // 2, (max_h - p.height()) // 2, p)
        painter.end()
        out = os.path.join(out_dir, "frame_f%02d.png" % i)
        if not canvas.save(out, "PNG"):
            return None, "保存第 %d 帧失败" % (i + 1)
        outs.append(out)
    notes = ["统一画布 %dx%d（逐帧居中）" % (max_w, max_h)]
    return outs, notes


def _qt_parent(pet):
    """pet 必须是 Qt 窗口才能作父对象；否则用 None（缺省不崩）。"""
    return pet if isinstance(pet, QWidget) else None


# ---------------- 视频 / GIF 抽帧 ----------------


def _pump_events(ms=10):
    """局部事件循环泵：在当前线程内处理事件（工作线程泵 QtMultimedia 帧投递）。
    P1-1：替代 QApplication.processEvents。注意：若在主线程调用，效果等同
    QApplication.processEvents 的局部版（同样会分发 GUI 事件）——生产路径全在
    工作线程，主线程只可能出现在 v13/绿色版无头直测中。"""
    loop = QEventLoop()
    t0 = time.time()
    while time.time() - t0 < ms / 1000.0:
        loop.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.002)


def _extract_video_frames(src, out_dir, cancel=None, progress=None):
    """从视频（mp4/webm/mov/avi 等）或 GIF 均匀抽帧（视频 3~20 帧、GIF 3~FRAME_MAX 帧；
    上限随用户配置 role_frame_max，抽帧时即按上限采样，不会白处理后再被导入拒绝）。

    视频走 QtMultimedia（QMediaPlayer + QVideoSink，绿色版自带 ffmpeg 后端），
    GIF 走 QImageReader（同步逐帧读，无事件循环依赖）。返回
    (原始帧 png 路径列表, err)；失败返回 (None, err)。
    捕获时即缩到 ≤1024（控制 4K 大视频的内存峰值），后续统一走
    _prepare_role_frames（并集画布 + 统一缩放，保留主体平移）。

    P1-1：全程可在工作线程调用（cancel/progress 可选回调）；视频路径的帧投递
    由本线程局部事件循环泵送，不阻塞 UI、不重入主事件循环。
    """
    ext = os.path.splitext(str(src))[1].lower()
    raws = []

    def _cap(img):
        if img is None or img.isNull():
            return
        if max(img.width(), img.height()) > 1024:
            img = img.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        raws.append(img)

    try:
        if ext == ".gif":
            reader = QImageReader(src)
            n = reader.imageCount()
            if n < 0:
                return None, "无法读取 GIF 帧数（文件可能损坏？）"
            if n <= 1:
                return None, "GIF 只有 %d 帧，帧动画至少需要 2 帧" % n
            if n > 120:
                return None, "GIF 帧数太多（%d 帧），建议改用视频或减少帧数" % n
            take = min(int(pet_resources.FRAME_MAX or 24), n)  # P3-5+：上限用户可调
            idxs = [int(round(i * (n - 1) / float(take - 1))) for i in range(take)]
            need = set(idxs)
            # 顺序读帧并只保留采样点：部分 GIF 插件 jumpToImage 返回 False
            # 但 read() 仍按序推进——用顺序读最稳，且最多只驻留 take 帧的内存
            i = 0
            while i < n:
                if cancel is not None and cancel():
                    raise ImportCancelled()
                img = reader.read()
                if img is None or img.isNull():
                    break
                if i in need:
                    if progress is not None:
                        progress("读取 GIF 帧 %d/%d…" % (i + 1, n))
                    _cap(img.convertToFormat(QImage.Format.Format_ARGB32))
                i += 1
        else:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
            player = QMediaPlayer()
            sink = QVideoSink()
            player.setVideoSink(sink)
            player.setSource(QUrl.fromLocalFile(os.path.abspath(src)))
            t0 = time.time()
            while player.duration() <= 0 and time.time() - t0 < 5:
                if cancel is not None and cancel():
                    player.stop()
                    raise ImportCancelled()
                _pump_events(20)
            dur = player.duration()
            if dur <= 0:
                player.stop()
                return None, "无法读取视频时长（格式不支持？可改用多选图片）"
            if not player.hasVideo():
                player.stop()
                return None, "该文件没有视频画面（纯音频？）"
            # 每约 0.4s 一帧；视频自身 ≤20 与用户配置上限取更小者（P3-5+）
            take = max(3, min(20, int(pet_resources.FRAME_MAX or 24), int(dur / 400)))
            got = []

            def _on_frame(frame):
                if frame.isValid() and not got:
                    got.append(frame.toImage())

            sink.videoFrameChanged.connect(_on_frame)
            if progress is not None:
                progress("读取首帧…")
            # S1：Qt6 ffmpeg 后端只在播放/暂停态向 sink 投帧——先 play() 拿首帧再 pause()
            # 大文件/高分辨率解码慢：首帧超时随文件大小放宽（无 GPU 软解 HEVC 场景）
            first_cap = 10 if os.path.getsize(src) > 50 * 1024 * 1024 else 5
            player.play()
            t0 = time.time()
            while not got and time.time() - t0 < first_cap:
                if cancel is not None and cancel():
                    player.stop()
                    raise ImportCancelled()
                _pump_events(10)
            player.pause()
            if not got:
                sink.videoFrameChanged.disconnect(_on_frame)
                player.stop()
                return None, "无法从视频读取画面"
            _cap(got[0])  # 首帧（t=0 位置）
            for i in range(1, take):
                if cancel is not None and cancel():
                    player.stop()
                    raise ImportCancelled()
                if progress is not None:
                    progress("抽视频帧 %d/%d…" % (i + 1, take))
                t = int(dur * i / float(take))
                del got[:]
                player.setPosition(t)  # 暂停态下 seek 仍会投递目标帧
                t1 = time.time()
                while not got and time.time() - t1 < 3:
                    if cancel is not None and cancel():
                        player.stop()
                        raise ImportCancelled()
                    _pump_events(10)
                if got:
                    _cap(got[0])
            sink.videoFrameChanged.disconnect(_on_frame)
            player.stop()
            # 注：worker 线程无事件循环，deleteLater 的 DeferredDelete 永不处理会泄漏 C++ 对象；
            # player/sink 均为局部变量，返回后由引用计数安全释放（sink 连接随析构断开）
    except ImportCancelled:
        raise
    except Exception as e:
        return None, "抽帧失败：%s" % e
    if len(raws) < 2:
        return None, "只抽到 %d 帧，帧动画至少需要 2 帧（可改用多选图片）" % len(raws)
    paths = []
    for i, img in enumerate(raws):
        p = os.path.join(out_dir, "raw_f%02d.png" % i)
        if not img.save(p, "PNG"):
            return None, "保存抽帧结果失败"
        paths.append(p)
    return paths, None


# ---------------- P1-1：导入工作线程 ----------------


def _run_import_pipeline(forms, frames_raw, frames_video, tmpdir, cancel=None, progress=None,
                         options=None):
    """角色导入的纯处理部分（无 UI），在工作线程内执行。

    options（P1-7 高级选项，全部可选，缺省 = 现行为）：
      {"remove_bg": bool, "trim": bool, "interval_ms": int|None,
       "render": dict|list, "keep_source": bool}
    返回 (result_dict, None) 或 (None, err)。result_dict 与旧 _do_import 一致，
    但不含 name（由主线程在完成时从控件实时读取，保持旧行为）；P1-7 起附加
    "options"（interval_ms/render/keep_source 回传落库用）与 "sources"
    （keep_source 时的原图路径列表）。
    """
    options = options or {}
    remove_bg = bool(options.get("remove_bg", True))
    trim = bool(options.get("trim", True))
    # P1-7：新选项仅在非默认时透传——保持旧调用签名完全兼容
    # （v13/绿色版用 stub 替换 _prepare_role_frames 时不接受新关键字参数）
    frame_kwargs = {}
    if not remove_bg:
        frame_kwargs["remove_bg"] = False
    png_kwargs = {}
    if not remove_bg:
        png_kwargs["remove_bg"] = False
    if not trim:
        png_kwargs["trim"] = False
    frames_out = []
    if frames_raw:
        if progress is not None:
            progress("帧动画统一画布处理…")
        frames_out, notesf = _prepare_role_frames(
            frames_raw, tmpdir, same_size=bool(frames_video), cancel=cancel,
            progress=progress, **frame_kwargs)
        if frames_out is None:
            return None, "帧处理失败：%s" % notesf
        base_out = frames_out[0]
        notes = ["帧动画 %d 帧：%s" % (len(frames_out), "、".join(notesf))]
        forms_out = [(forms[0][0], base_out)]
    else:
        base_out = os.path.join(tmpdir, "role_base.png")
        if progress is not None:
            progress("处理第 1 形态…")
        ok1, notes1 = _prepare_role_png(forms[0][1], base_out, cancel=cancel, **png_kwargs)
        if not ok1:
            return None, "第 1 形态处理失败：%s" % notes1
        notes = ["第 1 形态：%s" % ("、".join(notes1) if notes1 else "无需处理")]
        forms_out = [(forms[0][0], base_out)]
    for i, (nm, src) in enumerate(forms[1:], start=1):
        if cancel is not None and cancel():
            raise ImportCancelled()
        if progress is not None:
            progress("处理第 %d 形态（%s）…" % (i + 1, nm))
        fp = os.path.join(tmpdir, "form%d.png" % i)
        okf, notesf = _prepare_role_png(src, fp, cancel=cancel, **png_kwargs)
        if not okf:
            return None, "第 %d 形态处理失败：%s" % (i + 1, notesf)
        forms_out.append((nm, fp))
        notes.append("第 %d 形态（%s）：%s" % (i + 1, nm, "、".join(notesf) if notesf else "无需处理"))
    result = {"base": base_out, "frames": frames_out, "forms": forms_out, "notes": notes}
    # P1-7：高级选项回传（RolePanel 落库用；keep_source 时附带原图路径）
    result["options"] = {
        "interval_ms": options.get("interval_ms"),
        "render": options.get("render"),
        "keep_source": bool(options.get("keep_source")),
    }
    if options.get("keep_source"):
        sources = []
        for _nm, src in forms:
            if src and isinstance(src, str) and os.path.isfile(src):
                sources.append(src)
        sources.extend(frames_raw or [])
        result["sources"] = sources
    return result, None


class _ImportWorker(QThread):
    """P1-1：素材处理工作线程（图像管线 / 视频-GIF 抽帧）。

    任务 dict：{"kind": "extract", "src", "out_dir", "name_hint"} 或
    {"kind": "import", "forms", "frames_raw", "frames_video", "tmpdir"}。
    进度 progress(str)、结果 done_ok(object)、失败 failed(str) 经信号回主线程；
    cancel() 请求取消（管线周期检查，最终以 failed("已取消处理") 结束）。
    """
    progress = Signal(str)
    done_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self._task = task
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cancelled(self):
        return self._cancelled

    def run(self):
        task = self._task
        try:
            if task["kind"] == "extract":
                raws, err = _extract_video_frames(
                    task["src"], task["out_dir"],
                    cancel=self._is_cancelled, progress=self.progress.emit)
                if err:
                    self.failed.emit(err)
                else:
                    self.done_ok.emit({"raws": raws, "name_hint": task.get("name_hint", "")})
            else:
                res, err = _run_import_pipeline(
                    task["forms"], task.get("frames_raw") or [], task.get("frames_video", False),
                    task["tmpdir"], cancel=self._is_cancelled, progress=self.progress.emit,
                    options=task.get("options"))
                if err:
                    self.failed.emit(err)
                else:
                    self.done_ok.emit(res)
        except ImportCancelled:
            self.failed.emit("已取消处理")
        except Exception as e:
            self.failed.emit("处理失败：%s" % e)


# ---------------- 角色导入向导 ----------------
class RoleImportDialog(QDialog):
    """导入角色向导：1~8 个形态自由增删、每个形态独立命名选图（喂食循环切换）。

    素材支持静态图与多帧动画（多选图片 / 视频-GIF 抽帧）；
    点「导入」时自动处理（去背景/裁剪/缩放，静态走 _prepare_role_png、
    帧动画走 _prepare_role_frames 统一画布），结果经 result_data() 交
    RolePanel 落库；临时文件在 closeEvent 清理。
    """

    MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self.setWindowTitle("导入角色")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(600, 430)
        self._tmpdir = None
        self._result = None
        self._worker = None       # P1-1：在途工作线程（None=空闲）
        self._worker_kind = None  # P1-1：当前任务类型（extract/import）
        self._busy_state = False  # P1-1：处理中标志（形态行按钮随 busy 禁用）
        self._stopping = False    # P1-1：停止请求中（吞掉迟到进度，防覆盖「正在停止…」文案）
        # P1-1：应用退出前收敛在途工作线程（父窗口析构路径不经过 closeEvent，
        # 必须挂 aboutToQuit，否则 QThread: Destroyed while thread is still running）。
        # 注意：绑定方法会被应用单例强引用——closeEvent 真正关闭时必须 disconnect，
        # 否则每次打开向导泄漏一个隐藏对话框。
        try:
            QApplication.instance().aboutToQuit.connect(self._shutdown_worker)
        except Exception:
            pass  # instance() 为 None（无应用上下文）时静默跳过：此时也不存在退出流程

        root = QVBoxLayout(self)
        root.addWidget(QLabel("选好图片点「导入」即可：自动去背景、裁剪边距、统一大小。"))

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("角色名"))
        self._name_edit = QLineEdit()
        name_row.addWidget(self._name_edit, 1)
        root.addLayout(name_row)

        self._frames_raw = []   # 原始帧 png 路径（多选图片 / 视频抽帧）
        self._frames_video = False  # 帧是否来自同源视频/GIF（并集画布）
        self._name_hint = ""    # 素材源文件名（名字回退用，避免 raw_f00 当角色名）
        self._rawdir = None     # 抽帧临时目录
        # 形态列表（v1.4 多形态：1~8 个、名字自定义，喂食依次切换、12 秒后回第一形态）
        forms_head = QHBoxLayout()
        forms_head.addWidget(QLabel("形态（可改名；喂食依次切换，12 秒后回第一形态）"))
        self._add_form_btn = QPushButton("＋ 添加形态")
        self._add_form_btn.clicked.connect(self._add_form)
        forms_head.addStretch(1)
        forms_head.addWidget(self._add_form_btn)
        root.addLayout(forms_head)
        self._form_rows = []   # [{"name": str, "src": str}]，名字在导入时从控件读取
        self._forms_box = QVBoxLayout()
        root.addLayout(self._forms_box)
        self._add_form("常态")
        # 多帧素材（v1.3.2）：多选图片 = 帧序列；视频/GIF 自动抽帧
        fr_row = QHBoxLayout()
        fr_row.addWidget(QLabel("多帧动画"))
        m_btn = QPushButton("选多张图片…")
        m_btn.clicked.connect(self._pick_multi)
        v_btn = QPushButton("视频/GIF 抽帧…")
        v_btn.clicked.connect(self._pick_video)
        fr_row.addWidget(m_btn)
        fr_row.addWidget(v_btn)
        fr_row.addStretch(1)
        root.addLayout(fr_row)
        self._frames_status = QLabel("静态素材：也可选多张图片或视频/GIF 做帧动画")
        self._frames_status.setWordWrap(True)
        root.addWidget(self._frames_status)
        self._mat_btns = (m_btn, v_btn, self._add_form_btn)  # 素材选择按钮：处理期间统一禁用防重入

        # ---- P1-7 高级折叠区（全部可选，默认 = 现行为）----
        adv = QGroupBox("高级")
        adv.setCheckable(True)
        adv.setChecked(False)  # 默认折叠，不打扰常规导入
        adv_grid = QGridLayout(adv)
        self._adv_interval_chk = QCheckBox("自定义帧间隔")
        self._adv_interval = QSpinBox()
        self._adv_interval.setRange(10, 10000)
        self._adv_interval.setValue(140)
        self._adv_interval.setSuffix(" ms/帧")
        self._adv_interval.setEnabled(False)
        self._adv_interval_chk.toggled.connect(self._adv_interval.setEnabled)
        self._adv_rmbg = QCheckBox("自动去背景（无透明通道时）")
        self._adv_rmbg.setChecked(True)   # 默认开 = 现行为
        self._adv_trim = QCheckBox("裁剪透明边距")
        self._adv_trim.setChecked(True)   # 默认开 = 现行为
        self._adv_keep = QCheckBox("保留原图到角色目录 source/")
        self._adv_keep.setChecked(False)  # P2-6：默认关以减小体积
        self._adv_render_chk = QCheckBox("自定义渲染参数（锚点/缩放/偏移）")
        self._adv_anchor_x = QDoubleSpinBox()
        self._adv_anchor_x.setRange(0.0, 1.0)
        self._adv_anchor_x.setSingleStep(0.05)
        self._adv_anchor_x.setDecimals(2)
        self._adv_anchor_x.setValue(0.5)
        self._adv_anchor_y = QDoubleSpinBox()
        self._adv_anchor_y.setRange(0.0, 1.0)
        self._adv_anchor_y.setSingleStep(0.05)
        self._adv_anchor_y.setDecimals(2)
        self._adv_anchor_y.setValue(0.5)
        self._adv_scale = QDoubleSpinBox()
        self._adv_scale.setRange(0.1, 4.0)
        self._adv_scale.setSingleStep(0.05)
        self._adv_scale.setDecimals(2)
        self._adv_scale.setValue(1.0)
        self._adv_off_x = QSpinBox()
        self._adv_off_x.setRange(-300, 300)
        self._adv_off_y = QSpinBox()
        self._adv_off_y.setRange(-300, 300)
        self._adv_render_widgets = (
            self._adv_anchor_x, self._adv_anchor_y, self._adv_scale,
            self._adv_off_x, self._adv_off_y)
        for _w in self._adv_render_widgets:
            _w.setEnabled(False)
        self._adv_render_chk.toggled.connect(
            lambda on: [w.setEnabled(on) for w in self._adv_render_widgets])
        adv_grid.addWidget(self._adv_interval_chk, 0, 0)
        adv_grid.addWidget(self._adv_interval, 0, 1)
        adv_grid.addWidget(self._adv_rmbg, 1, 0)
        adv_grid.addWidget(self._adv_trim, 1, 1)
        adv_grid.addWidget(self._adv_keep, 2, 0, 1, 2)
        adv_grid.addWidget(self._adv_render_chk, 3, 0, 1, 2)
        adv_grid.addWidget(QLabel("锚点 X"), 4, 0)
        adv_grid.addWidget(self._adv_anchor_x, 4, 1)
        adv_grid.addWidget(QLabel("锚点 Y"), 5, 0)
        adv_grid.addWidget(self._adv_anchor_y, 5, 1)
        adv_grid.addWidget(QLabel("缩放倍率"), 6, 0)
        adv_grid.addWidget(self._adv_scale, 6, 1)
        adv_grid.addWidget(QLabel("偏移 X"), 7, 0)
        adv_grid.addWidget(self._adv_off_x, 7, 1)
        adv_grid.addWidget(QLabel("偏移 Y"), 8, 0)
        adv_grid.addWidget(self._adv_off_y, 8, 1)
        root.addWidget(adv)

        prev_row = QHBoxLayout()
        base_lay, self._prev_base = self._make_preview("形态 1（待机/动画）")
        full_lay, self._prev_full = self._make_preview("形态 2（若有）")
        prev_row.addLayout(base_lay)
        prev_row.addLayout(full_lay)
        root.addLayout(prev_row)

        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        root.addWidget(self._notes)

        btns = QHBoxLayout()
        self._ok = QPushButton("导入")
        self._cancel = QPushButton("取消")
        self._stop_btn = QPushButton("停止处理")  # P1-1：处理中可见，可取消工作线程
        self._stop_btn.clicked.connect(self._stop_worker)
        self._stop_btn.setVisible(False)
        self._ok.setDefault(True)
        self._ok.clicked.connect(self._do_import)
        self._cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(self._stop_btn)
        btns.addWidget(self._ok)
        btns.addWidget(self._cancel)
        root.addLayout(btns)

    @staticmethod
    def _make_preview(title):
        """构建「标题 + 预览框」子布局；返回 (QLayout, QLabel)。

        注意：不能用局部包装 QWidget 挂预览框——局部变量被 GC 会连带销毁
        子控件的 C++ 对象（libshiboken 已删除错误），必须返回布局交给调用方挂载。
        """
        lay = QVBoxLayout()
        cap = QLabel(title)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev = QLabel("未选择")
        prev.setFixedSize(240, 170)
        prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        lay.addWidget(cap)
        lay.addWidget(prev, 0, Qt.AlignmentFlag.AlignCenter)
        return lay, prev

    def _form_views(self):
        """按 _form_rows 重建形态行（≤8 行，重建成本可忽略）。"""
        for i in reversed(range(self._forms_box.count())):
            w = self._forms_box.itemAt(i).widget()
            if w is not None:
                w.deleteLater()
        for i, fr in enumerate(self._form_rows):
            row_w = QWidget()
            lay = QHBoxLayout(row_w)
            lay.setContentsMargins(0, 0, 0, 0)
            name_edit = QLineEdit(fr["name"])
            name_edit.setFixedWidth(90)
            name_edit.setMaxLength(12)  # 与库侧截断一致，超长不再静默丢失
            name_edit.setPlaceholderText("形态%d" % (i + 1))
            file_edit = QLineEdit(fr.get("src", ""))
            file_edit.setReadOnly(True)
            file_edit.setPlaceholderText("第 %d 形态图（必选）" % (i + 1))
            pick = QPushButton("浏览…")
            pick.clicked.connect(lambda _c=False, fi=i: self._pick_form(fi))
            rem = QPushButton("✕")
            rem.setFixedWidth(28)
            rem.clicked.connect(lambda _c=False, fi=i: self._del_form(fi))
            lay.addWidget(name_edit)
            lay.addWidget(file_edit, 1)
            lay.addWidget(pick)
            lay.addWidget(rem)
            self._forms_box.addWidget(row_w)
            fr["name_edit"] = name_edit
            fr["file_edit"] = file_edit
            fr["pick"] = pick
            fr["rem"] = rem
            pick.setEnabled(not self._busy_state)  # P1-1：处理中禁改形态，防快照与界面不一致
            rem.setEnabled(not self._busy_state)

    def _add_form(self, name=""):
        if len(self._form_rows) >= 8:
            _warn(self, "形态", "最多 8 个形态")
            return
        self._form_rows.append({"name": name or "形态%d" % (len(self._form_rows) + 1), "src": ""})
        self._form_views()

    def _del_form(self, i):
        if len(self._form_rows) <= 1:
            _warn(self, "形态", "至少保留 1 个形态")
            return
        self._form_rows.pop(i)
        self._form_views()

    def _pick_form(self, i):
        src, _f = QFileDialog.getOpenFileName(
            self, "选择第 %d 形态图" % (i + 1), "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        if i == 0:
            self._apply_static_form(src)  # 形态 0 与静态图同源：清帧 + 命名回退
            return
        pix, err = self._validate_image(src, "形态图")
        if pix is None:
            _warn(self, "形态图", err)
            return
        self._form_rows[i]["src"] = src
        self._form_views()
        # 预览：形态 0 → 左框；形态 1 → 右框；其余不重复预览
        if i == 0:
            self._prev_base.setText("")
            self._prev_base.setPixmap(pix.scaled(240, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        elif i == 1:
            self._prev_full.setText("")
            self._prev_full.setPixmap(pix.scaled(240, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        if not self._name_edit.text().strip() and i == 0:
            self._name_edit.setText(os.path.splitext(os.path.basename(src))[0])

    def _set_busy(self, on, text="处理中…"):
        """处理期间统一禁/启用导入、取消与全部素材选择按钮（防重入嵌套抽帧）；
        P1-1：处理中显示「停止处理」按钮，窗口本身保持可拖动。"""
        self._busy_state = bool(on)
        self._ok.setEnabled(not on)
        self._cancel.setEnabled(not on)
        self._ok.setText(text if on else "导入")
        self._stop_btn.setVisible(on)
        self._stop_btn.setEnabled(on)
        for b in self._mat_btns:
            b.setEnabled(not on)
        for fr in self._form_rows:  # P1-1：形态行按钮同步禁用，防处理中改形态列表
            for k in ("pick", "rem"):
                btn = fr.get(k)
                if btn is not None:
                    btn.setEnabled(not on)

    def _start_worker(self, task):
        """启动工作线程并接线进度/结果/失败信号（P1-1）。"""
        w = _ImportWorker(task, self)
        w.progress.connect(self._on_worker_progress)
        w.done_ok.connect(self._on_worker_done)
        w.failed.connect(self._on_worker_failed)
        w.finished.connect(w.deleteLater)
        self._worker = w
        self._worker_kind = task["kind"]
        w.start()

    def _stop_worker(self):
        """请求取消在途处理：管线周期检查后以「已取消处理」结束。"""
        if self._worker is not None:
            self._worker.cancel()
            self._stopping = True  # 吞掉迟到进度，防覆盖「正在停止……」文案
            self._stop_btn.setEnabled(False)
            self._notes.setText("正在停止……")

    def _shutdown_worker(self):
        """取消并等待在途工作线程收敛（≤3s；超时 terminate 兜底）。

        供 closeEvent 与应用 aboutToQuit 共用：任何销毁路径都不让
        QThread 在运行中被析构（Qt fatal）。等待前断开信号，避免收敛期间
        排队中的 failed 在稍后主线程恢复事件循环时弹出多余提示。"""
        w = self._worker
        if w is None:
            return
        w.cancel()
        for sig in (w.done_ok, w.failed, w.progress):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass  # 有意忽略：信号未连接/已断开时 disconnect 抛错（幂等断开）
        if not w.wait(3000):
            try:
                w.terminate()  # 极端兜底：管线卡死时强杀，防退出卡住
                w.wait(1000)
                w.deleteLater()  # terminate 不发射 finished，手动释放防泄漏
            except Exception:
                pass  # 有意忽略：极端兜底强杀失败不阻塞退出（已尽力收敛线程）
        self._worker = None
        self._worker_kind = None

    def _on_worker_progress(self, text):
        if self._stopping:
            return  # 停止请求中：迟到进度不再覆盖「正在停止……」文案
        self._notes.setText(text)
        self._frames_status.setText(text)

    def _on_worker_done(self, res):
        self._worker = None
        self._worker_kind = None
        self._stopping = False
        if "raws" in res:
            # 抽帧完成
            self._set_busy(False)
            self._set_frames(res["raws"],
                             "已抽 %d 帧（视频/GIF 均匀采样，导入时统一自动处理）" % len(res["raws"]),
                             name_hint=res.get("name_hint") or "", video=True)
            return
        # 导入处理完成：补名字（完成时从控件实时读取，保持旧行为）
        res["name"] = self._name_edit.text().strip() or getattr(self, "_name_hint", "") or "未命名"
        self._set_busy(False)
        self._result = res
        self.accept()

    def _on_worker_failed(self, err):
        kind = self._worker_kind
        self._worker = None
        self._worker_kind = None
        self._stopping = False
        self._set_busy(False)
        if kind == "import":
            self._cleanup_tmp()  # 线程已结束，此时清理临时目录安全
        if err == "已取消处理":
            self._notes.setText("已停止处理")  # 主动停止不是错误：静默恢复 UI，不弹错误框
            return
        _warn(self, "抽帧" if kind == "extract" else "导入角色", err)

    def _validate_image(self, src, title):
        """素材校验：存在/大小/可加载。返回 (pix, err)。"""
        try:
            if os.path.getsize(src) > self.MAX_BYTES:
                return None, "文件超过 10MB，无法导入"
            pix = QPixmap(src)
            if pix.isNull():
                return None, "无法加载该图片"
        except Exception:
            return None, "读取图片失败"
        return pix, None

    def _apply_static_form(self, src):
        """校验并写入形态 0 + 预览 + 清帧选择（形态行选择与多选单文件共用）。"""
        pix, err = self._validate_image(src, "形态图")
        if pix is None:
            _warn(self, "形态图", err)
            return False
        if not self._form_rows:
            self._add_form("常态")
        self._form_rows[0]["src"] = src
        self._form_views()
        self._frames_raw = []  # 换单图必须清掉旧帧，否则导入仍走旧帧（M1）
        self._frames_video = False
        self._name_hint = os.path.splitext(os.path.basename(src))[0]
        self._frames_status.setText("静态素材：也可选多张图片或视频/GIF 做帧动画")
        self._prev_base.setText("")
        self._prev_base.setPixmap(pix.scaled(
            240, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not self._name_edit.text().strip():
            self._name_edit.setText(os.path.splitext(os.path.basename(src))[0])
        return True

    def _set_frames(self, raws, note, name_hint=None, video=False):
        """设置帧序列：清空静态图，展示首帧预览与帧数状态。

        video=True 表示同源帧（视频/GIF 抽帧）→ 导入走并集画布保留平移。
        """
        self._frames_raw = list(raws)
        self._frames_video = bool(video)
        self._name_hint = name_hint or os.path.splitext(os.path.basename(raws[0]))[0]
        self._frames_status.setText(note)
        first = QPixmap(raws[0])
        self._prev_base.setText("")
        self._prev_base.setPixmap(first.scaled(
            240, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not self._name_edit.text().strip():
            self._name_edit.setText(name_hint or os.path.splitext(os.path.basename(raws[0]))[0])

    def _pick_multi(self):
        files, _f = QFileDialog.getOpenFileNames(
            self, "选择多张图片（按文件名排序作为帧序）", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if len(files) <= 1:
            if files:
                self._apply_static_form(files[0])  # 单文件：同套校验（L9）
            return
        _max_frames = int(pet_resources.FRAME_MAX or 24)  # P3-5+：上限用户可调
        if len(files) > _max_frames:
            _warn(self, "多帧动画", "最多 %d 帧（可在设置里调整），当前选了 %d 张"
                  % (_max_frames, len(files)))
            return
        files = sorted(files)
        self._set_frames(files, "已选 %d 帧（多选图片，按文件名排序）" % len(files),
                         name_hint=os.path.splitext(os.path.basename(files[0]))[0])

    def _pick_video(self):
        src, _f = QFileDialog.getOpenFileName(
            self, "选择视频/GIF 抽帧", "",
            "视频 (*.mp4 *.webm *.mov *.avi *.mkv *.m4v *.wmv);;GIF (*.gif)")
        if not src:
            return
        try:
            if os.path.getsize(src) > 200 * 1024 * 1024:
                _warn(self, "抽帧", "文件超过 200MB，太大啦")
                return
        except Exception:
            pass  # 有意忽略：体积检查失败不拦抽帧（200MB 只是软上限）
        # P1-1：每次抽帧前重建临时目录——重试成功后旧 raw_fXX.png 不残留
        if self._rawdir:
            shutil.rmtree(self._rawdir, ignore_errors=True)
        self._rawdir = tempfile.mkdtemp(prefix="role_raw_")
        self._set_busy(True, text="抽帧中…")
        self._frames_status.setText("正在抽帧……")
        # P1-1：抽帧移入工作线程，UI 不再阻塞（窗口可拖动、可「停止处理」）
        self._start_worker({
            "kind": "extract",
            "src": src,
            "out_dir": self._rawdir,
            "name_hint": os.path.splitext(os.path.basename(src))[0],
        })

    def _do_import(self):
        # 收集形态（名字从控件实时读）
        forms = []
        for i, fr in enumerate(self._form_rows):
            nm = (fr.get("name_edit") and fr["name_edit"].text().strip()) or ("形态%d" % (i + 1))
            src = fr.get("src", "")
            if i == 0 and self._frames_raw:
                src = ""  # 帧动画角色：形态 0 用首帧，不要求选图
            elif not src or not os.path.isfile(src):
                _warn(self, "导入角色", "第 %d 形态还没选图" % (i + 1))
                return
            forms.append((nm, src))
        if not forms:
            _warn(self, "导入角色", "请先添加形态并选图")
            return
        # P1-7：高级折叠区选项收集（缺省 = 现行为）
        options = {
            "remove_bg": self._adv_rmbg.isChecked(),
            "trim": self._adv_trim.isChecked(),
            "keep_source": self._adv_keep.isChecked(),
        }
        if self._adv_interval_chk.isChecked():
            options["interval_ms"] = self._adv_interval.value()
        if self._adv_render_chk.isChecked():
            options["render"] = {
                "anchor": {"x": self._adv_anchor_x.value(), "y": self._adv_anchor_y.value()},
                "scale": self._adv_scale.value(),
                "offset": {"x": self._adv_off_x.value(), "y": self._adv_off_y.value()},
            }
        # P1-1：图像管线（去背景/裁剪/缩放，可能数秒）移入工作线程
        self._set_busy(True)
        self._notes.setText("正在自动处理素材（去背景 / 裁剪 / 缩放）……")
        self._tmpdir = tempfile.mkdtemp(prefix="role_prep_")
        self._start_worker({
            "kind": "import",
            "forms": forms,
            "frames_raw": list(self._frames_raw),
            "frames_video": bool(self._frames_video),
            "tmpdir": self._tmpdir,
            "options": options,
        })

    def _cleanup_tmp(self):
        """只清理本次导入的处理临时目录（保留原始抽帧供失败重试）。"""
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def _cleanup(self):
        self._cleanup_tmp()
        if self._rawdir:
            shutil.rmtree(self._rawdir, ignore_errors=True)
            self._rawdir = None

    def closeEvent(self, event):
        if self._worker is not None:
            self._shutdown_worker()  # P1-1：关闭先收敛在途线程（防 QThread 运行中析构）
            self._set_busy(False)    # 取消处理即视为结束：允许本次关闭继续
        # P1-1：真正关闭时断开 aboutToQuit 连接——绑定方法被应用单例强引用，
        # 不断开会泄漏对话框（_tmpdir/_result 常驻、临时目录永不清理）
        try:
            QApplication.instance().aboutToQuit.disconnect(self._shutdown_worker)
        except Exception:
            pass  # 有意忽略：未连接/已断开时 disconnect 抛错（幂等断开）
        self._cleanup()
        super().closeEvent(event)

    def result_data(self):
        """accepted 后取处理结果：{"name","base","frames","forms","notes"} 或 None。

        P1-7 起 result 附加 "options"（interval_ms/render/keep_source）与
        "sources"（keep_source 时的原图路径）。
        """
        return self._result


class RoleEditDialog(QDialog):
    """P1-7 轻量角色编辑：改名 / 形态改名+调序 / 换图（重新处理，不换 id）/
    渲染参数（anchor/scale/offset）/ 帧间隔 / 正面图（front）/ 状态图（states）。

    确认时把新素材经管线处理后写入 roles/ 目录（新文件名），用
    RoleLibrary.update(rid, patch) 落盘索引；成功后清理不再被引用的旧文件。
    全部编辑只在当前库的该角色上进行，不新建 id。
    """

    def __init__(self, parent=None, lib=None, role_id=""):
        super().__init__(_qt_parent(parent))
        self._lib = lib
        self._role_id = str(role_id or "")
        self._role = (lib.get(self._role_id) if lib else None) or {}
        self._forms = copy.deepcopy(self._role.get("forms") or [])
        if not self._forms:
            self._forms = [{"name": "常态", "file": self._role.get("file", "")}]
        self._cur_idx = 0
        self._loading = False
        self._pending_images = {}    # form_idx -> src（换图，待重新处理）
        self._pending_front = {}     # form_idx -> src|None（None=清除）
        self._pending_states = {}    # (form_idx, state) -> src|None（None=删除）
        self._touched_name = set()
        self._touched_render = set()
        self._touched_interval = set()
        self._staged = []            # 本次写入 roles/ 的新文件名（失败/取消时清理）
        self._tmpdir = None

        self.setWindowTitle("编辑角色「%s」" % self._role.get("name", ""))
        self.setStyleSheet(DIALOG_QSS)
        self.resize(600, 540)

        root = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("角色名"))
        self._name_edit = QLineEdit(self._role.get("name", ""))
        name_row.addWidget(self._name_edit, 1)
        root.addLayout(name_row)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("形态（选中后编辑；上移/下移调整喂食顺序）"))
        self._form_list = QListWidget()
        self._form_list.setMinimumWidth(190)
        self._form_list.currentRowChanged.connect(self._on_form_selected)
        left.addWidget(self._form_list, 1)
        reorder = QHBoxLayout()
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(lambda: self._move_form(-1))
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(lambda: self._move_form(1))
        reorder.addWidget(up_btn)
        reorder.addWidget(down_btn)
        reorder.addStretch(1)
        left.addLayout(reorder)
        body.addLayout(left)

        right = QVBoxLayout()
        self._preview = QLabel("预览")
        self._preview.setFixedSize(180, 130)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignCenter)

        fn_row = QHBoxLayout()
        fn_row.addWidget(QLabel("形态名"))
        self._form_name = QLineEdit()
        self._form_name.setMaxLength(12)
        self._form_name.textChanged.connect(lambda _t: self._mark("name"))
        fn_row.addWidget(self._form_name, 1)
        right.addLayout(fn_row)

        img_row = QHBoxLayout()
        self._img_btn = QPushButton("换图（重新处理）…")
        self._img_btn.clicked.connect(self._pick_image)
        self._front_btn = QPushButton("设正面图…")
        self._front_btn.clicked.connect(self._pick_front)
        self._front_clear = QPushButton("清正面")
        self._front_clear.clicked.connect(self._clear_front)
        img_row.addWidget(self._img_btn)
        img_row.addWidget(self._front_btn)
        img_row.addWidget(self._front_clear)
        right.addLayout(img_row)
        self._img_status = QLabel("")
        self._img_status.setWordWrap(True)
        right.addWidget(self._img_status)

        render_box = QGroupBox("渲染参数（解决多形态切换跳变；默认 = 原行为）")
        rg = QGridLayout(render_box)
        self._anchor_x = QDoubleSpinBox()
        self._anchor_x.setRange(0.0, 1.0)
        self._anchor_x.setSingleStep(0.05)
        self._anchor_x.setDecimals(2)
        self._anchor_y = QDoubleSpinBox()
        self._anchor_y.setRange(0.0, 1.0)
        self._anchor_y.setSingleStep(0.05)
        self._anchor_y.setDecimals(2)
        self._scale = QDoubleSpinBox()
        self._scale.setRange(0.1, 4.0)
        self._scale.setSingleStep(0.05)
        self._scale.setDecimals(2)
        self._off_x = QSpinBox()
        self._off_x.setRange(-300, 300)
        self._off_y = QSpinBox()
        self._off_y.setRange(-300, 300)
        self._interval = QSpinBox()
        self._interval.setRange(0, 10000)
        self._interval.setSpecialValueText("默认")
        self._interval.setSuffix(" ms/帧")
        for _w in (self._anchor_x, self._anchor_y, self._scale,
                   self._off_x, self._off_y):
            _w.valueChanged.connect(lambda _v, _w=_w: self._mark("render"))
        self._interval.valueChanged.connect(lambda _v: self._mark("interval"))
        rg.addWidget(QLabel("锚点 X"), 0, 0)
        rg.addWidget(self._anchor_x, 0, 1)
        rg.addWidget(QLabel("锚点 Y"), 1, 0)
        rg.addWidget(self._anchor_y, 1, 1)
        rg.addWidget(QLabel("缩放倍率"), 2, 0)
        rg.addWidget(self._scale, 2, 1)
        rg.addWidget(QLabel("偏移 X"), 3, 0)
        rg.addWidget(self._off_x, 3, 1)
        rg.addWidget(QLabel("偏移 Y"), 4, 0)
        rg.addWidget(self._off_y, 4, 1)
        rg.addWidget(QLabel("动画帧间隔"), 5, 0)
        rg.addWidget(self._interval, 5, 1)
        right.addWidget(render_box)

        st_row = QHBoxLayout()
        st_row.addWidget(QLabel("状态图"))
        self._state_combo = QComboBox()
        self._state_combo.addItems(list(pet_resources.STATE_NAMES))
        st_pick = QPushButton("选图…")
        st_pick.clicked.connect(self._pick_state)
        st_clear = QPushButton("清除")
        st_clear.clicked.connect(self._clear_state)
        st_row.addWidget(self._state_combo, 1)
        st_row.addWidget(st_pick)
        st_row.addWidget(st_clear)
        right.addLayout(st_row)
        self._states_status = QLabel("")
        self._states_status.setWordWrap(True)
        right.addWidget(self._states_status)

        # v2.0.1：自定义动作（当前形态）：命名帧动作 + 程序化合成动作
        act_head = QHBoxLayout()
        act_head.addWidget(QLabel("自定义动作"))
        self._act_list = QListWidget()
        self._act_list.setMaximumHeight(80)
        act_head.addWidget(self._act_list, 1)
        act_btns = QVBoxLayout()
        b_add_f = QPushButton("＋帧动作…")
        b_add_f.clicked.connect(self._add_frame_action)
        b_add_p = QPushButton("＋合成…")
        b_add_p.clicked.connect(self._add_proc_action)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._del_action)
        act_btns.addWidget(b_add_f)
        act_btns.addWidget(b_add_p)
        act_btns.addWidget(b_del)
        act_head.addLayout(act_btns)
        right.addLayout(act_head)

        body.addLayout(right, 1)
        root.addLayout(body)

        btns = QHBoxLayout()
        self._ok = QPushButton("保存")
        self._cancel = QPushButton("取消")
        self._ok.setDefault(True)
        self._ok.clicked.connect(self._save)
        self._cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(self._ok)
        btns.addWidget(self._cancel)
        root.addLayout(btns)

        self._refresh_form_list()

    # ---------- 表单同步 ----------
    def _mark(self, group):
        """用户改动标记：仅被触碰过的字段组写回索引（未触碰保持原结构）。"""
        if self._loading or self._cur_idx is None:
            return
        getattr(self, "_touched_%s" % group).add(self._cur_idx)

    def _sync_current(self):
        """把控件值写回 self._forms[self._cur_idx]（切换形态 / 保存前调用）。"""
        if self._cur_idx is None or self._loading:
            return
        fm = self._forms[self._cur_idx]
        fm["name"] = self._form_name.text().strip()[:12] or ("形态%d" % (self._cur_idx + 1))
        if self._cur_idx in self._touched_render:
            fm["anchor"] = {"x": round(self._anchor_x.value(), 2), "y": round(self._anchor_y.value(), 2)}
            fm["scale"] = round(self._scale.value(), 2)
            fm["offset"] = {"x": self._off_x.value(), "y": self._off_y.value()}
        if self._cur_idx in self._touched_interval:
            v = self._interval.value()
            if v > 0:
                fm["anim_interval_ms"] = v
            else:
                fm.pop("anim_interval_ms", None)

    def _refresh_form_list(self):
        self._loading = True
        try:
            self._form_list.clear()
            for i, fm in enumerate(self._forms):
                self._form_list.addItem("%d. %s" % (i + 1, fm.get("name") or "形态%d" % (i + 1)))
            self._cur_idx = 0
            self._form_list.setCurrentRow(0)
            self._load_form(0)
        finally:
            self._loading = False

    def _on_form_selected(self, row):
        if self._loading:
            return
        self._sync_current()
        self._cur_idx = row if row is not None and 0 <= row < len(self._forms) else None
        if self._cur_idx is not None:
            self._load_form(self._cur_idx)

    def _load_form(self, idx):
        fm = self._forms[idx]
        self._loading = True
        try:
            self._form_name.setText(fm.get("name") or "")
            anchor = fm.get("anchor") or {"x": 0.5, "y": 0.5}
            self._anchor_x.setValue(float(anchor.get("x", 0.5)))
            self._anchor_y.setValue(float(anchor.get("y", 0.5)))
            self._scale.setValue(float(fm.get("scale") or 1.0))
            off = fm.get("offset") or {"x": 0, "y": 0}
            self._off_x.setValue(int(off.get("x", 0)))
            self._off_y.setValue(int(off.get("y", 0)))
            aiv = fm.get("anim_interval_ms")
            self._interval.setValue(int(aiv) if isinstance(aiv, (int, float)) and aiv > 0 else 0)
        finally:
            self._loading = False
        self._update_statuses()
        self._refresh_act_list()  # v2.0.1：切形态刷新自定义动作列表

    def _update_statuses(self):
        idx = self._cur_idx
        if idx is None:
            return
        fm = self._forms[idx]
        pending_img = self._pending_images.get(idx)
        pending_front = self._pending_front.get(idx)
        lines = []
        if pending_img:
            lines.append("待处理换图：%s" % os.path.basename(pending_img))
        if pending_front is not None:
            lines.append("待处理正面图：%s" % (os.path.basename(pending_front) if pending_front else "清除"))
        elif fm.get("front"):
            lines.append("已有正面图")
        st_lines = []
        for st in pet_resources.STATE_NAMES:
            if (idx, st) in self._pending_states:
                st_lines.append("%s(待%s)" % (st, "处理" if self._pending_states[(idx, st)] else "清除"))
            elif (fm.get("states") or {}).get(st):
                st_lines.append(st)
        self._img_status.setText("；".join(lines) if lines else "未选择新素材")
        self._states_status.setText(("状态图：%s" % "、".join(st_lines)) if st_lines else "状态图：未配置（走程序化表情）")
        self._preview.setText("")
        p = self._lib.resolve(fm.get("file") or "") if self._lib else ""
        if p and os.path.isfile(p):
            pix = QPixmap(p)
            if not pix.isNull():
                self._preview.setPixmap(pix.scaled(
                    180, 130, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                return
        self._preview.setText("无法预览")

    # ---------- 动作 ----------
    def _move_form(self, delta):
        idx = self._cur_idx
        if idx is None:
            return
        j = idx + delta
        if not (0 <= j < len(self._forms)):
            return
        self._sync_current()
        self._forms[idx], self._forms[j] = self._forms[j], self._forms[idx]
        # 待处理映射与触碰标记同步换序
        for table in (self._pending_images, self._pending_front):
            a, b = table.get(idx), table.get(j)
            table.pop(idx, None)
            table.pop(j, None)
            if b is not None:
                table[idx] = b
            if a is not None:
                table[j] = a
        new_states = {}
        for (fi, st), v in self._pending_states.items():
            fi2 = j if fi == idx else (idx if fi == j else fi)
            new_states[(fi2, st)] = v
        self._pending_states = new_states
        for touched in (self._touched_name, self._touched_render, self._touched_interval):
            if idx in touched or j in touched:
                new_t = set()
                for fi in touched:
                    new_t.add(j if fi == idx else (idx if fi == j else fi))
                touched.clear()
                touched.update(new_t)
        # 重建列表期间屏蔽 currentRowChanged，避免把旧控件值写回已换序的形态
        self._loading = True
        try:
            self._form_list.clear()
            for i, fm in enumerate(self._forms):
                self._form_list.addItem("%d. %s" % (i + 1, fm.get("name") or "形态%d" % (i + 1)))
            self._cur_idx = j
            self._form_list.setCurrentRow(j)
        finally:
            self._loading = False
        self._load_form(j)

    def _pick_image(self):
        if self._cur_idx is None:
            return
        src, _f = QFileDialog.getOpenFileName(
            self, "选择新的形态图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        pix, err = self._validate_image(src)
        if pix is None:
            _warn(self, "换图", err)
            return
        self._pending_images[self._cur_idx] = src
        self._update_statuses()

    def _pick_front(self):
        if self._cur_idx is None:
            return
        src, _f = QFileDialog.getOpenFileName(
            self, "选择正面图（缺省与侧面同图）", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        pix, err = self._validate_image(src)
        if pix is None:
            _warn(self, "正面图", err)
            return
        self._pending_front[self._cur_idx] = src
        self._update_statuses()

    def _clear_front(self):
        if self._cur_idx is None:
            return
        self._pending_front[self._cur_idx] = None
        self._update_statuses()

    def _pick_state(self):
        if self._cur_idx is None:
            return
        st = self._state_combo.currentText()
        src, _f = QFileDialog.getOpenFileName(
            self, "选择状态图「%s」（未配置走程序化表情）" % st, "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        pix, err = self._validate_image(src)
        if pix is None:
            _warn(self, "状态图", err)
            return
        self._pending_states[(self._cur_idx, st)] = src
        self._update_statuses()

    def _clear_state(self):
        if self._cur_idx is None:
            return
        st = self._state_combo.currentText()
        self._pending_states[(self._cur_idx, st)] = None
        self._update_statuses()

    def _validate_image(self, src):
        try:
            if os.path.getsize(src) > 10 * 1024 * 1024:
                return None, "文件超过 10MB，无法使用"
            pix = QPixmap(src)
            if pix.isNull():
                return None, "无法加载该图片"
        except Exception:
            return None, "读取图片失败"
        return pix, None

    def _process_pending(self):
        """把待处理的换图/正面图/状态图跑默认管线（去背景+裁剪），返回 (ok, err)。"""
        if not (self._pending_images or any(v for v in self._pending_front.values())
                or any(v for v in self._pending_states.values())):
            return True, ""
        self._tmpdir = tempfile.mkdtemp(prefix="role_edit_")
        self._process_list = []  # [(kind, idx|(idx,state), tmp_path)]
        try:
            n = 0
            for idx, src in self._pending_images.items():
                out = os.path.join(self._tmpdir, "img%d.png" % n)
                okp, notesp = _prepare_role_png(src, out)
                if not okp:
                    return False, "形态 %d 换图处理失败：%s" % (idx + 1, notesp)
                self._process_list.append(("image", idx, out))
                n += 1
            for idx, src in self._pending_front.items():
                if not src:
                    continue
                out = os.path.join(self._tmpdir, "img%d.png" % n)
                okp, notesp = _prepare_role_png(src, out)
                if not okp:
                    return False, "形态 %d 正面图处理失败：%s" % (idx + 1, notesp)
                self._process_list.append(("front", idx, out))
                n += 1
            for (idx, st), src in self._pending_states.items():
                if not src:
                    continue
                out = os.path.join(self._tmpdir, "img%d.png" % n)
                okp, notesp = _prepare_role_png(src, out)
                if not okp:
                    return False, "形态 %d 状态图「%s」处理失败：%s" % (idx + 1, st, notesp)
                self._process_list.append(("state", (idx, st), out))
                n += 1
            return True, ""
        except Exception as e:
            return False, "处理失败：%s" % e

    def _save(self):
        if self._lib is None:
            return
        self._sync_current()
        okp, errp = self._process_pending()
        if not okp:
            _warn(self, "编辑角色", errp)
            return
        name = self._name_edit.text().strip()
        if not name:
            _warn(self, "编辑角色", "角色名不能为空")
            return
        patch_forms = copy.deepcopy(self._forms)
        just_staged = []  # 本次保存尝试新暂存的文件（失败只回收这些，不动先前会话的暂存）
        # 处理结果写入 roles/ 目录（新文件名，不换 id）
        try:
            for kind, key, tmp_path in getattr(self, "_process_list", []):
                staged = self._lib.stage_file(tmp_path)
                if staged is None:
                    raise RuntimeError("写入角色目录失败")
                self._staged.append(staged)
                just_staged.append(staged)
                if kind == "image":
                    patch_forms[key]["file"] = staged
                elif kind == "front":
                    patch_forms[key]["front"] = staged
                else:
                    idx, st = key
                    patch_forms[idx].setdefault("states", {})[st] = staged
            for idx, src in self._pending_front.items():
                if src is None:
                    patch_forms[idx].pop("front", None)
            for (idx, st), src in self._pending_states.items():
                if src is None:
                    patch_forms[idx].setdefault("states", {}).pop(st, None)
        except Exception:
            for s in just_staged:
                p = self._lib.resolve(s)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：本次写入残留清理尽力而为
                if s in self._staged:
                    self._staged.remove(s)
            _warn(self, "编辑角色", "素材写入失败")
            return
        # M1 修复：旧引用集合用库的 _role_paths 全量收集（含 animations 帧），
        # 避免换图后误删仍被 animations.idle 引用的首帧（帧动画静默丢失）
        old_refs = set(self._lib._role_paths(self._role))
        ok, err = self._lib.update(self._role_id, {"name": name, "forms": patch_forms})
        if not ok:
            for s in just_staged:
                p = self._lib.resolve(s)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：本次写入残留清理尽力而为
                if s in self._staged:
                    self._staged.remove(s)
            _warn(self, "编辑角色", err or "保存失败")
            return
        # 成功：清理不再被引用的旧素材文件
        new_refs = set(self._lib._role_paths(self._lib.get(self._role_id)))
        for f in sorted(old_refs - new_refs):
            if f:
                p = self._lib.resolve(f)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：旧文件清理尽力而为（索引已更新，残留仅占空间）
        # v2.0.1：本次暂存但最终未被引用的新文件（如刚添加又删除的动作帧）同样回收，
        # 否则 roles/ 目录会残留孤儿帧文件
        for fn in list(self._staged):
            p = self._lib.resolve(fn)
            if os.path.abspath(p) not in new_refs:
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：暂存文件清理尽力而为（不阻塞保存）
                self._staged.remove(fn)
        self.accept()

    def _cleanup_staged(self):
        """删除本次写入但未提交（或提交失败）的新文件。"""
        for fn in self._staged:
            p = self._lib.resolve(fn)
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：孤儿文件清理尽力而为
        self._staged = []

    def _cleanup(self):
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    # ---------- v2.0.1：自定义动作（当前形态） ----------
    def _refresh_act_list(self):
        """列出当前形态的自定义动作（帧动作 + 程序化合成）。"""
        self._act_list.clear()
        if self._cur_idx is None or self._loading:
            return
        fm = self._forms[self._cur_idx]
        for act in (fm.get("animations") or {}):
            if act not in pet_resources.ANIM_ACTIONS:
                self._act_list.addItem("%s（帧）" % act)
        for name in sorted(fm.get("procs") or {}):
            self._act_list.addItem("%s（合成）" % name)

    def _add_frame_action(self):
        """多选图片 → 统一画布管线 → 立即入角色目录（staged，取消时回收）。"""
        files, _f = QFileDialog.getOpenFileNames(
            self, "选择动作帧图片（2 张起）", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if len(files) < 2:
            _warn(self, "帧动作", "帧动作至少 2 张图")
            return
        max_frames = int(pet_resources.FRAME_MAX)
        if len(files) > max_frames:
            _warn(self, "帧动作", "最多 %d 帧（可在设置里调整）" % max_frames)
            return
        name, ok = QInputDialog.getText(self, "帧动作", "动作名（英文字母开头，字母/数字/下划线 ≤24 字符）")
        name = (name or "").strip()
        if not ok or not name:
            return
        if not pet_resources.CUSTOM_ACTION_RE.match(name):
            _warn(self, "帧动作", "动作名不合法（英文字母开头，字母/数字/下划线）")
            return
        if name in pet_resources.ANIM_ACTIONS or name in pet_resources.ACTION_RESERVED:
            _warn(self, "帧动作", "动作名与内建动作/保留名重名（%s），换一个名字"
                  % "、".join(pet_resources.ANIM_ACTIONS + pet_resources.ACTION_RESERVED))
            return
        idx = self._cur_idx
        if idx is None or self._lib is None:
            return
        if name in (self._forms[idx].get("procs") or {}):
            _warn(self, "帧动作", "该形态已有同名合成动作，帧动作会被遮蔽，换一个名字")
            return
        tmpdir = tempfile.mkdtemp(prefix="role_act_")
        staged = []
        try:
            outs, notes = _prepare_role_frames(files, tmpdir, same_size=False)
            if outs is None:
                _warn(self, "帧动作", "处理失败：%s" % (notes,))
                return
            for o in outs:
                s = self._lib.stage_file(o)
                if s is None:
                    raise RuntimeError("写入角色目录失败")
                staged.append(s)
                self._staged.append(s)
            self._forms[idx].setdefault("animations", {})[name] = staged
            self._refresh_act_list()
        except Exception as e:
            # 只回收本次尝试暂存的文件——_cleanup_staged() 会连带删掉同会话先前
            # 已成功添加的动作帧，保存后动作静默变空
            for s in staged:
                p = self._lib.resolve(s)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：本次导入残留清理尽力而为
                if s in self._staged:
                    self._staged.remove(s)
            _warn(self, "帧动作", "导入失败：%s" % e)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _add_proc_action(self):
        """添加程序化合成动作（呼吸/摇摆/点头，用角色自身贴图合成，无需素材）。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("程序化合成动作")
        dlg.setStyleSheet(DIALOG_QSS)
        lay = QVBoxLayout(dlg)
        nm = QLineEdit()
        nm.setPlaceholderText("动作名（英文/数字/下划线）")
        lay.addWidget(nm)
        kind_box = QComboBox()
        kind_box.addItem("呼吸（整体轻微缩放）", "breathe")
        kind_box.addItem("摇摆（左右晃动）", "sway")
        kind_box.addItem("点头（上下位移）", "nod")
        lay.addWidget(kind_box)
        amp = QDoubleSpinBox()
        amp.setDecimals(3)
        lay.addWidget(amp)
        period = QSpinBox()
        period.setRange(200, 10000)
        lay.addWidget(period)

        def _apply_proc_defaults():
            # 幅度/周期默认与钳制范围随 kind 走单一来源（DEFAULT_PROC_PARAMS/PROC_AMP_BOUNDS）
            k = kind_box.currentData()
            lo, hi = pet_resources.PROC_AMP_BOUNDS.get(k, (0.001, 1.0))
            d = pet_resources.DEFAULT_PROC_PARAMS[k]
            amp.setRange(lo, hi)
            amp.setValue(float(d["amp"]))
            period.setValue(int(d["period_ms"]))
        kind_box.currentIndexChanged.connect(lambda _i: _apply_proc_defaults())
        _apply_proc_defaults()
        ok = QPushButton("添加")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = nm.text().strip()
        if not pet_resources.CUSTOM_ACTION_RE.match(name):
            _warn(self, "合成动作", "动作名不合法（英文字母开头，字母/数字/下划线）")
            return
        if name in pet_resources.ANIM_ACTIONS or name in pet_resources.ACTION_RESERVED:
            _warn(self, "合成动作", "动作名与内建动作/保留名重名（%s），会无法从菜单播放，换一个名字"
                  % "、".join(pet_resources.ANIM_ACTIONS + pet_resources.ACTION_RESERVED))
            return
        if self._cur_idx is None or self._lib is None:
            return
        if name in (self._forms[self._cur_idx].get("animations") or {}):
            _warn(self, "合成动作", "该形态已有同名帧动作，合成动作会被遮蔽，换一个名字")
            return
        self._forms[self._cur_idx].setdefault("procs", {})[name] = {
            "kind": kind_box.currentData(), "amp": amp.value(), "period_ms": period.value()}
        self._refresh_act_list()

    def _del_action(self):
        """删除选中的自定义动作（按条目后缀只删对应类型：帧/合成同名互不影响）。"""
        item = self._act_list.currentItem()
        if item is None or self._cur_idx is None:
            return
        text = item.text()
        fm = self._forms[self._cur_idx]
        removed = False
        if text.endswith("（帧）"):
            fm.setdefault("animations", {}).pop(text[:-len("（帧）")], None)
            removed = True
        elif text.endswith("（合成）"):
            fm.setdefault("procs", {}).pop(text[:-len("（合成）")], None)
            removed = True
        if removed:
            self._refresh_act_list()

    def closeEvent(self, event):
        self._cleanup()
        if self.result() != QDialog.DialogCode.Accepted:
            self._cleanup_staged()  # v2.0.1：取消/关闭时回收未提交的新文件
        super().closeEvent(event)


# ---------------- a) 角色面板 ----------------
class AISettingsDialog(QDialog):
    """AI 接口/模型/人设/回复长度设置（P1-10，OpenAI 兼容，支持本地 Ollama）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("AI 设置")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(560, 500)
        cfg = _get(parent, "cfg") or {}
        root = QVBoxLayout(self)
        root.addWidget(QLabel("接口地址（OpenAI 兼容；留空 = DeepSeek 官方）"))
        self._base = QLineEdit(cfg.get("ai_base_url", ""))
        self._base.setPlaceholderText("https://api.deepseek.com")
        root.addWidget(self._base)
        root.addWidget(QLabel("模型名（本地 Ollama 可填 qwen2.5 之类）"))
        self._model = QLineEdit(cfg.get("ai_model", "deepseek-chat"))
        root.addWidget(self._model)
        root.addWidget(QLabel("人设预设（选「自定义」可完全自己写）"))
        self._persona = QComboBox()
        self._persona.addItem("内置大肥鱼（又娇又赖，默认）", "default")
        self._persona.addItem("啥子蛇（毒舌腹黑「本专员」）", "sheshe")
        self._persona.addItem("傲娇系（嘴硬心软）", "tsundere")
        self._persona.addItem("自定义（自己写人设）", "custom")
        root.addWidget(self._persona)
        self._persona.currentIndexChanged.connect(self._on_persona_changed)
        cur_persona = str(cfg.get("ai_persona", "default") or "default")
        _pi = self._persona.findData(cur_persona)
        if _pi >= 0:
            self._persona.setCurrentIndex(_pi)
        root.addWidget(QLabel("自定义人设（选「自定义」预设后生效；留空 = 内置大肥鱼人设）"))
        self._prompt = QPlainTextEdit()
        self._prompt.setPlainText(cfg.get("ai_system_prompt", ""))
        self._prompt.setPlaceholderText("例：你是一只高冷的猫猫桌宠，只对绳匠一个人温柔……")
        root.addWidget(self._prompt, 1)
        self._on_persona_changed(self._persona.currentIndex())
        row = QHBoxLayout()
        row.addWidget(QLabel("回复字数上限"))
        self._reply = QSpinBox()
        self._reply.setRange(4, 50)
        self._reply.setValue(int(cfg.get("ai_reply_len", 25) or 25))
        row.addWidget(self._reply)
        row.addWidget(QLabel("max_tokens"))
        self._tokens = QSpinBox()
        self._tokens.setRange(16, 512)
        self._tokens.setValue(int(cfg.get("ai_max_tokens", 60) or 60))
        row.addWidget(self._tokens)
        row.addStretch(1)
        root.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _on_persona_changed(self, _idx):
        """预设选择：仅「自定义」时启用人设编辑框。"""
        self._prompt.setEnabled(self._persona.currentData() == "custom")

    def _save(self):
        data = {
            "ai_base_url": self._base.text().strip().rstrip("/"),
            "ai_model": self._model.text().strip() or "deepseek-chat",
            "ai_persona": self._persona.currentData() or "default",
            "ai_system_prompt": self._prompt.toPlainText().strip(),
            "ai_reply_len": self._reply.value(),
            "ai_max_tokens": self._tokens.value(),
        }
        _call(self._pet, "apply_ai_settings", data)
        self.accept()


class RolePanel(QWidget):
    """角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。"""

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
        self._btn_edit = QPushButton("编辑…")
        self._btn_del = QPushButton("删除")
        self._btn_default = QPushButton("恢复默认")
        for b in (self._btn_import, self._btn_set, self._btn_edit,
                  self._btn_del, self._btn_default):
            btns.addWidget(b)
        self._btn_import.clicked.connect(self._import)
        self._btn_set.clicked.connect(self._set_active)
        self._btn_edit.clicked.connect(self._edit)
        self._btn_del.clicked.connect(self._delete)
        self._btn_default.clicked.connect(self._reset_default)
        left.addLayout(btns)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        cap1 = QLabel("形态 1")
        cap1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(cap1)
        self._preview = QLabel("预览")
        self._preview.setFixedSize(200, 200)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview)
        cap2 = QLabel("形态 2")
        cap2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(cap2)
        self._preview_full = QLabel("预览")
        self._preview_full.setFixedSize(200, 200)
        self._preview_full.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_full.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview_full)
        self._meta = QLabel("")
        self._meta.setWordWrap(True)
        right.addWidget(self._meta)
        right.addStretch(1)
        root.addLayout(right)

        self._refresh()

    # ---------- 内部 ----------
    def _refresh(self):
        self._list.clear()
        if self._lib is None:
            self._list.addItem("角色库不可用")
            for b in (self._btn_import, self._btn_set, self._btn_edit,
                      self._btn_del, self._btn_default):
                b.setEnabled(False)
            self._info.setText("当前：默认角色")
            self._preview.setText("角色库不可用")
            self._preview.setPixmap(QPixmap())
            self._preview_full.setText("角色库不可用")
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        for b in (self._btn_import, self._btn_set, self._btn_edit,
                  self._btn_del, self._btn_default):
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
                    pass  # 有意忽略：尺寸探测失败显示 ?x?（预览信息尽力而为）
            mark = " [当前]" if role["id"] == active else ""
            nf = len(role.get("forms") or [])
            form_text = ("%d形态" % nf) if nf >= 2 else "单形态"
            if role.get("frames"):
                form_text += "+%d帧" % len(role["frames"])
            it = QListWidgetItem("%s  %s  %s  %s%s" % (role["name"], size_text, form_text, role.get("added", ""), mark))
            it.setData(Qt.ItemDataRole.UserRole, role["id"])
            self._list.addItem(it)
            if role["id"] == active:
                active_name = role["name"]
                self._list.setCurrentItem(it)
        self._info.setText(("当前：%s" % active_name) if active else "当前：默认角色")
        if self._list.count() == 0:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("暂无角色\n点「导入角色…」加一个")
            self._preview_full.setPixmap(QPixmap())
            self._preview_full.setText("暂无角色")
            self._meta.setText("")

    def _on_select(self, item, _prev):
        if item is None or self._lib is None:
            self._preview.setPixmap(QPixmap())
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        p = self._lib.path_for(rid)
        if not p:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("文件缺失，无法预览")
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        pix = QPixmap(p)
        if pix.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText("无法预览")
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        scaled = pix.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        self._preview.setText("")
        self._preview.setPixmap(scaled)
        fp = self._lib.path_for_full(rid)
        if fp:
            try:
                pf = QPixmap(fp)
                if not pf.isNull():
                    self._preview_full.setText("")
                    self._preview_full.setPixmap(pf.scaled(
                        200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    self._meta.setText(self._meta_text(rid, pix))
                else:
                    self._preview_full.setPixmap(QPixmap())
                    self._preview_full.setText("形态 2 无法预览")
                    self._meta.setText(self._meta_text(rid, pix))
            except Exception:
                self._preview_full.setPixmap(QPixmap())
                self._preview_full.setText("吃饱图无法预览")
        else:
            self._preview_full.setPixmap(QPixmap())
            self._preview_full.setText("单形态：无第二形态")
            self._meta.setText(self._meta_text(rid, pix))

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    def _meta_text(self, rid, pix):
        """预览元信息：尺寸 + 形态数（≥3 形态注明仅预览前 2 个）。"""
        nf = len(self._lib.form_metas(rid)) if self._lib else 0
        if nf <= 1:
            return "%dx%d · 单形态" % (pix.width(), pix.height())
        if nf == 2:
            return "%dx%d · 双形态" % (pix.width(), pix.height())
        return "%dx%d · %d形态（仅预览前 2 个）" % (pix.width(), pix.height(), nf)

    # ---------- 动作 ----------
    def _import(self):
        """导入角色：弹出向导（多形态自定 + 素材自动处理）→ 落库 → 切换。"""
        if self._lib is None:
            return
        dlg = RoleImportDialog(self._parent_widget())
        try:
            if modal(dlg) != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            forms_src = data.get("forms") or None
            opts = data.get("options") or {}
            role, err = self._lib.import_processed(
                data["base"], None, data["name"],
                frames_src=data.get("frames") or None,
                forms_src=forms_src,
                interval_ms=opts.get("interval_ms"),
                render=opts.get("render"),
                keep_source=bool(opts.get("keep_source")),
                source_files=data.get("sources"),
            )
            if role is None:
                _warn(self._parent_widget(), "导入角色", err or "导入失败")
                return
            _call(self._pet, "apply_role", role["id"])  # 导入即切换为新角色
            self._refresh()
            n_forms = len(forms_src or [])
            if data.get("frames"):
                tip = ("帧动画角色：待机循环播放 %d 帧；喂食在 %d 个形态间切换，12 秒后回第一形态。"
                       % (len(data["frames"]), max(1, n_forms)))
            elif n_forms >= 2:
                tip = ("%d 形态角色：喂食依次切换形态，12 秒后回「%s」。"
                       % (n_forms, forms_src[0][0]))
            else:
                tip = "单形态角色：喂食后仍是同一形象（可重新导入添加更多形态）。"
            _info(self._parent_widget(), "导入角色",
                  "导入成功！\n\n· %s\n\n%s" % ("\n· ".join(data["notes"]), tip))
        finally:
            dlg._cleanup()  # 任何路径都清理向导临时文件（含取消/失败）

    def _edit(self):
        """P1-7：编辑选中角色（改名/换图/调序/渲染参数/状态图，不换 id）。"""
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "编辑角色", "先在列表里选中一个角色")
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        dlg = RoleEditDialog(self._parent_widget(), self._lib, rid)
        try:
            if modal(dlg) != QDialog.DialogCode.Accepted:
                return
            role = self._lib.get(rid) or {}
            self._refresh()
            # 编辑的是当前角色 → 立即重载贴图（换图/调参实时生效）
            if self._lib.active_id() == rid:
                _call(self._pet, "apply_role", rid)
            _info(self._parent_widget(), "编辑角色",
                  "已保存「%s」的修改。" % role.get("name", ""))
        finally:
            dlg._cleanup()  # 任何路径都清理编辑临时目录

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
                label = f["name"] + ("（仅试听）" if str(f.get("ext", "")).lower() != ".wav" else "")
                cb.addItem(label)
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
            pass  # 有意忽略：样式配置异常回退默认（防御性）

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


# ---------------- P0-1：PetWindow 对话框入口函数（迁移自桌宠.py） ----------------
# 全部鸭子类型访问 pet（show_bubble / cfg / role_lib / apply_role），不 import 桌宠。
def open_resource_manager(pet, tab=0):
    try:
        dlg = ResourceManagerDialog(pet, tab)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("resource_manager failed: %r" % (e,))
        pet.show_bubble("资源管理窗口打不开……")


def open_ledger(pet):
    try:
        dlg = LedgerDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("ledger dialog failed: %r" % (e,))


def open_bubble_style(pet):
    try:
        dlg = BubbleStyleDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("bubble_style dialog failed: %r" % (e,))


def open_lines(pet):
    try:
        dlg = LinesDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("lines dialog failed: %r" % (e,))


def open_ai_settings(pet):
    try:
        dlg = AISettingsDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("ai settings dialog failed: %r" % (e,))


class PhysicsDialog(QDialog):
    """P1-手感：甩抛物理参数设置（重力/反弹/地面摩擦/顶边反弹/力度增益）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("物理参数")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(430, 330)
        cfg = (_get(parent, "cfg") or {}).get("physics") or {}
        root = QVBoxLayout(self)
        root.addWidget(QLabel("甩抛手感参数（重力 0 = 漂浮模式；非法值自动回退默认）"))
        self._spin = {}
        for label, key, lo, hi in (
                ("重力 gravity（px/s²）", "gravity", 0.0, 10000.0),
                ("反弹 restitution（0~1）", "restitution", 0.0, 1.0),
                ("地面摩擦 groundFriction", "groundFriction", 0.0, 50.0),
                ("力度增益 throwPower", "throwPower", 0.1, 10.0)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            sp.setValue(float(cfg.get(key, 1.0)))
            row.addWidget(sp)
            row.addStretch(1)
            root.addLayout(row)
            self._spin[key] = sp
        self._ceil = QCheckBox("顶边也反弹（ceilingBounce）")
        self._ceil.setChecked(bool(cfg.get("ceilingBounce", True)))
        root.addWidget(self._ceil)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _save(self):
        data = {"gravity": self._spin["gravity"].value(),
                "restitution": self._spin["restitution"].value(),
                "groundFriction": self._spin["groundFriction"].value(),
                "throwPower": self._spin["throwPower"].value(),
                "ceilingBounce": self._ceil.isChecked()}
        _call(self._pet, "apply_physics", data)
        self.accept()


def open_physics(pet):
    """P1-手感：物理参数对话框入口（置顶+显式焦点，同其它对话框套路）。"""
    try:
        dlg = PhysicsDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("physics dialog failed: %r" % (e,))


class VoiceDialog(QDialog):
    """v2.0：语音设置——开关 / 合成方式（系统语音或 API）/ 事件片段导入试听。

    片段由用户自行准备（wav/mp3）；AI 合成受限时主界面气泡明确提示原因（不静默）。"""

    EVENTS = (("reply", "AI 回复"), ("feed", "喂食"), ("poke", "被戳"),
              ("sleep", "睡觉"), ("wake", "醒来"))

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("语音设置")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(520, 420)
        cfg = (_get(parent, "cfg") or {}).get("voice") or {}
        root = QVBoxLayout(self)
        self._en = QCheckBox("开启语音（默认关闭）")
        self._en.setChecked(bool(cfg.get("enabled")))
        root.addWidget(self._en)
        row = QHBoxLayout()
        row.addWidget(QLabel("AI 声音合成"))
        self._mode = QComboBox()
        self._mode.addItem("关闭合成（只用片段）", "off")
        self._mode.addItem("本地系统语音（离线，无需 Key）", "sapi")
        self._mode.addItem("API 合成（OpenAI 兼容 /audio/speech）", "api")
        root.addWidget(row)
        root.addWidget(self._mode)
        _mi = self._mode.findData(cfg.get("tts_mode", "off"))
        if _mi >= 0:
            self._mode.setCurrentIndex(_mi)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("合成声音"))
        self._voice = QLineEdit(cfg.get("tts_voice", ""))
        self._voice.setPlaceholderText("留空用系统默认；如 Microsoft Huihui Desktop / alloy")
        row2.addWidget(self._voice)
        root.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("TTS 模型"))
        self._model = QLineEdit(cfg.get("tts_model", ""))
        self._model.setPlaceholderText("留空用 tts-1")
        row3.addWidget(self._model)
        root.addLayout(row3)
        root.addWidget(QLabel("事件片段（自己准备的 wav/mp3；导入即用，可试听/清除）"))
        self._row_labels = {}
        for key, label in self.EVENTS:
            r = QHBoxLayout()
            r.addWidget(QLabel(label))
            st = QLabel("—")
            r.addWidget(st)
            self._row_labels[key] = st
            b1 = QPushButton("导入…")
            b1.clicked.connect(lambda _c=False, k=key: self._import(k))
            b2 = QPushButton("试听")
            b2.clicked.connect(lambda _c=False, k=key: self._test(k))
            b3 = QPushButton("清除")
            b3.clicked.connect(lambda _c=False, k=key: self._clear(k))
            r.addWidget(b1)
            r.addWidget(b2)
            r.addWidget(b3)
            root.addLayout(r)
        self._refresh_rows()
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _refresh_rows(self):
        """导入/清除后即时刷新「✓ 已配 / —」标签。"""
        voice = _get(self._pet, "voice")
        for key, lbl in self._row_labels.items():
            cur = voice.clip(key) if voice is not None else None
            lbl.setText("✓ 已配" if cur else "—")

    def _import(self, key):
        src, _f = QFileDialog.getOpenFileName(self, "导入语音片段", "", "音频 (*.wav *.mp3)")
        if not src:
            return
        ok, err = _get(self._pet, "voice").set_clip(key, src)
        if not ok:
            _warn(self, "语音片段", err or "导入失败")
            return
        self._refresh_rows()

    def _test(self, key):
        p = _get(self._pet, "voice").clip(key)
        if p is None:
            _warn(self, "试听", "该事件还没配片段")
            return
        try:
            _call(self._pet, "preview_audio", p)
        except Exception as e:
            _warn(self, "试听", "播放失败：%s" % e)

    def _clear(self, key):
        ok, err = _get(self._pet, "voice").set_clip(key, None)
        if not ok:
            _warn(self, "语音片段", err or "清除失败")
            return
        self._refresh_rows()

    def _save(self):
        data = {"enabled": self._en.isChecked(),
                "tts_mode": self._mode.currentData(),
                "tts_voice": self._voice.text().strip(),
                "tts_model": self._model.text().strip()}
        _call(self._pet, "apply_voice", data)
        self.accept()


def open_voice(pet):
    """v2.0：语音设置对话框入口。"""
    try:
        dlg = VoiceDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("voice dialog failed: %r" % (e,))


def ask_amount(pet, title, label, cur):
    """数值输入对话框（预算 / 余额预警共用）：置顶 + 显式焦点，规避前台锁。"""
    dlg = QInputDialog(pet)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setInputMode(QInputDialog.InputMode.DoubleInput)
    dlg.setDoubleRange(0.0, 99999.0)
    dlg.setDoubleDecimals(2)
    dlg.setDoubleValue(cur)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.setFocus()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return round(max(0.0, dlg.doubleValue()), 2)
    return None


def set_frame_max(pet, save_cfg):
    """P3-5+：帧动画帧数上限（读侧与导入管线共用，改完立即生效）。"""
    cur = int(pet.cfg.get("role_frame_max", 24) or 24)
    dlg = QInputDialog(pet)
    dlg.setWindowTitle("帧数上限")
    dlg.setLabelText("帧动画角色最多多少帧？（2~60，对导入与加载立即生效）")
    dlg.setInputMode(QInputDialog.InputMode.IntInput)
    dlg.setIntRange(2, 60)
    dlg.setIntValue(cur)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.setFocus()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    val = dlg.intValue()
    pet.cfg["role_frame_max"] = val
    save_cfg(pet.cfg)
    pet_resources.FRAME_MAX = val
    # 已载入角色立即按新上限重建（调小立即截断生效；调大下次导入即用）
    try:
        pet.role_lib._load()
        pet.apply_role(pet.cfg.get("role", ""))
    except Exception:
        pass  # 有意忽略：重建失败下次启动自愈，不影响上限已落盘
    pet.show_bubble("帧上限改为 %d 帧啦~" % val)
