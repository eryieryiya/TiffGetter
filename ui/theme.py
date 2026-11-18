# -*- coding: utf-8 -*-
"""主题系统：主题常量、明暗切换、配色、日志 tag 与主题按钮。"""
import sys
from typing import Dict, Literal

import tkinter as tk

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
    tb = None
    # 提供空常量占位
    PRIMARY = SUCCESS = INFO = WARNING = DANGER = SECONDARY = None

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


class ThemeMixin:
    """主题相关方法集合；需与 App 的其他 mixin 组合使用。"""

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
        # 主题切换后刷新数据源边界提示的颜色
        try:
            self._refresh_source_note(self._current_source_info())
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
