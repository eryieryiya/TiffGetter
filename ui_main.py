#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiffGetter 卫星影像获取工具 - GUI

使用 ttkbootstrap 美化；三 Tab 设计：
  - Tab 1 单点下载（含地图选点）
  - Tab 2 批量下载（CSV / SHP）
  - Tab 3 清理与维护

底部共享：日志面板 + Progressbar + 状态栏 + 结果 Treeview。
子进程架构：subprocess.Popen + CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT。

UI 实现已拆分至 ui 包（mixin 组合）；本模块只保留入口与兼容 re-export。
"""
import tkinter as tk

from ui.theme import HAS_TTKBOOTSTRAP, tb
from ui.app import App
from ui.runner import _build_cli_cmd, _cli_workdir
from ui.map_picker import _install_map_user_agent

__all__ = [
    "App",
    "main",
    "_build_cli_cmd",
    "_cli_workdir",
    "_install_map_user_agent",
]


def main():
    if HAS_TTKBOOTSTRAP:
        root = tb.Window(themename="darkly")
    else:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
