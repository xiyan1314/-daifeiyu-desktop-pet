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

import os
import shutil
import tempfile
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QRadioButton,
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


# ---------------- 角色素材自动处理（导入向导用） ----------------
_IMG_MAX_PROCESS_PX = 2048   # 去背景前的预缩放上限（限制泛洪耗时）
_IMG_TARGET_MAX_PX = 512     # 输出统一上限（角色太大/太小都不合适）
_IMG_BG_TOL = 40             # 去背景颜色容差（RGB 各通道最大差值）
_IMG_MIN_PX = 8


def _remove_background(img):
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
        return None
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
            QApplication.processEvents()  # 大图泛洪数秒：周期让事件循环喘气，避免假死
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


def _content_bbox(img):
    """非透明像素包围盒 (x, y, w, h)；全透明返回 None。"""
    w, h = img.width(), img.height()
    try:
        raw = bytearray(img.bits())
    except Exception:
        return None
    bpl = img.bytesPerLine()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * bpl
        if y % 256 == 0:
            QApplication.processEvents()  # 大图扫描：周期让事件循环喘气
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


def _load_prepared(src, max_px=None):
    """加载素材并做通用预处理：预缩放 → 无透明通道自动去背景。

    max_px=None 用全局 _IMG_MAX_PROCESS_PX（2048）；帧动画可传 1024 控制峰值。
    返回 (img, notes) 或 (None, None)。notes 为这一阶段的说明列表。
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
        removed = _remove_background(img)
        if removed is None:
            notes.append("背景与主体相连，保留原图")
        else:
            img = removed
            notes.append("已自动去背景")
    return img, notes


def _prepare_role_png(src, out_path):
    """导入素材自动处理：无透明通道→去背景；裁剪透明边距；>512px 等比缩小。

    成功返回 (True, notes)；失败返回 (False, err)。notes 为中文说明列表。
    """
    img, notes = _load_prepared(src)
    if img is None:
        return False, "无法加载该图片"
    bbox = _content_bbox(img)
    if bbox is None:
        return False, "图片没有可见内容"
    x, y, w, h = bbox
    if (x, y, w, h) != (0, 0, img.width(), img.height()):
        img = img.copy(x, y, w, h)
        notes.append("已裁剪透明边距")
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


def _prepare_role_frames(srcs, out_dir, same_size=True):
    """批量处理帧素材到统一画布（帧动画导入用）。

    same_size=True（视频/GIF 抽帧，原始尺寸一致）：先算全部帧的内容**并集 bbox**，
    所有帧裁到同一矩形（保留主体平移的动画信息），再统一等比缩放（长边 ≤512）。
    same_size=False（多选图片，尺寸可能不一）：逐帧独立处理（去背景/裁剪/缩放），
    最后把每帧内容居中放进最大帧尺寸的透明画布（尺寸一致、防帧间跳动）。
    返回 (out_paths, notes) 或 (None, err)。
    """
    imgs = []
    for i, s in enumerate(srcs):
        img, _load_notes = _load_prepared(s, max_px=1024)  # 帧序列峰值控制（输出 ≤512）
        if img is None:
            return None, "第 %d 帧无法加载" % (i + 1)
        imgs.append(img)
        QApplication.processEvents()  # 多帧连续处理：周期呼吸
    if same_size:
        # 并集 bbox：所有帧裁到同一矩形，保留帧间平移
        union = None
        for img in imgs:
            b = _content_bbox(img)
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
        b = _content_bbox(img)
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


def _extract_video_frames(src, out_dir):
    """从视频（mp4/webm/mov/avi 等）或 GIF 均匀抽帧（视频 3~20 帧、GIF 3~24 帧）。

    视频走 QtMultimedia（QMediaPlayer + QVideoSink，绿色版自带 ffmpeg 后端），
    GIF 走 QMovie。返回 (原始帧 png 路径列表, err)；失败返回 (None, err)。
    捕获时即缩到 ≤1024（控制 4K 大视频的内存峰值），后续统一走
    _prepare_role_frames（并集画布 + 统一缩放，保留主体平移）。
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
            from PySide6.QtGui import QMovie
            movie = QMovie(src)
            if not movie.isValid():
                movie.stop()
                return None, "GIF 无法读取"
            movie.setCacheMode(QMovie.CacheMode.CacheNone)  # 帧不驻留缓存：控制大 GIF 内存峰值
            n = movie.frameCount()
            if n <= 1:
                movie.stop()
                return None, "GIF 只有 %d 帧，帧动画至少需要 2 帧" % n
            if n > 120:
                movie.stop()
                return None, "GIF 帧数太多（%d 帧），建议改用视频或减少帧数" % n
            take = min(24, n)
            idxs = [int(round(i * (n - 1) / float(take - 1))) for i in range(take)]
            for i in idxs:
                movie.jumpToFrame(i)
                t0 = time.time()
                while movie.currentFrameNumber() != i and time.time() - t0 < 2:
                    QApplication.processEvents()
                    time.sleep(0.005)
                if movie.currentFrameNumber() != i:
                    continue  # 超时未到目标帧：跳过，避免误取旧帧造成重复
                _cap(movie.currentPixmap().toImage())
            movie.stop()
        else:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
            player = QMediaPlayer()
            sink = QVideoSink()
            player.setVideoSink(sink)
            player.setSource(QUrl.fromLocalFile(os.path.abspath(src)))
            t0 = time.time()
            while player.duration() <= 0 and time.time() - t0 < 5:
                QApplication.processEvents()
                time.sleep(0.01)
            dur = player.duration()
            if dur <= 0:
                player.stop()
                return None, "无法读取视频时长（格式不支持？可改用多选图片）"
            if not player.hasVideo():
                player.stop()
                return None, "该文件没有视频画面（纯音频？）"
            take = max(3, min(20, int(dur / 400)))  # 每约 0.4s 一帧
            got = []

            def _on_frame(frame):
                if frame.isValid() and not got:
                    got.append(frame.toImage())

            sink.videoFrameChanged.connect(_on_frame)
            # S1：Qt6 ffmpeg 后端只在播放/暂停态向 sink 投帧——先 play() 拿首帧再 pause()
            # 大文件/高分辨率解码慢：首帧超时随文件大小放宽（无 GPU 软解 HEVC 场景）
            first_cap = 10 if os.path.getsize(src) > 50 * 1024 * 1024 else 5
            player.play()
            t0 = time.time()
            while not got and time.time() - t0 < first_cap:
                QApplication.processEvents()
                time.sleep(0.005)
            player.pause()
            if not got:
                sink.videoFrameChanged.disconnect(_on_frame)
                player.stop()
                return None, "无法从视频读取画面"
            _cap(got[0])  # 首帧（t=0 位置）
            for i in range(1, take):
                t = int(dur * i / float(take))
                del got[:]
                player.setPosition(t)  # 暂停态下 seek 仍会投递目标帧
                t1 = time.time()
                while not got and time.time() - t1 < 3:
                    QApplication.processEvents()
                    time.sleep(0.005)
                if got:
                    _cap(got[0])
            sink.videoFrameChanged.disconnect(_on_frame)
            player.stop()
            player.deleteLater()
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
        self._ok.setDefault(True)
        self._ok.clicked.connect(self._do_import)
        self._cancel.clicked.connect(self.reject)
        btns.addStretch(1)
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
        """处理期间统一禁/启用导入、取消与全部素材选择按钮（防重入嵌套抽帧）。"""
        self._ok.setEnabled(not on)
        self._cancel.setEnabled(not on)
        self._ok.setText(text if on else "导入")
        for b in self._mat_btns:
            b.setEnabled(not on)

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
        if len(files) > 24:
            _warn(self, "多帧动画", "最多 24 帧，当前选了 %d 张" % len(files))
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
            pass
        self._set_busy(True, text="抽帧中…")
        self._frames_status.setText("正在抽帧……")
        QApplication.processEvents()
        raws, err = None, None
        try:
            if self._rawdir is None:
                self._rawdir = tempfile.mkdtemp(prefix="role_raw_")
            raws, err = _extract_video_frames(src, self._rawdir)
        except Exception as e:
            err = "抽帧失败：%s" % e
        finally:
            self._set_busy(False)
        if err:
            _warn(self, "抽帧", err)
            return
        self._set_frames(raws, "已抽 %d 帧（视频/GIF 均匀采样，导入时统一自动处理）" % len(raws),
                         name_hint=os.path.splitext(os.path.basename(src))[0], video=True)

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
        # 大图去背景/裁剪要几秒：禁全部按钮（含素材选择，防重入/嵌套抽帧）
        self._set_busy(True)
        self._notes.setText("正在自动处理素材（去背景 / 裁剪 / 缩放）……")
        QApplication.processEvents()
        try:
            self._tmpdir = tempfile.mkdtemp(prefix="role_prep_")
            frames_out = []
            if self._frames_raw:
                # 帧动画：统一画布处理（并集裁剪/逐帧居中），首帧即形态 0
                frames_out, notesf = _prepare_role_frames(
                    self._frames_raw, self._tmpdir, same_size=bool(self._frames_video))
                if frames_out is None:
                    self._cleanup_tmp()  # 保留原始抽帧：失败后可重试（L3）
                    _warn(self, "导入角色", "帧处理失败：%s" % notesf)
                    return
                base_out = frames_out[0]
                notes = ["帧动画 %d 帧：%s" % (len(frames_out), "、".join(notesf))]
                forms_out = [(forms[0][0], base_out)]
            else:
                base_out = os.path.join(self._tmpdir, "role_base.png")
                ok1, notes1 = _prepare_role_png(forms[0][1], base_out)
                if not ok1:
                    self._cleanup_tmp()
                    _warn(self, "导入角色", "第 1 形态处理失败：%s" % notes1)
                    return
                notes = ["第 1 形态：%s" % ("、".join(notes1) if notes1 else "无需处理")]
                forms_out = [(forms[0][0], base_out)]
            # 其余形态逐个处理
            for i, (nm, src) in enumerate(forms[1:], start=1):
                fp = os.path.join(self._tmpdir, "form%d.png" % i)
                okf, notesf = _prepare_role_png(src, fp)
                if not okf:
                    self._cleanup_tmp()
                    _warn(self, "导入角色", "第 %d 形态处理失败：%s" % (i + 1, notesf))
                    return
                forms_out.append((nm, fp))
                notes.append("第 %d 形态（%s）：%s" % (i + 1, nm, "、".join(notesf) if notesf else "无需处理"))
            self._result = {
                "name": self._name_edit.text().strip()
                        or getattr(self, "_name_hint", "") or "未命名",
                "base": base_out,
                "frames": frames_out or [],
                "forms": forms_out,
                "notes": notes,
            }
            self.accept()
        except Exception as e:
            self._cleanup_tmp()
            _warn(self, "导入角色", "处理失败：%s" % e)
        finally:
            self._set_busy(False)

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
        if not self._ok.isEnabled():
            event.ignore()  # 处理中：忽略关闭，防止清理正在写入的临时目录
            return
        self._cleanup()
        super().closeEvent(event)

    def result_data(self):
        """accepted 后取处理结果：{"name","base","frames","forms","notes"} 或 None。"""
        return self._result


# ---------------- a) 角色面板 ----------------
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
            for b in (self._btn_import, self._btn_set, self._btn_del, self._btn_default):
                b.setEnabled(False)
            self._info.setText("当前：默认角色")
            self._preview.setText("角色库不可用")
            self._preview.setPixmap(QPixmap())
            self._preview_full.setText("角色库不可用")
            self._preview_full.setPixmap(QPixmap())
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
            role, err = self._lib.import_processed(data["base"], None, data["name"],
                                                   frames_src=data.get("frames") or None,
                                                   forms_src=forms_src)
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
