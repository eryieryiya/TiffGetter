"""UI 拆分后的模块布局测试：不创建 Tk 根窗口。"""

from __future__ import annotations


def test_ui_main_entrypoint_exports():
    import ui_main

    assert ui_main.App is not None
    assert callable(ui_main.main)


def test_app_is_composed_of_mixins():
    from ui_main import App
    from ui.theme import ThemeMixin
    from ui.runner import RunnerMixin
    from ui.tabs.single import SingleTabMixin
    from ui.tabs.batch import BatchTabMixin
    from ui.tabs.cleanup import CleanupTabMixin

    for mixin in (
        ThemeMixin,
        RunnerMixin,
        SingleTabMixin,
        BatchTabMixin,
        CleanupTabMixin,
    ):
        assert issubclass(App, mixin)


def test_tab_modules_importable():
    import ui.tabs.batch
    import ui.tabs.cleanup
    import ui.tabs.single

    assert callable(ui.tabs.single.SingleTabMixin._build_tab_single)
    assert callable(ui.tabs.batch.BatchTabMixin._build_tab_batch)
    assert callable(ui.tabs.cleanup.CleanupTabMixin._build_tab_cleanup)
