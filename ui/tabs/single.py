# -*- coding: utf-8 -*-
"""Tab 1：单点下载（坐标输入、地图选点、日期、输出、启动）。"""
import os
import re

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ui.theme import (
    DATE_PLACEHOLDER,
    HAS_TTKBOOTSTRAP,
    INFO,
    SUCCESS,
    SECONDARY,
    DANGER,
)
from ui.runner import _build_cli_cmd
from ui.map_picker import HAS_MAPVIEW


class SingleTabMixin:
    """单点下载 Tab 方法集合；需与 App 的其他 mixin 组合使用。"""

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
        self.zoom_spin = ttk.Spinbox(param_frame, from_=1, to=20, textvariable=self.zoom_var, width=18)
        self.zoom_spin.grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.W)

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
        self.date_start_entry = self._date_entry(date_frame, self.date_start_var)
        self.date_start_entry.grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.EW)

        ttk.Label(date_frame, text="截止:").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.date_end_var = tk.StringVar()
        self.date_end_entry = self._date_entry(date_frame, self.date_end_var)
        self.date_end_entry.grid(row=0, column=3, pady=2, sticky=tk.EW)

        # 输出
        out_frame = ttk.LabelFrame(parent, text="输出设置", padding=10)
        out_frame.pack(fill=tk.X, pady=(0, 6))
        out_frame.columnconfigure(1, weight=1)

        ttk.Label(out_frame, text="输出目录:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.output_var = tk.StringVar(value=os.path.join("data", "output", "historical"))
        self.output_var.trace_add(
            'write', lambda *_: self._mark_output_edited('_output_edited')
        )
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

        info = self._current_source_info()
        cmd = _build_cli_cmd(["--source", info.name,
                              "--lat", str(lat), "--lon", str(lon),
                              "--zoom", str(zoom), "--buffer", str(buf),
                              "--output", out])
        if info.supports_history and ds and de:
            cmd.extend(["--date-range", ds, de])

        self._launch_subprocess(cmd)
