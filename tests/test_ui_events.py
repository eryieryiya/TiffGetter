# -*- coding: utf-8 -*-
"""UI 消费 TG_EVENT 结构化事件的测试（不创建 Tk 窗口）。"""

from __future__ import annotations

from ui.app import App


class FakeTree:
    """记录插入行内容与 tag 的假 Treeview。"""

    def __init__(self):
        """初始化空行记录。"""
        self.rows = []

    def insert(self, parent, index, values=None, tags=()):
        """记录一次插入操作，返回占位行 id。"""
        self.rows.append((values, tags))
        return f"I{len(self.rows)}"

    def get_children(self):
        """无子节点，供进度估算遍历。"""
        return []


def _make_app():
    """构造已绑定假结果树的 App 实例，并跳过进度更新。"""
    app = object.__new__(App)
    app.result_tree = FakeTree()
    app._update_progress_fine = lambda: None
    return app


def test_success_event_row():
    """success 事件插入成功状态行，原因为空，路径取事件 path。"""
    app = _make_app()

    app._handle_event({
        'type': 'date_result',
        'date': '2024-01-01',
        'status': 'success',
        'kind': None,
        'path': '/tmp/a.tif',
    })

    values, tags = app.result_tree.rows[0]
    assert values == ('2024-01-01', '✅ success', '', '/tmp/a.tif')
    assert 'row_success' in tags


def test_failed_event_row_with_reason():
    """failed 事件把 kind 映射为中文失败原因。"""
    app = _make_app()

    app._handle_event({
        'type': 'date_result',
        'date': '2024-01-02',
        'status': 'failed',
        'kind': 'forbidden',
        'path': None,
    })

    values, tags = app.result_tree.rows[0]
    assert values == ('2024-01-02', '❌ failed', '访问被拒绝 (403)', '')
    assert 'row_failed' in tags


def test_duplicate_and_existing_event_rows():
    """duplicate 与 existing 事件均映射为 partial 行 tag。"""
    app = _make_app()

    app._handle_event({
        'type': 'date_result',
        'date': '2024-01-03',
        'status': 'duplicate',
        'kind': None,
        'path': '/tmp/b.tif',
    })
    app._handle_event({
        'type': 'date_result',
        'date': '2024-01-04',
        'status': 'existing',
        'kind': None,
        'path': '/tmp/c.tif',
    })

    first_values, first_tags = app.result_tree.rows[0]
    second_values, second_tags = app.result_tree.rows[1]
    assert first_values[1] == '♻️ duplicate'
    assert 'row_partial' in first_tags
    assert second_values[1] == '📁 existing'
    assert 'row_partial' in second_tags


def test_run_summary_event_ignored():
    """run_summary 事件不插入结果行。"""
    app = _make_app()

    app._handle_event({'type': 'run_summary', 'total': 5})

    assert app.result_tree.rows == []


def test_batch_event_uses_coordinate_name():
    """批量事件的 coord_index 非 None 时第一列取坐标名称。"""
    app = _make_app()

    app._handle_event({
        'type': 'date_result',
        'coord_index': 2,
        'date': '2024-01-01',
        'name': 'NYC',
        'status': 'failed',
        'kind': 'timeout',
        'detail': 'Read timeout',
        'path': None,
    })

    values, tags = app.result_tree.rows[0]
    assert values == ('NYC', '❌ failed', '请求超时', '')
    assert 'row_failed' in tags


def test_unknown_kind_falls_back_to_detail():
    """未知失败类型无中文映射时原因回退为事件 detail。"""
    app = _make_app()

    app._handle_event({
        'type': 'date_result',
        'coord_index': None,
        'date': '2024-01-05',
        'name': 'Site',
        'status': 'failed',
        'kind': 'weird_error',
        'detail': '具体异常',
        'path': None,
    })

    values, tags = app.result_tree.rows[0]
    assert values[2] == '具体异常'
    assert 'row_failed' in tags


def test_parse_result_line_single_columns():
    """旧日志单点成功/失败回退均插入 4 列。"""
    app = _make_app()

    app._parse_result_line('[OK] 2024-08-15')
    app._parse_result_line('[FAIL] 2024-08-15')

    ok_values, ok_tags = app.result_tree.rows[0]
    fail_values, fail_tags = app.result_tree.rows[1]
    assert ok_values == ('2024-08-15', '✅ success', '', '')
    assert 'row_success' in ok_tags
    assert fail_values == ('2024-08-15', '❌ failed', '', '')
    assert 'row_failed' in fail_tags


def test_parse_result_line_batch_columns():
    """旧日志批量回退插入 4 列，第 4 列为经纬度文本。"""
    app = _make_app()

    app._parse_result_line('  [OK] NYC  (40.7128, -74.0060) 成功 1/2')

    values, tags = app.result_tree.rows[0]
    assert values == ('NYC', '✅ success', '', '40.7128,-74.0060 成功 1/2')
    assert 'row_success' in tags
