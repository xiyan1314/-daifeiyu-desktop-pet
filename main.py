# -*- coding: utf-8 -*-
"""大肥鱼桌宠 主入口（P2-4 命名治理：main.py 为规范入口）。

桌宠.py 保留为兼容壳（绿色版 启动桌宠.vbs 与老脚本仍指向它，行为不变）。
"""
import os
import sys

# 支持从任意目录运行（bat/README 均会 cd 到本目录，此处防御性补足）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠

if __name__ == "__main__":
    桌宠.main()
