# -*- coding: utf-8 -*-
"""主应用：由 Theme / Runner / MapPicker / 三个 Tab mixin 组合而成。"""
import base64
import os
import queue
import re
import subprocess
import sys
from typing import Literal, Optional

import tkinter as tk
from tkinter import ttk

from providers.registry import list_sources, get_source, DEFAULT_SOURCE

from ui.theme import (
    ThemeMixin,
    HAS_TTKBOOTSTRAP,
    DEFAULT_PAIR_KEY,
    DATE_PLACEHOLDER,
    SUCCESS,
    WARNING,
    SECONDARY,
    THEME_PAIRS,
    tb,
)
from ui.runner import RunnerMixin
from ui.map_picker import MapPickerMixin
from ui.tabs.single import SingleTabMixin
from ui.tabs.batch import BatchTabMixin
from ui.tabs.cleanup import CleanupTabMixin

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
class App(ThemeMixin, RunnerMixin, MapPickerMixin,
          SingleTabMixin, BatchTabMixin, CleanupTabMixin):
    def __init__(self, root):
        self.root = root
        self.process: Optional[subprocess.Popen] = None
        self.log_queue: queue.Queue = queue.Queue()
        self._stopping = False
        self._failure_details = {}

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

        # ----- 数据源状态（单点 / 批量共用同一个选择） -----
        self._source_infos = list_sources()
        self._sources_by_name = {s.name: s for s in self._source_infos}
        self._source_name_by_display = {
            s.display_name: s.name for s in self._source_infos
        }
        self.source_var = tk.StringVar(
            value=self._sources_by_name[DEFAULT_SOURCE].display_name
        )
        # 输出目录是否被用户手动修改（区分自动跟随数据源）
        self._output_programmatic = False
        self._output_edited = False
        self._batch_output_edited = False

        root.title("TiffGetter 卫星影像获取")
        root.geometry("960x720")
        root.minsize(820, 600)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.poll_log_queue()

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
        if HAS_TTKBOOTSTRAP and tb_cls is not None:
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
        tb_cls = tb.Button if HAS_TTKBOOTSTRAP else None
        return self._tk("btn", parent, tb_cls=tb_cls, ttk_cls=ttk.Button,
                        style=style, extra={"text": text, "command": command}, **kw)

    def _lbl(self, parent, text="", style=None, **kw):
        """统一构造标签。"""
        tb_cls = tb.Label if HAS_TTKBOOTSTRAP else None
        return self._tk("lbl", parent, tb_cls=tb_cls, ttk_cls=ttk.Label,
                        style=style, extra={"text": text}, **kw)

    def _cb(self, parent, text="", variable=None, style=None, **kw):
        """统一构造复选框。"""
        tb_cls = tb.Checkbutton if HAS_TTKBOOTSTRAP else None
        return self._tk("cb", parent, tb_cls=tb_cls, ttk_cls=ttk.Checkbutton,
                        style=style, extra={"text": text, "variable": variable}, **kw)

    def _pb(self, parent, style=None, **kw):
        """统一构造进度条。"""
        tb_cls = tb.Progressbar if HAS_TTKBOOTSTRAP else None
        return self._tk("pb", parent, tb_cls=tb_cls, ttk_cls=ttk.Progressbar,
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
            title_col, text="TiffGetter 卫星影像获取",
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

        # ---------- 数据源选择（单点 / 批量共用） ----------
        source_bar = ttk.Frame(self.root, padding=(12, 4))
        source_bar.pack(fill=tk.X)
        ttk.Label(source_bar, text="数据源:").pack(side=tk.LEFT)
        self.source_combo = ttk.Combobox(
            source_bar, textvariable=self.source_var, state='readonly',
            values=[s.display_name for s in self._source_infos], width=26,
        )
        self.source_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.source_combo.bind('<<ComboboxSelected>>', self._on_source_changed)
        self.attribution_lbl = self._lbl(source_bar, text="", style=SECONDARY)
        self.attribution_lbl.pack(side=tk.LEFT, padx=(0, 10))
        self.experimental_lbl = self._lbl(source_bar, text="", style=WARNING)
        self.experimental_lbl.pack(side=tk.LEFT)

        # 数据源使用边界提示（可换行，无提示时隐藏）
        self.source_note_frame = ttk.Frame(self.root, padding=(12, 0))
        self.source_note_frame.pack(fill=tk.X)
        self.source_note_lbl = self._lbl(
            self.source_note_frame, text="", wraplength=760, justify=tk.LEFT,
        )

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
        cols = ("date", "status", "reason", "path")
        self.result_tree = ttk.Treeview(
            result_frame, columns=cols, show='headings', height=5
        )
        self.result_tree.heading("date", text="日期 / 名称")
        self.result_tree.heading("status", text="状态")
        self.result_tree.heading("reason", text="失败原因")
        self.result_tree.heading("path", text="路径")
        self.result_tree.column("date", width=150, anchor=tk.W)
        self.result_tree.column("status", width=100, anchor=tk.CENTER)
        self.result_tree.column("reason", width=150, anchor=tk.W)
        self.result_tree.column("path", width=320, anchor=tk.W)
        self.result_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        rsb = ttk.Scrollbar(result_frame, command=self.result_tree.yview)
        rsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_tree.config(yscrollcommand=rsb.set)
        self.result_tree.bind('<Double-1>', self._open_selected_path)

        # ---------- 运行结束横幅 ----------
        self.run_banner = ttk.Frame(self.root)
        self.run_banner_label = self._lbl(self.run_banner, text="", padding=(8, 4))
        self.run_banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.run_banner_btn = self._btn(
            self.run_banner, text="查看失败详情",
            style=SECONDARY, command=self._show_failure_details, ipad=2,
        )
        self.run_banner_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.run_banner.pack(fill=tk.X, padx=8, pady=(4, 0))

        # ---------- 底部共享区：进度条 + 日志面板 ----------
        bottom = ttk.Frame(self.root, padding=(8, 4))
        bottom.pack(fill=tk.BOTH, expand=True)
        self._bottom_frame = bottom

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
        # 右侧数据源标签
        self.source_status_lbl = self._lbl(
            status_frame, text="", style=outline_style,
            padding=(8, 2), relief=tk.SUNKEN,
        )
        self.source_status_lbl.pack(side=tk.RIGHT, padx=(0, 4))

        # 默认隐藏运行结束横幅（运行结束后再显示）
        self.run_banner.pack_forget()

        # 按初始数据源应用一次联动
        self._apply_source(self._current_source_name())

    # ------------------------------------------------------------------
    # 数据源联动
    # ------------------------------------------------------------------
    def _current_source_name(self) -> str:
        return self._source_name_by_display.get(
            self.source_var.get(), DEFAULT_SOURCE
        )

    def _current_source_info(self):
        name = self._current_source_name()
        info = self._sources_by_name.get(name)
        if info is None:
            info = get_source(name).info
        return info

    def _on_source_changed(self, _event=None):
        self._apply_source(self._current_source_name())

    def _apply_source(self, name: str) -> None:
        info = self._sources_by_name.get(name)
        if info is None:
            try:
                info = get_source(name).info
            except Exception:
                info = self._sources_by_name[DEFAULT_SOURCE]
        self.source_var.set(info.display_name)

        # 1) 日期范围：非历史源禁用并清空
        if info.supports_history:
            self._set_date_widgets_state(True)
        else:
            self._set_date_widgets_state(False)
            for var in (self.date_start_var, self.date_end_var,
                        self.batch_date_start_var, self.batch_date_end_var):
                var.set("")

        # 2) 缩放范围随数据源更新，超限值截断
        self._apply_zoom_limits(info)

        # 3) 输出目录：用户未手动修改时跟随数据源
        if not self._output_edited:
            self._set_output_value(
                self.output_var, self._default_output_for(info.name, batch=False)
            )
        if not self._batch_output_edited:
            self._set_output_value(
                self.batch_output_var,
                self._default_output_for(info.name, batch=True),
            )

        # 4) 版权与实验性提示
        self.attribution_lbl.configure(text=f"版权：{info.attribution}")
        self.experimental_lbl.configure(
            text="⚠ 实验性数据源，接口可能失效" if info.experimental else ""
        )
        self.source_status_lbl.configure(text=f"数据源：{info.display_name}")
        self._refresh_source_note(info)
        self.log_msg(f"当前数据源: {info.display_name}（版权：{info.attribution}）")
        if info.usage_note:
            self.log_msg(f"数据源提示: {info.usage_note}")
        elif info.experimental:
            self.log_msg("提示：该数据源为实验性，接口可能失效")

    # 数据源边界提示的强调色（OSM 警示红 / Google 橙色）
    _SOURCE_NOTE_COLORS = {'osm': '#c0392b', 'google': '#d35400'}

    def _refresh_source_note(self, info) -> None:
        """按数据源边界提示刷新提示 Label；无提示时清空并隐藏。"""
        lbl = getattr(self, 'source_note_lbl', None)
        if lbl is None:
            return
        note = getattr(info, 'usage_note', '') or ''
        if not note:
            lbl.configure(text="")
            if lbl.winfo_manager():
                lbl.pack_forget()
            return
        color = self._SOURCE_NOTE_COLORS.get(getattr(info, 'name', ''))
        try:
            if color:
                lbl.configure(text=f"⚠ {note}", foreground=color)
            else:
                lbl.configure(text=f"⚠ {note}")
        except Exception:
            lbl.configure(text=f"⚠ {note}")
        if not lbl.winfo_manager():
            lbl.pack(fill=tk.X)

    def _set_date_widgets_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget in (self.date_start_entry, self.date_end_entry,
                       self.batch_date_start_entry, self.batch_date_end_entry):
            try:
                widget.configure(state=state)
            except Exception:
                pass

    def _apply_zoom_limits(self, info) -> None:
        for spin, var in ((self.zoom_spin, self.zoom_var),
                          (self.batch_zoom_spin, self.batch_zoom_var)):
            try:
                spin.configure(from_=info.min_zoom, to=info.max_zoom)
            except Exception:
                pass
            try:
                value = var.get()
            except Exception:
                continue
            clamped = min(max(value, info.min_zoom), info.max_zoom)
            if clamped != value:
                var.set(clamped)

    @staticmethod
    def _default_output_for(source_name: str, batch: bool = False) -> str:
        if source_name == DEFAULT_SOURCE:
            return os.path.join(
                "data", "output", "batch" if batch else "historical"
            )
        return os.path.join("data", "output", source_name)

    def _set_output_value(self, var: tk.StringVar, value: str) -> None:
        self._output_programmatic = True
        try:
            var.set(value)
        finally:
            self._output_programmatic = False

    def _mark_output_edited(self, flag_attr: str) -> None:
        if not self._output_programmatic:
            setattr(self, flag_attr, True)

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
