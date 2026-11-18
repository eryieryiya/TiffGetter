# -*- coding: utf-8 -*-
"""Tab 2：批量下载（坐标文件、参数、预览、启动）。"""
import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ui.theme import (
    HAS_TTKBOOTSTRAP,
    PRIMARY,
    INFO,
    SUCCESS,
    SECONDARY,
    DANGER,
)
from ui.runner import _build_cli_cmd


class BatchTabMixin:
    """批量下载 Tab 方法集合；需与 App 的其他 mixin 组合使用。"""

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
        self.batch_zoom_spin = ttk.Spinbox(param_frame, from_=1, to=20, textvariable=self.batch_zoom_var, width=18)
        self.batch_zoom_spin.grid(row=0, column=1, padx=(0, 8), pady=2, sticky=tk.W)

        ttk.Label(param_frame, text="缓冲区 (米):").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_buffer_var = tk.IntVar(value=500)
        ttk.Spinbox(param_frame, from_=50, to=5000, increment=50,
                     textvariable=self.batch_buffer_var, width=18).grid(row=0, column=3, pady=2, sticky=tk.W)

        ttk.Label(param_frame, text="起始:").grid(row=1, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_date_start_var = tk.StringVar()
        self.batch_date_start_entry = self._date_entry(param_frame, self.batch_date_start_var)
        self.batch_date_start_entry.grid(row=1, column=1, padx=(0, 8), pady=2, sticky=tk.EW)

        ttk.Label(param_frame, text="截止:").grid(row=1, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_date_end_var = tk.StringVar()
        self.batch_date_end_entry = self._date_entry(param_frame, self.batch_date_end_var)
        self.batch_date_end_entry.grid(row=1, column=3, pady=2, sticky=tk.EW)

        out2 = ttk.Frame(param_frame)
        out2.grid(row=2, column=0, columnspan=4, sticky=tk.EW, pady=(6, 0))
        out2.columnconfigure(1, weight=1)
        ttk.Label(out2, text="输出根目录:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.batch_output_var = tk.StringVar(value=os.path.join("data", "output", "batch"))
        self.batch_output_var.trace_add(
            'write', lambda *_: self._mark_output_edited('_batch_output_edited')
        )
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
        self.preview_tree.heading("source", text="坐标来源")
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

    def _start_batch(self):
        try:
            path, zoom, buf, out, ds, de, conc = self._validate_inputs_batch()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return

        # OSM 公共瓦片不适合批量抓取：启动前二次确认
        if self._current_source_name() == 'osm':
            if not messagebox.askyesno(
                "OSM 批量下载确认",
                "当前数据源为 OpenStreetMap（OSM 公共瓦片）。\n\n"
                "OSM 公共瓦片仅适合轻量、单点使用，批量下载请改用 ESRI 或 Bing，"
                "否则可能被限流或封禁。\n\n仍要继续吗？",
            ):
                return

        self._stopping = False
        self._set_running(True)
        self._clear_results()
        self.log.delete(1.0, tk.END)
        self.status_var.set("批量下载中...")

        info = self._current_source_info()
        cmd = _build_cli_cmd(["--source", info.name,
                              "--coords-file", path,
                              "--zoom", str(zoom), "--buffer", str(buf),
                              "--output", out,
                              "--coord-concurrency", str(conc)])
        if info.supports_history and ds and de:
            cmd.extend(["--date-range", ds, de])

        self._launch_subprocess(cmd)

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
