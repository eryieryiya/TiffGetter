# -*- coding: utf-8 -*-
"""Tab 3：清理与维护（残留扫描、勾选、执行清理）。"""
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

from utils.cleanup import (
    cleanup_stale_temp_tiles,
    scan_residuals,
    delete_paths,
    format_size,
)
from ui import BASE_DIR
from ui.theme import (
    INFO,
    WARNING,
    SECONDARY,
    DANGER,
)


class CleanupTabMixin:
    """清理与维护 Tab 方法集合；需与 App 的其他 mixin 组合使用。"""

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

        cols = ("select", "kind", "status", "size", "mtime", "path")
        self.cleanup_tree = ttk.Treeview(
            tree_frame, columns=cols, show='headings', height=10
        )
        self.cleanup_tree.heading("select", text="勾选")
        self.cleanup_tree.heading("kind", text="类型")
        self.cleanup_tree.heading("status", text="状态")
        self.cleanup_tree.heading("size", text="大小")
        self.cleanup_tree.heading("mtime", text="修改时间")
        self.cleanup_tree.heading("path", text="路径")
        self.cleanup_tree.column("select", width=60, anchor=tk.CENTER)
        self.cleanup_tree.column("kind", width=120, anchor=tk.W)
        self.cleanup_tree.column("status", width=80, anchor=tk.CENTER)
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
        self._cleanup_active: dict = {}

    # ------------------------------------------------------------------
    # 清理 Tab 操作
    # ------------------------------------------------------------------
    def _scan_residuals(self):
        for r in self.cleanup_tree.get_children():
            self.cleanup_tree.delete(r)
        self._cleanup_selects.clear()
        self._cleanup_iids.clear()
        self._cleanup_active.clear()

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
            active = bool(it.get('active', False))
            tag = "danger" if it['kind'] == 'historical_date' else "warning"
            iid = self.cleanup_tree.insert('', tk.END, values=(
                "—" if active else "□", it['kind'],
                "使用中" if active else "可清理",
                format_size(it['size_bytes']),
                datetime.fromtimestamp(it['mtime']).strftime("%Y-%m-%d %H:%M:%S"),
                it['path'],
            ), tags=(tag,))
            self._cleanup_selects[iid] = False
            self._cleanup_iids[it['path']] = iid
            self._cleanup_active[iid] = active
        self._refresh_cleanup_checkmarks()
        self.log_msg(f"扫描：发现 {len(items)} 个可清理条目，共 {format_size(total_size)}")
        self.status_var.set(f"发现 {len(items)} 条，共 {format_size(total_size)}")

    def _refresh_cleanup_checkmarks(self):
        """依据 _cleanup_selects 重写 checkbox 列视觉；活跃目录显示为不可选。"""
        for iid, sel in self._cleanup_selects.items():
            try:
                vals = list(self.cleanup_tree.item(iid, 'values'))
                if not vals:
                    continue
                if self._cleanup_active.get(iid, False):
                    vals[0] = "—"
                else:
                    vals[0] = "☑" if sel else "□"
                self.cleanup_tree.item(iid, values=vals)
            except Exception:
                pass

    def _on_cleanup_click(self, event):
        """单击第一列（勾选列）即切换勾选；使用中的目录禁止勾选。"""
        try:
            col = self.cleanup_tree.identify_column(event.x)
            if col != '#1':
                return None
            iid = self.cleanup_tree.identify_row(event.y)
            if not iid:
                return None
            if self._cleanup_active.get(iid, False):
                return "break"
            cur = self._cleanup_selects.get(iid, False)
            self._cleanup_selects[iid] = not cur
            self._refresh_cleanup_checkmarks()
            return "break"
        except Exception:
            return None

    def _select_all_cleanup(self):
        for iid in self._cleanup_selects:
            if self._cleanup_active.get(iid, False):
                continue
            self._cleanup_selects[iid] = True
        self._refresh_cleanup_checkmarks()

    def _invert_cleanup(self):
        for iid in self._cleanup_selects:
            if self._cleanup_active.get(iid, False):
                continue
            self._cleanup_selects[iid] = not self._cleanup_selects[iid]
        self._refresh_cleanup_checkmarks()

    def _toggle_cleanup_row(self, _event):
        iid = self.cleanup_tree.focus()
        if not iid:
            return
        if self._cleanup_active.get(iid, False):
            return
        cur = self._cleanup_selects.get(iid, False)
        self._cleanup_selects[iid] = not cur
        self._refresh_cleanup_checkmarks()

    def _quick_clean_temp(self):
        if not messagebox.askyesno(
            "确认", "将清理已过期（心跳超时）的临时瓦片目录 (temp_tiles_*)。"
                    "使用中的目录会被跳过。继续？"
        ):
            return
        self.status_var.set("清理中...")
        removed = cleanup_stale_temp_tiles(BASE_DIR)
        self.log_msg(f"已清理 {len(removed)} 个过期临时瓦片目录")
        self.status_var.set(f"已清理 {len(removed)} 个")
        # 自动重新扫描
        self._scan_residuals()

    def _execute_cleanup(self):
        selected_paths = [
            path for path, iid in self._cleanup_iids.items()
            if self._cleanup_selects.get(iid, False)
            and not self._cleanup_active.get(iid, False)
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
