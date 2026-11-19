# -*- coding: utf-8 -*-
"""ttkbootstrap 缺失时 UI 控件回退到原生 ttk 的测试（不创建 Tk 窗口）。"""

from __future__ import annotations

import ui.app as ui_app
from ui.app import App


class _FakeWidget:
    """记录构造参数、可被实例化的假控件基类。"""

    def __init__(self, parent=None, **kwargs):
        """保存父容器与全部关键字参数，便于断言。"""
        self.parent = parent
        self.kwargs = kwargs


def _install_fakes(monkeypatch):
    """模拟 ttkbootstrap 缺失，并用假控件类替换原生 ttk 控件类。"""
    monkeypatch.setattr(ui_app, "HAS_TTKBOOTSTRAP", False)
    monkeypatch.setattr(ui_app, "tb", None)
    classes = {}
    for name in ("Button", "Label", "Checkbutton", "Progressbar"):
        fake_cls = type("Fake" + name, (_FakeWidget,), {})
        monkeypatch.setattr(ui_app.ttk, name, fake_cls)
        classes[name] = fake_cls
    return classes


def test_btn_fallback_strips_ttkbootstrap_keys(monkeypatch):
    """ttkbootstrap 缺失时 _btn 回退到 ttk.Button 并剥离专属参数。"""
    classes = _install_fakes(monkeypatch)
    app = object.__new__(App)

    widget = app._btn(object(), "开始", command=lambda: None,
                      bootstyle="success", ipad=4)

    assert type(widget) is classes["Button"]
    assert "bootstyle" not in widget.kwargs
    assert "ipad" not in widget.kwargs
    assert widget.kwargs["text"] == "开始"


def test_lbl_fallback_strips_ttkbootstrap_keys(monkeypatch):
    """ttkbootstrap 缺失时 _lbl 回退到 ttk.Label 并保留普通参数。"""
    classes = _install_fakes(monkeypatch)
    app = object.__new__(App)

    widget = app._lbl(object(), "标题", bootstyle="info", padding=2)

    assert type(widget) is classes["Label"]
    assert "bootstyle" not in widget.kwargs
    assert widget.kwargs["text"] == "标题"
    assert widget.kwargs["padding"] == 2


def test_cb_fallback_strips_ttkbootstrap_keys(monkeypatch):
    """ttkbootstrap 缺失时 _cb 回退到 ttk.Checkbutton 并保留 text/variable。"""
    classes = _install_fakes(monkeypatch)
    app = object.__new__(App)

    widget = app._cb(object(), "启用", variable="var", bootstyle="round-toggle")

    assert type(widget) is classes["Checkbutton"]
    assert "bootstyle" not in widget.kwargs
    assert widget.kwargs["text"] == "启用"
    assert widget.kwargs["variable"] == "var"


def test_pb_fallback_strips_ttkbootstrap_keys(monkeypatch):
    """ttkbootstrap 缺失时 _pb 回退到 ttk.Progressbar 并剥离专属参数。"""
    classes = _install_fakes(monkeypatch)
    app = object.__new__(App)

    widget = app._pb(object(), bootstyle="striped", ipad=3)

    assert type(widget) is classes["Progressbar"]
    assert "bootstyle" not in widget.kwargs
    assert "ipad" not in widget.kwargs


def test_tk_accepts_none_tb_cls(monkeypatch):
    """即使 HAS_TTKBOOTSTRAP 为真，tb_cls 为 None 时也走 ttk 回退。"""
    classes = _install_fakes(monkeypatch)
    monkeypatch.setattr(ui_app, "HAS_TTKBOOTSTRAP", True)
    app = object.__new__(App)

    widget = app._tk(
        "lbl", object(), tb_cls=None, ttk_cls=classes["Label"],
        extra={"text": "x", "bootstyle": "danger"},
        ipad=2, padding=1,
    )

    assert type(widget) is classes["Label"]
    assert widget.kwargs == {"text": "x", "padding": 1}
