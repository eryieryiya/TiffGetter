#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESRI Wayback 历史影像获取工具 - GUI

使用 ttkbootstrap 美化；三 Tab 设计：
  - Tab 1 单点下载（含地图选点）
  - Tab 2 批量下载（CSV / SHP）
  - Tab 3 清理与维护

底部共享：日志面板 + Progressbar + 状态栏 + 结果 Treeview。
子进程架构：subprocess.Popen + CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT。
"""
import os
import sys
import subprocess
import threading
import queue
import signal
import re
import base64
from datetime import datetime
from typing import List, Optional, Dict, Literal

# ttkbootstrap 是必需依赖（已在 environment.yml 声明）
try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import (
        PRIMARY, SUCCESS, INFO, WARNING, DANGER, SECONDARY,
    )
    HAS_TTKBOOTSTRAP = True
except ImportError:
    # 回退到原生 ttk
    HAS_TTKBOOTSTRAP = False
    # 提供空常量占位
    PRIMARY = SUCCESS = INFO = WARNING = DANGER = SECONDARY = None

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# 地图选点：可选依赖；不存在时禁用"地图选点"按钮
try:
    import tkintermapview
    HAS_MAPVIEW = True
except ImportError:
    HAS_MAPVIEW = False

from utils.cleanup import scan_residuals, cleanup_temp_tiles, delete_paths, format_size

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _build_cli_cmd(extra_args: List[str]) -> List[str]:
    """构造 CLI 子进程命令（下载逻辑跑在子进程，stdout 回传日志面板）。

    开发态: python main.py <args>
    打包态: TiffGetter.exe <args>（app_entry 自动按参数路由到 CLI；
            sys.executable 即 exe 自身，不再拼接脚本路径）
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable] + list(extra_args)
    return [sys.executable, os.path.join(BASE_DIR, 'main.py')] + list(extra_args)


def _cli_workdir() -> str:
    """CLI 子进程的工作目录。

    打包态下 BASE_DIR 是 PyInstaller 临时解压目录（退出即删除），
    相对输出路径会写进临时目录导致数据丢失；改为 exe 所在目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return BASE_DIR

# ----------------------------------------------------------------------
# 主题系统常量
# ----------------------------------------------------------------------
THEME_PAIRS: Dict[str, tuple] = {
    "tokyo-night": ("tokyo-night-dark", "tokyo-night-light"),
    "everforest":  ("everforest-dark",  "everforest-light"),
    "dracula":     ("dracula-dark",     "dracula-light"),
    "catppuccin":  ("catppuccin-dark",  "catppuccin-light"),
    "nord":        ("nord-dark",        "nord-light"),
    "gruvbox":     ("gruvbox-dark",     "gruvbox-light"),
    "vapor":       ("vapor-dark",       "vapor-light"),
    "minty":       ("minty-dark",       "minty-light"),
}
DEFAULT_PAIR_KEY = "tokyo-night"
DATE_PLACEHOLDER = "YYYY-MM-DD"

# 48x48 卫星剪影图标 base64
_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAACXBIWXMAAAsTAAALEwEAmpwY"
    "AAABhElEQVR4nO2ZzU7CQBSFP7t03rRo0aNGjRg9cufCnB07c+e9AT/AKzgBeIUP8Ck6cODA"
    "gwcPvD+ASe84Z7lpTnpuLkqSpEmSJEmSpEmSpEmSpEmSpHmH4H8E8AMYB9aAh+AE2AZmgTNg"
    "HNgHLoAnYBU4B56ASWATWAbugc1gHNgGLoFTYBs4BzaBa2AVWAZ2gV1gHlgGdoE1YB1YB2aB"
    "HWAUWAL2gSlgFNghZYBVYBNYoC1AFdgiJoBV4BFYI2VAFdghZYA1YAVYI2WAOdAgaoAt0CBq"
    "gDrQIGqABdAgaYBO0CBpgE7QIGmASNwIJoB46AE2ASHQLG0CJqAENAkqwgKQgJZBB6CE1CEk"
    "kHIoAbSQA0ggZRC5oAO0kAGIIWUQOKCD9EA9JIGUQOaAD9FA9JIKEQO6EA9lAJpIKEQOqEB9"
    "lAJpoKEQOaMA9lAN5oKEQPaMA9lAd5oIMQP6MA9lB15oIEQP6MA/lA/54L4QP60A8FAnwYd2"
    "wBpQAAAAASUVORK5CYII="
)


# ======================================================================
# 主应用
# ======================================================================
class App:
    def __init__(self, root):
        self.root = root
        self.process: Optional[subprocess.Popen] = None
        self.log_queue: queue.Queue = queue.Queue()
        self._stopping = False

        # ----- 主题偏好加载 -----
        try:
            from utils.theme_pref import load_pref, save_pref
            self._tp_load = load_pref
            self._tp_save = save_pref
        except Exception:
            self._tp_load = lambda: {}
            self._tp_save = lambda _d: None
        pref = self._tp_load()
        self.theme_pair: str = pref.get("theme_pair", DEFAULT_PAIR_KEY)
        if self.theme_pair not in THEME_PAIRS:
            self.theme_pair = DEFAULT_PAIR_KEY
        self.theme_mode: Literal["dark", "light"] = (
            "dark" if pref.get("mode") not in ("dark", "light")
            else pref["mode"]
        )
        self._last_good_theme: Optional[str] = None

        # ----- 应用主题（ttkbootstrap） -----
        if HAS_TTKBOOTSTRAP:
            self._apply_theme_initial()
        else:
            style = ttk.Style()
            if 'vista' in style.theme_names():
                style.theme_use('vista')
            self.style = style

        # ----- 其他 UI 状态 -----
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self._estimated_total_dates: Optional[int] = None  # 精细化进度

        root.title("ESRI Wayback 历史影像获取")
        root.geometry("960x720")
        root.minsize(820, 600)

        self._build_ui()
        self.poll_log_queue()

    # ================================================================
    # 主题系统辅助
    # ================================================================
    def _current_full_theme(self) -> str:
        dark, light = THEME_PAIRS[self.theme_pair]
        return dark if self.theme_mode == "dark" else light

    def _get_theme_colors(self, full_theme: str) -> Dict[str, str]:
        is_light = full_theme.endswith("-light") or "light" in full_theme
        palette = {
            "dark": {
                "log_bg":     "#1a1b26", "log_fg":     "#a9b1d6",
                "lvl_info":   "#7aa2f7", "lvl_warn":   "#e0af68",
                "lvl_err":    "#f7768e", "lvl_ok":     "#9ece6a",
                "row_ok":     "#9ece6a", "row_part":   "#e0af68",
                "row_fail":   "#f7768e",
                "stripe_bg":  "#24283b",
                "ph_fg":      "#565f89",
            },
            "light": {
                "log_bg":     "#f5f7ff", "log_fg":     "#343b58",
                "lvl_info":   "#2e7de9", "lvl_warn":   "#8c6c3e",
                "lvl_err":    "#c64343", "lvl_ok":     "#485e30",
                "row_ok":     "#587539", "row_part":   "#8c6c3e",
                "row_fail":   "#c64343",
                "stripe_bg":  "#e8ecf4",
                "ph_fg":      "#8a91a6",
            },
        }
        return palette["dark"] if not is_light else palette["light"]

    def _apply_theme_initial(self) -> None:
        full = self._current_full_theme()
        try:
            self.style = tb.Style(theme=full)
            self._last_good_theme = full
        except Exception as e:
            try:
                self.style = tb.Style(theme="darkly")
                self._last_good_theme = "darkly"
            except Exception:
                self.style = tb.Style()
            print(f"[theme] fallback: {e}", file=sys.stderr)
        try:
            bg = self.style.lookup("TFrame", "background") or "#1a1b26"
            self.root.configure(bg=bg)
        except Exception:
            pass

    def _apply_theme(self, mode: Literal["dark", "light"]) -> None:
        if mode == self.theme_mode and self._last_good_theme is not None:
            return
        self.theme_mode = mode
        full = self._current_full_theme()
        try:
            self.root.withdraw()
            # 使用 theme_use() 而不是 tb.Style(theme=full)，避免遍历所有 widget
            # 这样可以避免 tkcalendar 的 Calendar 组件兼容性问题
            self.style.theme_use(full)
            self._last_good_theme = full
            self._recolor_widgets_for_theme()
            self._tp_save({"theme_pair": self.theme_pair, "mode": self.theme_mode})
            self._update_statusbar_theme_label()
            self.root.deiconify()
        except AttributeError as e:
            # tkcalendar 的 Calendar 组件与 ttkbootstrap 主题切换存在兼容性问题
            # Calendar 对象没有 .style 属性，导致 AttributeError
            # 但 theme_use() 已经成功设置了主题，只是某些 widget 的样式没有更新
            # 我们忽略这个错误，认为主题切换成功
            if "Calendar" in str(e) and "style" in str(e):
                self._last_good_theme = full
                # 用 try-except 包裹，避免再次触发 Calendar 错误
                try:
                    self._recolor_widgets_for_theme()
                except Exception:
                    pass
                self._tp_save({"theme_pair": self.theme_pair, "mode": self.theme_mode})
                self._update_statusbar_theme_label()
                try:
                    self.root.deiconify()
                except Exception:
                    pass
            else:
                try:
                    self.root.deiconify()
                except Exception:
                    pass
                self.log_msg(f"[theme] 切换失败 {full}: {e}")
                if self._last_good_theme and HAS_TTKBOOTSTRAP:
                    try:
                        self.style.theme_use(self._last_good_theme)
                    except Exception:
                        pass
        except Exception as e:
            try:
                self.root.deiconify()
            except Exception:
                pass
            self.log_msg(f"[theme] 切换失败 {full}: {e}")
            if self._last_good_theme and HAS_TTKBOOTSTRAP:
                try:
                    self.style.theme_use(self._last_good_theme)
                except Exception:
                    pass

    def _recolor_widgets_for_theme(self) -> None:
        colors = self._get_theme_colors(self._last_good_theme or "")
        # 1) 日志面板
        try:
            self.log.configure(bg=colors["log_bg"], fg=colors["log_fg"],
                               insertbackground=colors["log_fg"])
        except Exception:
            pass
        self._configure_log_tags(colors)
        # 2) 结果树
        try:
            self.result_tree.tag_configure("row_success", foreground=colors["row_ok"])
            self.result_tree.tag_configure("row_partial", foreground=colors["row_part"])
            self.result_tree.tag_configure("row_failed",  foreground=colors["row_fail"])
        except Exception:
            pass
        # 3) 预览斑马纹
        try:
            self.preview_tree.tag_configure("odd", background=colors["stripe_bg"])
        except Exception:
            pass
        # 4) 清理列表 danger / warning
        try:
            self.cleanup_tree.tag_configure("danger",  foreground=colors["row_fail"])
            self.cleanup_tree.tag_configure("warning", foreground=colors["row_part"])
        except Exception:
            pass

    def _configure_log_tags(self, colors: Dict[str, str]) -> None:
        for tag, key, bold in (
            ("lvl_info", "lvl_info", False),
            ("lvl_warn", "lvl_warn", False),
            ("lvl_err",  "lvl_err",  True),
            ("lvl_ok",   "lvl_ok",   False),
        ):
            try:
                cfg = {"foreground": colors[key]}
                if bold:
                    cfg["font"] = ("Consolas", 9, "bold")
                self.log.tag_configure(tag, **cfg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------
    # ttkbootstrap 专属关键字集合；原生 ttk 不支持时被剥离
    _TB_ONLY_KEYS = {"bootstyle", "ipad", "ipady", "ipadx"}

    def _tk(self, kind, parent, *, tb_cls, ttk_cls, style=None, extra=None, **kw):
        """统一构造 ttkbootstrap / 原生 ttk 控件；ttkbootstrap 失败时回退到 ttk。

        kind: 当前未使用，保留扩展位
        tb_cls / ttk_cls: ttkbootstrap 与原生 ttk 控件类
        style: bootstyle 名
        extra: 仅传给 ttkbootstrap 的额外参数（如 Checkbutton 的 variable）
        """
        if HAS_TTKBOOTSTRAP:
            bs_kw = {"bootstyle": style} if style else {}
            try:
                if extra:
                    return tb_cls(parent, **bs_kw, **extra, **kw)
                return tb_cls(parent, **bs_kw, **kw)
            except Exception:
                pass
        # 回退到原生 ttk：剥离 ttkbootstrap 专属参数
        safe_kw = {k: v for k, v in kw.items() if k not in self._TB_ONLY_KEYS}
        if extra:
            safe_extra = {k: v for k, v in extra.items() if k not in self._TB_ONLY_KEYS}
            return ttk_cls(parent, **safe_extra, **safe_kw)
        return ttk_cls(parent, **safe_kw)

    def _btn(self, parent, text, command=None, style=None, **kw):
        """统一构造按钮。"""
        return self._tk("btn", parent, tb_cls=tb.Button, ttk_cls=ttk.Button,
                        style=style, extra={"text": text, "command": command}, **kw)

    def _lbl(self, parent, text="", style=None, **kw):
        """统一构造标签。"""
        return self._tk("lbl", parent, tb_cls=tb.Label, ttk_cls=ttk.Label,
                        style=style, extra={"text": text}, **kw)

    def _cb(self, parent, text="", variable=None, style=None, **kw):
        """统一构造复选框。"""
        return self._tk("cb", parent, tb_cls=tb.Checkbutton, ttk_cls=ttk.Checkbutton,
                        style=style, extra={"text": text, "variable": variable}, **kw)

    def _pb(self, parent, style=None, **kw):
        """统一构造进度条。"""
        return self._tk("pb", parent, tb_cls=tb.Progressbar, ttk_cls=ttk.Progressbar,
                        style=style, **kw)

    def _build_ui(self):
        # ---------- 品牌头部 ----------
        header = ttk.Frame(self.root, padding=(12, 8))
        header.pack(fill=tk.X)

        # 左：图标
        try:
            self.icon_img = tk.PhotoImage(data=base64.b64decode(_ICON_B64))
            icon_lbl = ttk.Label(header, image=self.icon_img, padding=(0, 0, 12, 0))
            icon_lbl.pack(side=tk.LEFT)
        except Exception:
            self.icon_img = None

        # 中：两行标题
        title_col = ttk.Frame(header)
        title_col.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(
            title_col, text="ESRI Wayback 历史影像获取",
            font=('Segoe UI', 16, 'bold'),
        ).pack(anchor=tk.W)
        sub_text = "批量 · 坐标解析 · GeoTIFF 导出"
        self._lbl(title_col, text=sub_text, style=SECONDARY,
                  font=('Segoe UI', 10)).pack(anchor=tk.W)

        # 右：主题切换器
        self.theme_toggle_frame = ttk.Frame(header)
        self.theme_toggle_frame.pack(side=tk.RIGHT)
        self._build_theme_toggler(self.theme_toggle_frame)

        # 分隔线
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # 主 Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))

        self.tab_single = ttk.Frame(self.notebook, padding=8)
        self.tab_batch = ttk.Frame(self.notebook, padding=8)
        self.tab_cleanup = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_single, text="单点下载")
        self.notebook.add(self.tab_batch, text="批量下载")
        self.notebook.add(self.tab_cleanup, text="清理与维护")

        self._build_tab_single(self.tab_single)
        self._build_tab_batch(self.tab_batch)
        self._build_tab_cleanup(self.tab_cleanup)

        # ---------- 结果 Treeview ----------
        result_frame = ttk.LabelFrame(self.root, text="结果", padding=4)
        result_frame.pack(fill=tk.X, padx=8, pady=(8, 0))
        cols = ("date", "status", "path")
        self.result_tree = ttk.Treeview(
            result_frame, columns=cols, show='headings', height=5
        )
        self.result_tree.heading("date", text="日期 / 名称")
        self.result_tree.heading("status", text="状态")
        self.result_tree.heading("path", text="路径")
        self.result_tree.column("date", width=160, anchor=tk.W)
        self.result_tree.column("status", width=100, anchor=tk.CENTER)
        self.result_tree.column("path", width=400, anchor=tk.W)
        self.result_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        rsb = ttk.Scrollbar(result_frame, command=self.result_tree.yview)
        rsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_tree.config(yscrollcommand=rsb.set)
        self.result_tree.bind('<Double-1>', self._open_selected_path)

        # ---------- 底部共享区：进度条 + 日志面板 ----------
        bottom = ttk.Frame(self.root, padding=(8, 4))
        bottom.pack(fill=tk.BOTH, expand=True)

        # 进度条
        prog_frame = ttk.Frame(bottom)
        prog_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(prog_frame, text="进度:").pack(side=tk.LEFT, padx=(0, 4))
        self.progress = self._pb(prog_frame, style=f"{SUCCESS}-striped",
                                 mode='determinate', maximum=100, value=0)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 日志面板（带工具栏）
        log_frame = ttk.LabelFrame(bottom, text="日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # 日志工具栏
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill=tk.X, pady=(0, 2))
        self._btn(log_toolbar, text="🗑️ 清空", style=SECONDARY,
                  command=self._clear_log, ipad=2).pack(side=tk.LEFT, padx=(0, 4))
        self._btn(log_toolbar, text="📋 复制选中", style=SECONDARY,
                  command=self._copy_log_selection, ipad=2).pack(side=tk.LEFT, padx=(0, 4))
        # spacer
        ttk.Frame(log_toolbar).pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 自动滚动开关
        self._cb(log_toolbar, text="自动滚动",
                 variable=self.auto_scroll_var,
                 style=f"{SUCCESS}-round-toggle").pack(side=tk.RIGHT)

        # 日志文本
        colors_init = self._get_theme_colors(self._last_good_theme or "")
        self.log = tk.Text(
            log_frame, height=10, font=('Consolas', 9), wrap=tk.WORD,
            bg=colors_init["log_bg"], fg=colors_init["log_fg"],
            insertbackground=colors_init["log_fg"],
            relief=tk.FLAT, borderwidth=4,
        )
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.config(yscrollcommand=scrollbar.set)
        # tag 初始配色
        self._configure_log_tags(colors_init)
        # 结果树 tag 初始
        try:
            self.result_tree.tag_configure("row_success", foreground=colors_init["row_ok"])
            self.result_tree.tag_configure("row_partial", foreground=colors_init["row_part"])
            self.result_tree.tag_configure("row_failed",  foreground=colors_init["row_fail"])
        except Exception:
            pass

        # ---------- 状态栏 ----------
        self.status_var = tk.StringVar(value="就绪")
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X)
        status_bar = ttk.Label(
            status_frame, textvariable=self.status_var,
            relief=tk.SUNKEN, anchor=tk.W, padding=(6, 3),
        )
        status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 右侧主题标签
        outline_style = f"{SECONDARY}-outline" if SECONDARY else None
        self.theme_status_lbl = self._lbl(
            status_frame,
            text=f"主题：{self._last_good_theme or '—'}",
            style=outline_style, padding=(8, 2), relief=tk.SUNKEN,
        )
        self.theme_status_lbl.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # 主题切换器
    # ------------------------------------------------------------------
    def _build_theme_toggler(self, parent):
        if not HAS_TTKBOOTSTRAP:
            return
        self.btn_theme_dark = self._btn(
            parent, text="🌙 暗色",
            command=lambda: (self._apply_theme("dark"), self._refresh_theme_buttons()),
            style=PRIMARY,
        )
        self.btn_theme_dark.pack(side=tk.LEFT, padx=(0, 4))
        light_bs = f"{WARNING}-outline" if WARNING else WARNING
        self.btn_theme_light = self._btn(
            parent, text="☀️ 亮色",
            command=lambda: (self._apply_theme("light"), self._refresh_theme_buttons()),
            style=light_bs,
        )
        self.btn_theme_light.pack(side=tk.LEFT)
        self._refresh_theme_buttons()

    def _refresh_theme_buttons(self):
        if not HAS_TTKBOOTSTRAP or not hasattr(self, 'btn_theme_dark'):
            return
        try:
            if self.theme_mode == "dark":
                self.btn_theme_dark.configure(bootstyle=PRIMARY)
            else:
                self.btn_theme_dark.configure(bootstyle=f"{PRIMARY}-outline")
            if self.theme_mode == "light":
                self.btn_theme_light.configure(bootstyle=WARNING)
            else:
                self.btn_theme_light.configure(bootstyle=f"{WARNING}-outline")
        except Exception:
            pass

    def _update_statusbar_theme_label(self):
        if self.theme_status_lbl is not None and self._last_good_theme:
            self.theme_status_lbl.configure(text=f"主题：{self._last_good_theme}")

    # ------------------------------------------------------------------
    # 日期输入（tkcalendar 可选 → Entry+placeholder 降级）
    # ------------------------------------------------------------------
    def _date_entry(self, parent, variable: tk.StringVar):
        try:
            from tkcalendar import DateEntry  # type: ignore
            # 不使用 bootstyle 参数，避免 tkcalendar 的 Calendar 组件与 ttkbootstrap
            # 主题切换产生兼容性问题（Calendar object has no attribute style）
            return DateEntry(parent, textvariable=variable,
                             date_pattern='y-mm-dd', width=22)
        except ImportError:
            e = ttk.Entry(parent, textvariable=variable, width=22)
            colors = self._get_theme_colors(self._last_good_theme or "")
            ph = colors.get("ph_fg", "#888")
            normal_fg = colors.get("log_fg", "#000")

            def on_focus_in(_ev, e=e, ph=DATE_PLACEHOLDER, nfg=normal_fg):
                if e.get() == ph:
                    e.delete(0, tk.END)
                    e.configure(foreground=nfg)

            def on_focus_out(_ev, e=e, ph=DATE_PLACEHOLDER, phfg=ph):
                if not e.get().strip():
                    e.insert(0, ph)
                    e.configure(foreground=phfg)
                elif e.get() == ph:
                    e.configure(foreground=phfg)

            e.bind('<FocusIn>', on_focus_in)
            e.bind('<FocusOut>', on_focus_out)
            if not variable.get():
                e.insert(0, DATE_PLACEHOLDER)
                e.configure(foreground=ph)
            return e

    # ------------------------------------------------------------------
    # Tab1 辅助：粘贴坐标 + 即时校验
    # ------------------------------------------------------------------
    def _paste_coord(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        m = re.match(r'^[\s]*([\-0-9.]+)[,\s]+([\-0-9.]+)[\s]*$', text)
        if not m:
            return
        try:
            lat, lon = float(m.group(1)), float(m.group(2))
        except ValueError:
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        self.lat_var.set(f"{lat:.6f}")
        self.lon_var.set(f"{lon:.6f}")

    def _refresh_coord_hint(self, *_):
        if not hasattr(self, 'coord_hint_lbl'):
            return
        lat_s = self.lat_var.get().strip()
        lon_s = self.lon_var.get().strip()
        if not lat_s and not lon_s:
            txt, bs = "请填入纬度和经度", INFO
        else:
            lat_ok = lon_ok = True
            try:
                lat = float(lat_s)
                if not (-90 <= lat <= 90):
                    raise ValueError
            except (ValueError, TypeError):
                lat_ok = False
            try:
                lon = float(lon_s)
                if not (-180 <= lon <= 180):
                    raise ValueError
            except (ValueError, TypeError):
                lon_ok = False
            if lat_ok and lon_ok and lat_s and lon_s:
                txt, bs = "✓ 坐标合法", SUCCESS
            else:
                reasons = []
                if not lat_ok:
                    reasons.append("lat 越界/非数字" if lat_s else "lat 为空")
                if not lon_ok:
                    reasons.append("lon 越界/非数字" if lon_s else "lon 为空")
                txt, bs = "✗ " + " / ".join(reasons), DANGER
        if HAS_TTKBOOTSTRAP and bs:
            try:
                self.coord_hint_lbl.configure(bootstyle=bs, text=txt)
            except Exception:
                self.coord_hint_lbl.configure(text=txt)
        else:
            self.coord_hint_lbl.configure(text=txt)

    # ------------------------------------------------------------------
    # Tab 1：单点下载
    # ------------------------------------------------------------------
    def _build_tab_single(self, parent):
        # 坐标
        coord_frame = ttk.LabelFrame(parent, text="坐标", padding=10)
        coord_frame.pack(fill=tk.X, pady=(0, 6))
        coord_frame.columnconfigure(1, weight=1)
        coord_frame.columnconfigure(3, weight=1)

        ttk.Label(coord_frame, text="纬度:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.lat_var = tk.StringVar(value="35.6586")
        ttk.Entry(coord_frame, textvariable=self.lat_var, width=22).grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.EW)

        ttk.Label(coord_frame, text="经度:").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.lon_var = tk.StringVar(value="139.7454")
        ttk.Entry(coord_frame, textvariable=self.lon_var, width=22).grid(row=0, column=3, padx=(0, 8), pady=2, sticky=tk.EW)

        # 行1：地图选点 + 粘贴坐标 并排
        btn_row = ttk.Frame(coord_frame)
        btn_row.grid(row=1, column=0, columnspan=4, pady=(4, 0), sticky=tk.EW)
        map_btn_text = "在地图上选点" if HAS_MAPVIEW else "地图选点（缺少 tkintermapview）"
        map_state = tk.NORMAL if HAS_MAPVIEW else tk.DISABLED
        self._btn(btn_row, text=map_btn_text, command=self._open_map_picker,
                  style=INFO, state=map_state).pack(side=tk.LEFT)
        self._btn(btn_row, text="📋 粘贴坐标", command=self._paste_coord,
                  style=SECONDARY).pack(side=tk.LEFT, padx=(6, 0))

        # 即时校验 Label
        self.coord_hint_lbl = self._lbl(coord_frame, text="", style=INFO, padding=(2, 2))
        self.coord_hint_lbl.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(6, 0))
        self.lat_var.trace_add('write', self._refresh_coord_hint)
        self.lon_var.trace_add('write', self._refresh_coord_hint)
        self._refresh_coord_hint()

        # 参数
        param_frame = ttk.LabelFrame(parent, text="参数设置", padding=10)
        param_frame.pack(fill=tk.X, pady=(0, 6))
        param_frame.columnconfigure(1, weight=1)
        param_frame.columnconfigure(3, weight=1)

        ttk.Label(param_frame, text="缩放级别:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.zoom_var = tk.IntVar(value=18)
        ttk.Spinbox(param_frame, from_=1, to=20, textvariable=self.zoom_var, width=18).grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.W)

        ttk.Label(param_frame, text="缓冲区 (米):").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.buffer_var = tk.IntVar(value=500)
        ttk.Spinbox(param_frame, from_=50, to=5000, increment=50,
                     textvariable=self.buffer_var, width=18).grid(row=0, column=3, pady=2, sticky=tk.W)

        # 日期范围（带日期控件）
        date_frame = ttk.LabelFrame(parent, text="日期范围 (可选，留空获取全部)", padding=10)
        date_frame.pack(fill=tk.X, pady=(0, 6))
        date_frame.columnconfigure(1, weight=1)
        date_frame.columnconfigure(3, weight=1)

        ttk.Label(date_frame, text="起始:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.date_start_var = tk.StringVar()
        self._date_entry(date_frame, self.date_start_var).grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.EW)

        ttk.Label(date_frame, text="截止:").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.date_end_var = tk.StringVar()
        self._date_entry(date_frame, self.date_end_var).grid(row=0, column=3, pady=2, sticky=tk.EW)

        # 输出
        out_frame = ttk.LabelFrame(parent, text="输出设置", padding=10)
        out_frame.pack(fill=tk.X, pady=(0, 6))
        out_frame.columnconfigure(1, weight=1)

        ttk.Label(out_frame, text="输出目录:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.output_var = tk.StringVar(value=os.path.join("data", "output", "historical"))
        ttk.Entry(out_frame, textvariable=self.output_var, width=50).grid(row=0, column=1, padx=(0, 4), pady=2, sticky=tk.EW)
        self._btn(out_frame, text="浏览", style=SECONDARY,
                  command=lambda: self.output_var.set(filedialog.askdirectory() or self.output_var.get())
                  ).grid(row=0, column=2, pady=2)

        # 按钮
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 4))
        self.start_single_btn = self._btn(btn_frame, text="开始获取",
                                            command=self._start_single, style=SUCCESS)
        self.start_single_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = self._btn(btn_frame, text="停止", command=self._stop,
                                  state=tk.DISABLED, style=DANGER)
        self.stop_btn.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Tab 2：批量下载
    # ------------------------------------------------------------------
    def _build_tab_batch(self, parent):
        # 文件选择
        file_frame = ttk.LabelFrame(parent, text="坐标文件 (CSV / SHP)", padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 6))
        file_frame.columnconfigure(1, weight=1)

        self.coords_file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.coords_file_var, width=60).grid(row=0, column=0, columnspan=2, padx=(0, 4), pady=2, sticky=tk.EW)
        self._btn(file_frame, text="选择文件", style=SECONDARY,
                  command=self._pick_coords_file).grid(row=0, column=2, pady=2)
        self._btn(file_frame, text="预览", style=INFO,
                  command=self._preview_coords).grid(row=0, column=3, padx=(4, 0), pady=2)
        # 统计徽标
        outline_style = f"{INFO}-outline" if INFO else None
        self.batch_stat_lbl = self._lbl(file_frame, text="待加载", style=outline_style,
                                        padding=(8, 2))
        self.batch_stat_lbl.grid(row=0, column=4, padx=(10, 0), pady=2, sticky=tk.W)
        # 模板导出按钮
        self._btn(file_frame, text="📄 导出 CSV 模板", style=SECONDARY,
                  command=self._export_coord_template).grid(row=0, column=5, padx=(8, 0), pady=2)

        # 通用参数（缩放/缓冲区/日期/输出）
        param_frame = ttk.LabelFrame(parent, text="参数", padding=10)
        param_frame.pack(fill=tk.X, pady=(0, 6))
        param_frame.columnconfigure(1, weight=1)
        param_frame.columnconfigure(3, weight=1)

        ttk.Label(param_frame, text="缩放级别:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_zoom_var = tk.IntVar(value=18)
        ttk.Spinbox(param_frame, from_=1, to=20, textvariable=self.batch_zoom_var, width=18).grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.W)

        ttk.Label(param_frame, text="缓冲区 (米):").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_buffer_var = tk.IntVar(value=500)
        ttk.Spinbox(param_frame, from_=50, to=5000, increment=50,
                     textvariable=self.batch_buffer_var, width=18).grid(row=0, column=3, pady=2, sticky=tk.W)

        ttk.Label(param_frame, text="起始:").grid(row=1, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_date_start_var = tk.StringVar()
        self._date_entry(param_frame, self.batch_date_start_var).grid(row=1, column=1, padx=(0, 8), pady=2, sticky=tk.EW)

        ttk.Label(param_frame, text="截止:").grid(row=1, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_date_end_var = tk.StringVar()
        self._date_entry(param_frame, self.batch_date_end_var).grid(row=1, column=3, pady=2, sticky=tk.EW)

        out2 = ttk.Frame(param_frame)
        out2.grid(row=2, column=0, columnspan=4, sticky=tk.EW, pady=(6, 0))
        out2.columnconfigure(1, weight=1)
        ttk.Label(out2, text="输出根目录:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_output_var = tk.StringVar(value=os.path.join("data", "output", "batch"))
        ttk.Entry(out2, textvariable=self.batch_output_var, width=50).grid(row=0, column=1, padx=(0, 4), pady=2, sticky=tk.EW)
        self._btn(out2, text="浏览", style=SECONDARY,
                  command=lambda: self.batch_output_var.set(filedialog.askdirectory() or self.batch_output_var.get())
                  ).grid(row=0, column=2, pady=2)

        ttk.Label(out2, text="并发数:").grid(row=1, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_concurrency_var = tk.IntVar(value=1)
        ttk.Spinbox(out2, from_=1, to=16, textvariable=self.batch_concurrency_var, width=18).grid(row=1, column=1, pady=2, sticky=tk.W)

        # 预览表（多列 Treeview）
        preview_frame = ttk.LabelFrame(parent, text="坐标点预览", padding=6)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        cols = ("name", "lat", "lon", "source")
        self.preview_tree = ttk.Treeview(preview_frame, columns=cols, show='headings', height=8)
        self.preview_tree.heading("name", text="名称 / ID")
        self.preview_tree.heading("lat", text="纬度")
        self.preview_tree.heading("lon", text="经度")
        self.preview_tree.heading("source", text="来源")
        self.preview_tree.column("name", width=200, anchor=tk.W)
        self.preview_tree.column("lat", width=120, anchor=tk.E)
        self.preview_tree.column("lon", width=120, anchor=tk.E)
        self.preview_tree.column("source", width=80, anchor=tk.CENTER)
        self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        psb = ttk.Scrollbar(preview_frame, command=self.preview_tree.yview)
        psb.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_tree.config(yscrollcommand=psb.set)
        # 初始化斑马纹 tag
        try:
            colors = self._get_theme_colors(self._last_good_theme or "")
            self.preview_tree.tag_configure('odd', background=colors["stripe_bg"])
        except Exception:
            pass

        # 按钮
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X)
        self.start_batch_btn = self._btn(btn_frame, text="开始批量下载",
                                         command=self._start_batch, style=SUCCESS)
        self.start_batch_btn.pack(side=tk.LEFT, padx=(0, 6))

    # ------------------------------------------------------------------
    # Tab 3：清理与维护
    # ------------------------------------------------------------------
    def _build_tab_cleanup(self, parent):
        info = ttk.Label(
            parent,
            text="扫描并清理临时瓦片目录 (temp_tiles_*) 与历史日期子目录。"
                 "默认未勾选任何条目，请确认后再执行清理。",
            wraplength=900, justify=tk.LEFT,
        )
        info.pack(fill=tk.X, pady=(0, 6))

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 6))
        self._btn(btn_frame, text="扫描残留", command=self._scan_residuals,
            style=INFO).pack(side=tk.LEFT, padx=(0, 6))
        self._btn(btn_frame, text="仅清临时瓦片", command=self._quick_clean_temp,
                  style=WARNING).pack(side=tk.LEFT, padx=(0, 6))
        self._btn(btn_frame, text="执行清理 (按勾选)", command=self._execute_cleanup,
                  style=DANGER).pack(side=tk.LEFT, padx=(0, 12))
        # 批量操作
        info_outline = f"{INFO}-outline" if INFO else None
        sec_outline = f"{SECONDARY}-outline" if SECONDARY else None
        self._btn(btn_frame, text="全选", command=self._select_all_cleanup,
                  style=info_outline).pack(side=tk.LEFT, padx=(0, 4))
        self._btn(btn_frame, text="反选", command=self._invert_cleanup,
                  style=sec_outline).pack(side=tk.LEFT)

        # Treeview（带 checkbox 列）
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("select", "kind", "size", "mtime", "path")
        self.cleanup_tree = ttk.Treeview(
            tree_frame, columns=cols, show='headings', height=10
        )
        self.cleanup_tree.heading("select", text="勾选")
        self.cleanup_tree.heading("kind", text="类型")
        self.cleanup_tree.heading("size", text="大小")
        self.cleanup_tree.heading("mtime", text="修改时间")
        self.cleanup_tree.heading("path", text="路径")
        self.cleanup_tree.column("select", width=60, anchor=tk.CENTER)
        self.cleanup_tree.column("kind", width=120, anchor=tk.W)
        self.cleanup_tree.column("size", width=100, anchor=tk.E)
        self.cleanup_tree.column("mtime", width=160, anchor=tk.W)
        self.cleanup_tree.column("path", width=500, anchor=tk.W)
        self.cleanup_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tsb = ttk.Scrollbar(tree_frame, command=self.cleanup_tree.yview)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.cleanup_tree.config(yscrollcommand=tsb.set)
        # 单双切换都支持
        self.cleanup_tree.bind('<Double-1>', self._toggle_cleanup_row)
        self.cleanup_tree.bind('<Button-1>', self._on_cleanup_click)

        self._cleanup_selects: dict = {}
        self._cleanup_iids: dict = {}

    # ------------------------------------------------------------------
    # 日志泵
    # ------------------------------------------------------------------
    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log.insert(tk.END, msg + '\n')
                self._colorize_last_log_line(msg)
                if self.auto_scroll_var.get():
                    self.log.see(tk.END)
                # 解析 [i/N] 粗粒度进度
                m = re.search(r'\[(\d+)/(\d+)\]', msg)
                if m:
                    i, n = int(m.group(1)), int(m.group(2))
                    if n > 0:
                        self.progress['value'] = i / n * 100
                # 提取「找到 K 个版本」估计总日期数
                est = re.search(r'找到\s+(\d+)\s+个版本', msg)
                if est:
                    try:
                        self._estimated_total_dates = int(est.group(1))
                    except Exception:
                        pass
                # 解析成功/失败/重复行追加到结果表 + 精细进度
                self._parse_result_line(msg)
        except queue.Empty:
            pass
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.root.after(50, self.poll_log_queue)

    def log_msg(self, msg: str):
        self.log_queue.put(msg)

    def _clear_log(self):
        try:
            self.log.delete(1.0, tk.END)
        except Exception:
            pass

    def _copy_log_selection(self):
        try:
            sel = self.log.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)
        except Exception:
            pass

    def _colorize_last_log_line(self, msg: str):
        """对最后一行日志按级别着色。"""
        try:
            last_idx = self.log.index("end-1c linestart")
            end_idx = self.log.index("end-1c")
            if last_idx == end_idx:
                return
            has_ok_tag = False
            if re.search(r'\[OK\]|\[PART\]\s*ok', msg):
                self.log.tag_add("lvl_ok", last_idx, end_idx)
                has_ok_tag = True
            if "[FAIL]" in msg:
                self.log.tag_remove("lvl_ok", last_idx, end_idx)
                self.log.tag_add("lvl_err", last_idx, end_idx)
                return
            if has_ok_tag:
                return
            m = re.match(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (INFO|WARNING|ERROR) - (.*)',
                msg,
            )
            if m:
                lvl = m.group(2)
                tag = {"INFO": "lvl_info", "WARNING": "lvl_warn", "ERROR": "lvl_err"}.get(lvl)
                if tag:
                    self.log.tag_add(tag, last_idx, end_idx)
        except Exception:
            pass

    def _update_progress_fine(self):
        """从 result_tree 已插入的 [OK]/[FAIL] 计数估算总进度。"""
        try:
            rows = self.result_tree.get_children()
            done = 0
            for r in rows:
                vals = self.result_tree.item(r, 'values')
                if len(vals) > 1 and vals[1] in ("✅ success", "⚠️ partial", "❌ failed"):
                    done += 1
            if done > 0 and self._estimated_total_dates and self._estimated_total_dates > 0:
                est = min(done / self._estimated_total_dates, 0.99)
                if self.progress['value'] < est * 100:
                    self.progress['value'] = est * 100
        except Exception:
            pass

    def _parse_result_line(self, msg: str):
        """解析单点/批量结果日志，填充结果 Treeview。"""
        # 单点模式：[OK] 2024-08-15
        m1 = re.search(r'\[OK\]\s+(\S+)', msg)
        if m1:
            self.result_tree.insert('', tk.END,
                values=(m1.group(1), '✅ success', ''),
                tags=('row_success',))
            self._update_progress_fine()
            return
        m2 = re.search(r'\[FAIL\]\s+(\S+)', msg)
        if m2:
            self.result_tree.insert('', tk.END,
                values=(m2.group(1), '❌ failed', ''),
                tags=('row_failed',))
            self._update_progress_fine()
            return
        # 批量模式：[OK] name (lat, lon) 成功 X/Y
        m3 = re.search(r'\[(OK|PART|FAIL)\]\s+(\S+)\s+\(([0-9.\-]+),\s*([0-9.\-]+)\)\s+成功\s+(\d+)/(\d+)', msg)
        if m3:
            tag, name, lat, lon, succ, total = m3.groups()
            status_map = {
                'OK':   ('✅ success', 'row_success'),
                'PART': ('⚠️ partial', 'row_partial'),
                'FAIL': ('❌ failed',  'row_failed'),
            }
            status_txt, row_tag = status_map.get(tag, (tag, ''))
            self.result_tree.insert('', tk.END, values=(
                name, status_txt, f"{lat},{lon} 成功 {succ}/{total}"
            ), tags=(row_tag,))
            self._update_progress_fine()

    # ------------------------------------------------------------------
    # 地图选点
    # ------------------------------------------------------------------
    def _open_map_picker(self):
        if not HAS_MAPVIEW:
            messagebox.showerror("依赖缺失", "未安装 tkintermapview，无法使用地图选点")
            return
        win = tk.Toplevel(self.root)
        win.title("地图选点")
        win.geometry("760x540")
        try:
            cur_lat = float(self.lat_var.get())
            cur_lon = float(self.lon_var.get())
        except ValueError:
            cur_lat, cur_lon = 35.6586, 139.7454

        map_widget = tkintermapview.TkinterMapView(win, width=720, height=460, corner_radius=0)
        map_widget.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        map_widget.set_position(cur_lat, cur_lon)
        map_widget.set_zoom(12)

        marker = [None]

        def on_click(coords):
            lat, lon = coords
            if marker[0] is not None:
                marker[0].delete()
            marker[0] = map_widget.set_marker(lat, lon, text="选中")
            self._temp_pick = (lat, lon)

        map_widget.add_left_click_map_command(on_click)

        # 按钮
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        def confirm():
            if hasattr(self, '_temp_pick'):
                lat, lon = self._temp_pick
                self.lat_var.set(f"{lat:.6f}")
                self.lon_var.set(f"{lon:.6f}")
            win.destroy()

        def cancel():
            win.destroy()

        self._btn(btn_frame, text="确认选点", command=confirm, style=SUCCESS).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="取消", command=cancel).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Tab 2 操作
    # ------------------------------------------------------------------
    def _open_in_file_manager(self, path: str):
        """跨平台打开文件管理器并定位到 path。静默失败。"""
        try:
            if os.name == 'nt':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            self.log_msg(f"打开目录失败: {e}")

    def _export_coord_template(self):
        """导出 CSV 模板到临时目录并打开所在文件夹。静默失败。"""
        try:
            import tempfile
            tmp_dir = tempfile.gettempdir()
            target_dir = os.path.join(tmp_dir, "tiffgetter_templates")
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, "tiffgetter_coord_template.csv")
            lines = [
                "name,lat,lon",
                "Tokyo Tower,35.6586,139.7454",
                "Tiananmen,39.9042,116.4074",
            ]
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                f.write("\n".join(lines) + "\n")
            self._open_in_file_manager(target_dir)
            self.log_msg(f"已导出坐标模板：{path}")
        except Exception as e:
            self.log_msg(f"导出模板失败: {e}")

    def _set_batch_stat(self, kind: str, text: str):
        """批量徽标 helper: kind ∈ {primary, info, danger}."""
        if not hasattr(self, 'batch_stat_lbl'):
            return
        if HAS_TTKBOOTSTRAP:
            kind_map = {"primary": PRIMARY, "info": INFO, "danger": DANGER}
            bs = kind_map.get(kind, INFO)
            try:
                self.batch_stat_lbl.configure(bootstyle=bs, text=text)
            except Exception:
                self.batch_stat_lbl.configure(text=text)
        else:
            self.batch_stat_lbl.configure(text=text)

    def _pick_coords_file(self):
        path = filedialog.askopenfilename(
            title="选择坐标文件",
            filetypes=[("CSV / SHP", "*.csv *.shp"), ("CSV", "*.csv"), ("SHP", "*.shp"), ("All", "*.*")],
        )
        if path:
            self.coords_file_var.set(path)

    def _preview_coords(self):
        path = self.coords_file_var.get().strip()
        if not path:
            messagebox.showerror("错误", "请先选择坐标文件")
            self._set_batch_stat(kind="danger", text="未选择文件")
            return
        if not os.path.exists(path):
            messagebox.showerror("错误", f"文件不存在: {path}")
            self._set_batch_stat(kind="danger", text="文件不存在")
            return
        try:
            from coordinate_loader import load_coordinates_file, CoordinateLoadError
            coords = load_coordinates_file(path)
        except CoordinateLoadError as e:
            messagebox.showerror("解析失败", f"{e}\n({e.path})\nhint={e.hint}")
            self._set_batch_stat(kind="danger", text="解析失败")
            return
        except Exception as e:
            messagebox.showerror("解析失败", str(e))
            self._set_batch_stat(kind="danger", text=type(e).__name__)
            return

        # 清空 preview
        for r in self.result_tree.get_children():
            self.result_tree.delete(r)
        for r in self.preview_tree.get_children():
            self.preview_tree.delete(r)
        # 填充（最多 100 行）- 加斑马纹 tag
        for idx, c in enumerate(coords[:100]):
            tags = ('odd',) if idx % 2 else ()
            self.preview_tree.insert('', tk.END, values=(
                c.get('name') or c.get('id') or '',
                f"{c['lat']:.6f}",
                f"{c['lon']:.6f}",
                c.get('source', ''),
            ), tags=tags)
        if len(coords) > 100:
            self.preview_tree.insert('', tk.END, values=(
                '...', '', '', f'共 {len(coords)} 个，仅显示前 100 行'
            ))
        else:
            self.preview_tree.insert('', tk.END, values=(
                f'共 {len(coords)} 个', '', '', ''
            ))
        self.log_msg(f"预览：解析到 {len(coords)} 个坐标点")
        self._set_batch_stat(kind="primary", text=f"共 {len(coords)} 个点")

    # ------------------------------------------------------------------
    # 清理 Tab 操作
    # ------------------------------------------------------------------
    def _scan_residuals(self):
        for r in self.cleanup_tree.get_children():
            self.cleanup_tree.delete(r)
        self._cleanup_selects.clear()
        self._cleanup_iids.clear()

        items = scan_residuals(BASE_DIR)
        if not items:
            self.log_msg("扫描：无残留条目")
            self.status_var.set("就绪")
            return

        # 初始 theme 色应用到 tree tags
        try:
            colors = self._get_theme_colors(self._last_good_theme or "")
            self.cleanup_tree.tag_configure("danger",  foreground=colors["row_fail"])
            self.cleanup_tree.tag_configure("warning", foreground=colors["row_part"])
        except Exception:
            pass

        total_size = 0
        for it in items:
            total_size += it['size_bytes']
            tag = "danger" if it['kind'] == 'historical_date' else "warning"
            iid = self.cleanup_tree.insert('', tk.END, values=(
                "□", it['kind'], format_size(it['size_bytes']),
                datetime.fromtimestamp(it['mtime']).strftime("%Y-%m-%d %H:%M:%S"),
                it['path'],
            ), tags=(tag,))
            self._cleanup_selects[iid] = False
            self._cleanup_iids[it['path']] = iid
        self._refresh_cleanup_checkmarks()
        self.log_msg(f"扫描：发现 {len(items)} 个可清理条目，共 {format_size(total_size)}")
        self.status_var.set(f"发现 {len(items)} 条，共 {format_size(total_size)}")

    def _refresh_cleanup_checkmarks(self):
        """依据 _cleanup_selects 重写 checkbox 列视觉。"""
        for iid, sel in self._cleanup_selects.items():
            try:
                vals = list(self.cleanup_tree.item(iid, 'values'))
                if not vals:
                    continue
                vals[0] = "☑" if sel else "□"
                self.cleanup_tree.item(iid, values=vals)
            except Exception:
                pass

    def _on_cleanup_click(self, event):
        """单击第一列（勾选列）即切换勾选。"""
        try:
            col = self.cleanup_tree.identify_column(event.x)
            if col != '#1':
                return None
            iid = self.cleanup_tree.identify_row(event.y)
            if not iid:
                return None
            cur = self._cleanup_selects.get(iid, False)
            self._cleanup_selects[iid] = not cur
            self._refresh_cleanup_checkmarks()
            return "break"
        except Exception:
            return None

    def _select_all_cleanup(self):
        for iid in self._cleanup_selects:
            self._cleanup_selects[iid] = True
        self._refresh_cleanup_checkmarks()

    def _invert_cleanup(self):
        for iid in self._cleanup_selects:
            self._cleanup_selects[iid] = not self._cleanup_selects[iid]
        self._refresh_cleanup_checkmarks()

    def _toggle_cleanup_row(self, _event):
        iid = self.cleanup_tree.focus()
        if not iid:
            return
        cur = self._cleanup_selects.get(iid, False)
        self._cleanup_selects[iid] = not cur
        self._refresh_cleanup_checkmarks()

    def _quick_clean_temp(self):
        if not messagebox.askyesno("确认", "将清理所有临时瓦片目录 (temp_tiles_*)。继续？"):
            return
        self.status_var.set("清理中...")
        removed = cleanup_temp_tiles(BASE_DIR)
        self.log_msg(f"已清理 {len(removed)} 个临时瓦片目录")
        self.status_var.set(f"已清理 {len(removed)} 个")
        # 自动重新扫描
        self._scan_residuals()

    def _execute_cleanup(self):
        selected_paths = [
            path for path, iid in self._cleanup_iids.items()
            if self._cleanup_selects.get(iid, False)
        ]
        if not selected_paths:
            messagebox.showinfo("提示", "未勾选任何条目")
            return

        preview = "\n".join(f"  - {p}" for p in selected_paths[:20])
        if len(selected_paths) > 20:
            preview += f"\n  ... 还有 {len(selected_paths) - 20} 项"
        if not messagebox.askyesno(
            "二次确认",
            f"将永久删除 {len(selected_paths)} 个目录：\n{preview}\n\n确认？",
        ):
            return

        self.status_var.set("清理中...")
        results = delete_paths(selected_paths)
        ok_n = sum(1 for r in results if r['ok'])
        fail_n = len(results) - ok_n
        self.log_msg(f"清理完成：成功 {ok_n}, 失败 {fail_n}")
        for r in results:
            if not r['ok']:
                self.log_msg(f"  失败: {r['path']} - {r['error']}")
        self.status_var.set(f"清理完成 ({ok_n} 成功 / {fail_n} 失败)")
        self._scan_residuals()

    # ------------------------------------------------------------------
    # 子进程控制
    # ------------------------------------------------------------------
    def _set_running(self, running: bool):
        if running:
            self.start_single_btn.config(state=tk.DISABLED)
            self.start_batch_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.start_single_btn.config(state=tk.NORMAL)
            self.start_batch_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _validate_date_range(self, start_var: tk.StringVar, end_var: tk.StringVar):
        """校验日期范围：占位符视为空，需同时填写或同时留空。返回 (ds, de)。"""
        ds = start_var.get().strip()
        de = end_var.get().strip()
        if ds == DATE_PLACEHOLDER:
            ds = ""
        if de == DATE_PLACEHOLDER:
            de = ""
        if ds or de:
            for d in (ds, de):
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                    raise ValueError(f"日期格式错误 '{d}'")
            if ds and de and ds > de:
                raise ValueError("起始日期不能晚于截止日期")
            if not (ds and de):
                raise ValueError("起始和截止日期必须同时填写或同时留空")
        return ds, de

    def _validate_inputs_single(self):
        try:
            lat = float(self.lat_var.get())
        except ValueError:
            raise ValueError("纬度必须是数字")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"纬度越界 {lat}")
        try:
            lon = float(self.lon_var.get())
        except ValueError:
            raise ValueError("经度必须是数字")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"经度越界 {lon}")
        zoom = self.zoom_var.get()
        if not (1 <= zoom <= 20):
            raise ValueError(f"缩放级别越界 {zoom}")
        buf = self.buffer_var.get()
        if not (50 <= buf <= 5000):
            raise ValueError(f"缓冲区越界 {buf}")
        out = self.output_var.get().strip()
        if not out:
            raise ValueError("输出目录不能为空")
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            raise ValueError(f"输出目录无法创建：{e}")
        ds, de = self._validate_date_range(self.date_start_var, self.date_end_var)
        return lat, lon, zoom, buf, out, ds, de

    def _validate_inputs_batch(self):
        path = self.coords_file_var.get().strip()
        if not path:
            raise ValueError("请选择坐标文件")
        if not os.path.exists(path):
            raise ValueError(f"文件不存在: {path}")
        zoom = self.batch_zoom_var.get()
        if not (1 <= zoom <= 20):
            raise ValueError(f"缩放级别越界 {zoom}")
        buf = self.batch_buffer_var.get()
        if not (50 <= buf <= 5000):
            raise ValueError(f"缓冲区越界 {buf}")
        out = self.batch_output_var.get().strip()
        if not out:
            raise ValueError("输出根目录不能为空")
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            raise ValueError(f"输出目录无法创建：{e}")
        ds, de = self._validate_date_range(self.batch_date_start_var, self.batch_date_end_var)
        conc = self.batch_concurrency_var.get()
        if not (1 <= conc <= 16):
            raise ValueError(f"并发数越界 {conc}")
        return path, zoom, buf, out, ds, de, conc

    def _clear_results(self):
        for r in self.result_tree.get_children():
            self.result_tree.delete(r)
        self.progress['value'] = 0

    def _start_single(self):
        try:
            lat, lon, zoom, buf, out, ds, de = self._validate_inputs_single()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return

        self._stopping = False
        self._set_running(True)
        self._clear_results()
        self.log.delete(1.0, tk.END)
        self.status_var.set("运行中...")

        cmd = _build_cli_cmd(["--lat", str(lat), "--lon", str(lon),
                              "--zoom", str(zoom), "--buffer", str(buf),
                              "--output", out])
        if ds and de:
            cmd.extend(["--date-range", ds, de])

        self._launch_subprocess(cmd)

    def _start_batch(self):
        try:
            path, zoom, buf, out, ds, de, conc = self._validate_inputs_batch()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return

        self._stopping = False
        self._set_running(True)
        self._clear_results()
        self.log.delete(1.0, tk.END)
        self.status_var.set("批量下载中...")

        cmd = _build_cli_cmd(["--coords-file", path,
                              "--zoom", str(zoom), "--buffer", str(buf),
                              "--output", out,
                              "--coord-concurrency", str(conc)])
        if ds and de:
            cmd.extend(["--date-range", ds, de])

        self._launch_subprocess(cmd)

    def _launch_subprocess(self, cmd: list):
        def run():
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=_cli_workdir(),
                    creationflags=creationflags,
                )
                for line in self.process.stdout:
                    self.log_msg(line.rstrip())
                self.process.wait()
            except Exception as e:
                self.log_msg(f"启动子进程失败: {e}")
            finally:
                self.process = None
                self.root.after(0, self._on_done)

        threading.Thread(target=run, daemon=True).start()

    def _stop(self):
        if self.process and self.process.poll() is None:
            self._stopping = True
            self.status_var.set("正在停止...")
            self.stop_btn.config(state=tk.DISABLED)
            try:
                if os.name == 'nt':
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.terminate()
            except Exception as e:
                self.log_msg(f"停止信号发送失败: {e}")
                try:
                    self.process.terminate()
                except Exception:
                    pass
        else:
            self._set_running(False)
            self.status_var.set("已停止")

    def _on_done(self):
        self._set_running(False)
        if self._stopping:
            self.status_var.set("已停止")
        else:
            self.status_var.set("完成")
            try:
                self.progress['value'] = 100
            except Exception:
                pass
            # 进度条 bootstyle 切回 SUCCESS
            if HAS_TTKBOOTSTRAP:
                try:
                    self.progress.configure(bootstyle=f"{SUCCESS}-striped")
                except Exception:
                    pass

    def _open_selected_path(self, _event):
        iid = self.result_tree.focus()
        if not iid:
            return
        vals = self.result_tree.item(iid, 'values')
        path = vals[2] if len(vals) > 2 else ''
        # 路径可能只是 "lat,lon 成功 X/Y"，无目录则忽略
        if path and os.path.exists(path):
            self._open_in_file_manager(os.path.dirname(path))


def main():
    if HAS_TTKBOOTSTRAP:
        root = tb.Window(themename="darkly")
    else:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()