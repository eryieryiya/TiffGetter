"""主窗口关闭流程测试：不创建 Tk 根窗口，使用假对象直接调用 RunnerMixin._on_close。"""

from __future__ import annotations

import types

from ui.runner import RunnerMixin


class FakeProcess:
    """假子进程：poll() 返回 None 表示运行中，返回 0 表示已结束。"""

    def __init__(self, running: bool):
        self.running = running
        self.terminate_calls = 0

    def poll(self):
        """返回子进程状态：运行中为 None，已结束为 0。"""
        return None if self.running else 0

    def terminate(self):
        """记录终止调用次数。"""
        self.terminate_calls += 1


class FakeRoot:
    """假根窗口：记录 destroy 调用次数。"""

    def __init__(self):
        self.destroy_calls = 0

    def destroy(self):
        """记录窗口销毁调用次数。"""
        self.destroy_calls += 1


def test_on_close_terminates_running_process():
    """运行中的子进程：terminate 与 root.destroy 各调用一次。"""
    process = FakeProcess(running=True)
    root = FakeRoot()
    obj = types.SimpleNamespace(process=process, root=root)

    RunnerMixin._on_close(obj)

    assert process.terminate_calls == 1
    assert root.destroy_calls == 1


def test_on_close_without_process():
    """未启动子进程：不调用 terminate，仅销毁窗口。"""
    process = None
    root = FakeRoot()
    obj = types.SimpleNamespace(process=process, root=root)

    RunnerMixin._on_close(obj)

    assert root.destroy_calls == 1


def test_on_close_after_process_finished():
    """子进程已结束：不调用 terminate，仅销毁窗口。"""
    process = FakeProcess(running=False)
    root = FakeRoot()
    obj = types.SimpleNamespace(process=process, root=root)

    RunnerMixin._on_close(obj)

    assert process.terminate_calls == 0
    assert root.destroy_calls == 1
