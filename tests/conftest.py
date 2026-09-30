# -*- coding: utf-8 -*-
"""pytest 共享配置：项目根入路径 + offscreen 平台（Qt 模块无显示器可跑）。"""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
