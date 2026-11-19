"""TG_EVENT 结构化事件的输出与解析测试。

全部离线：不发起任何网络请求。
"""

from __future__ import annotations

from core import events
from core.errors import FailureKind


def test_emit_and_parse(capsys):
    """emit 输出的单行以 TG_EVENT 开头，且能被 parse 还原为同一字典。"""
    events.emit({'type': 'x', 'a': 1})

    out = capsys.readouterr().out
    line = out.strip()
    assert line.startswith('TG_EVENT ')
    assert events.parse(line) == {'type': 'x', 'a': 1}


def test_parse_non_event_returns_none():
    """非 TG_EVENT 行解析结果为 None。"""
    assert events.parse('普通日志') is None


def test_image_fetcher_emit_results(fetcher_factory, capsys):
    """_emit_results 把每条结果转换为一条 date_result 事件。"""
    fetcher = fetcher_factory()
    results = [
        {
            'date': '2015-06-01',
            'name': 'Fake 2015-06-01',
            'status': 'success',
            'file_path': 'out/2015-06-01/2015-06-01.tif',
        },
        {
            'date': '2016-06-01',
            'name': 'Fake 2016-06-01',
            'status': 'failed',
            'file_path': None,
            'failure_kind': FailureKind.FORBIDDEN,
            'detail': 'HTTP 403',
            'failures': [],
        },
    ]

    fetcher._emit_results(results, coord_index=2)

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    parsed = [events.parse(line) for line in lines]

    assert len(parsed) == 2
    assert parsed[0]['type'] == 'date_result'
    assert parsed[0]['coord_index'] == 2
    assert parsed[0]['status'] == 'success'
    assert parsed[0]['kind'] is None
    assert parsed[0]['path'] == 'out/2015-06-01/2015-06-01.tif'
    assert parsed[1]['type'] == 'date_result'
    assert parsed[1]['coord_index'] == 2
    assert parsed[1]['status'] == 'failed'
    assert parsed[1]['kind'] == 'forbidden'
    assert parsed[1]['path'] is None
