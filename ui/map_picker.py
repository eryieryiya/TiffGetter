# -*- coding: utf-8 -*-
"""地图选点窗口；tkintermapview 为可选依赖。"""
import tkinter as tk
from tkinter import ttk, messagebox

from ui.theme import SUCCESS

# 地图选点：可选依赖；不存在时禁用"地图选点"按钮
try:
    import tkintermapview
    HAS_MAPVIEW = True
except ImportError:
    HAS_MAPVIEW = False


def _install_map_user_agent():
    """为 tkintermapview 注入可识别的 User-Agent。

    该库默认发送 ``User-Agent: TkinterMapView``，无法区分调用方。
    这里只替换 ``tkintermapview.map_widget`` 模块内的 requests 引用，
    不影响全局 requests。
    """
    if not HAS_MAPVIEW:
        return
    try:
        from providers.osm import OSM_USER_AGENT
        import tkintermapview.map_widget as _map_widget

        real_requests = _map_widget.requests

        class _RequestsProxy:
            def get(self, url, **kwargs):
                headers = dict(kwargs.pop('headers', None) or {})
                headers['User-Agent'] = OSM_USER_AGENT
                return real_requests.get(url, headers=headers, **kwargs)

            def __getattr__(self, name):
                return getattr(real_requests, name)

        _map_widget.requests = _RequestsProxy()
    except Exception:
        pass


_install_map_user_agent()


class MapPickerMixin:
    """地图选点方法集合；需与 App 的其他 mixin 组合使用。"""

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
        win.transient(self.root)
        try:
            cur_lat = float(self.lat_var.get())
            cur_lon = float(self.lon_var.get())
        except ValueError:
            cur_lat, cur_lon = 35.6586, 139.7454

        # 可选底图：卫星图 / 矢量图，均使用 Esri，避免 OSM 公共瓦片的限流与拦截
        basemaps = {
            '卫星图': (
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "© Esri, Maxar, Earthstar Geographics",
            ),
            '矢量图': (
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                "© Esri, HERE, Garmin, © OpenStreetMap contributors",
            ),
        }
        default_basemap = '卫星图'

        map_widget = tkintermapview.TkinterMapView(win, width=720, height=460, corner_radius=0)
        map_widget.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        attribution_var = tk.StringVar(value=basemaps[default_basemap][1])
        tk.Label(
            win, textvariable=attribution_var, anchor="e",
            fg="#666666", font=("TkDefaultFont", 9),
        ).pack(fill=tk.X, padx=10, pady=(2, 0))
        map_widget.set_tile_server(basemaps[default_basemap][0], max_zoom=19)
        map_widget.set_zoom(12)
        map_widget.set_position(cur_lat, cur_lon)

        marker = [None]
        picked = [None]  # 窗口内局部状态，避免多个选点窗口互相覆盖

        def on_click(coords):
            lat, lon = coords
            if marker[0] is not None:
                marker[0].delete()
            marker[0] = map_widget.set_marker(lat, lon, text="选中")
            picked[0] = (lat, lon)

        map_widget.add_left_click_map_command(on_click)

        # 按钮
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        ttk.Label(btn_frame, text="底图").pack(side=tk.LEFT)
        basemap_var = tk.StringVar(value=default_basemap)
        basemap_box = ttk.Combobox(
            btn_frame, textvariable=basemap_var, values=list(basemaps),
            state='readonly', width=7,
        )
        basemap_box.pack(side=tk.LEFT, padx=(4, 0))

        def switch_basemap(_event=None):
            url, attribution = basemaps[basemap_var.get()]
            map_widget.set_tile_server(url, max_zoom=19)
            attribution_var.set(attribution)

        basemap_box.bind('<<ComboboxSelected>>', switch_basemap)

        def close():
            win.destroy()

        def confirm():
            if picked[0] is None:
                messagebox.showinfo("提示", "请先在地图上点击选择点位", parent=win)
                return
            lat, lon = picked[0]
            self.lat_var.set(f"{lat:.6f}")
            self.lon_var.set(f"{lon:.6f}")
            close()

        win.protocol("WM_DELETE_WINDOW", close)

        self._btn(btn_frame, text="确认选点", command=confirm, style=SUCCESS).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="取消", command=close).pack(side=tk.RIGHT)
