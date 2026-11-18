# -*- coding: utf-8 -*-
"""TiffGetter GUI 包（由 ui_main.py 拆分出的 mixin 组合）。

各子模块只依赖本包内更底层的模块，避免循环导入：

    ui.theme      ← ui.runner / ui.map_picker / ui.tabs.*
    ui.runner     ← ui.tabs.single / ui.tabs.batch
    ui.app        组合全部 mixin
"""
import os

# 仓库根目录（原 ui_main.py 所在目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
