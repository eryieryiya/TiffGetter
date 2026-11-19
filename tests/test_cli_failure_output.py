"""main.py CLI 失败提示与下载前预检测试。

全部离线：仅验证输出文本与目录创建行为，不发起任何网络请求。
"""

from __future__ import annotations

from core.errors import FailureKind
from main import (
    _batch_failure_lines,
    _preflight_hints,
    _print_failure_hints,
)
import main


def test_print_failure_hints(capsys):
    """失败分类计数应输出分类、数量与对应操作建议。"""
    _print_failure_hints({'forbidden': 1, 'timeout': 2})
    out = capsys.readouterr().out
    assert '失败提示:' in out
    assert 'forbidden (1)' in out
    assert 'timeout (2)' in out
    assert '限制' in out
    assert '超时' in out


def test_print_failure_hints_empty(capsys):
    """空失败计数不输出任何内容。"""
    _print_failure_hints({})
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ''


def test_batch_failure_lines():
    """只为失败坐标生成包含失败分类的文本行。"""
    summary = [
        {
            'name': 'NYC',
            'lat': 40.7128,
            'lon': -74.0060,
            'results': [
                {'status': 'failed', 'failure_kind': FailureKind.FORBIDDEN},
            ],
        },
        {
            'name': 'Tokyo',
            'lat': 35.6762,
            'lon': 139.6503,
            'results': [
                {'status': 'failed', 'failure_kind': FailureKind.TIMEOUT},
            ],
        },
        {
            'name': 'Paris',
            'lat': 48.8566,
            'lon': 2.3522,
            'results': [
                {'status': 'success'},
            ],
        },
    ]
    lines = _batch_failure_lines(summary)
    assert len(lines) == 2
    assert lines[0].startswith('NYC (40.712800, -74.006000)：')
    assert 'forbidden' in lines[0]
    assert lines[1].startswith('Tokyo (35.676200, 139.650300)：')
    assert 'timeout' in lines[1]
    assert all('Paris' not in line for line in lines)


def test_preflight_rasterio_hint(monkeypatch, capsys, tmp_path):
    """rasterio 不可用时提示仅输出 PNG。"""
    monkeypatch.setattr(main, 'HAS_RASTERIO', False)
    assert _preflight_hints(str(tmp_path / 'output')) is True
    out = capsys.readouterr().out
    assert '仅输出 PNG' in out


def test_preflight_proxy_hint(monkeypatch, capsys, tmp_path):
    """检测到代理环境变量时只输出变量名，不输出变量值。"""
    monkeypatch.delenv('HTTP_PROXY', raising=False)
    monkeypatch.delenv('ALL_PROXY', raising=False)
    monkeypatch.setenv('HTTPS_PROXY', 'http://secret-proxy:8080')
    assert _preflight_hints(str(tmp_path / 'output')) is True
    out = capsys.readouterr().out
    assert 'HTTPS_PROXY' in out
    assert 'secret-proxy' not in out


def test_preflight_creates_output_dir(tmp_path):
    """输出目录不存在时应被创建并返回 True。"""
    output_dir = tmp_path / 'nested' / 'output'
    assert _preflight_hints(str(output_dir)) is True
    assert output_dir.is_dir()


def test_preflight_output_dir_failure(monkeypatch, capsys, tmp_path):
    """创建输出目录失败时返回 False 并提示权限或磁盘问题。"""
    def _deny(path, exist_ok=False):
        """模拟目录创建被拒绝。"""
        raise OSError('denied')

    monkeypatch.setattr(main.os, 'makedirs', _deny)
    assert _preflight_hints(str(tmp_path / 'output')) is False
    out = capsys.readouterr().out
    assert '无法创建输出目录' in out
    assert '权限' in out
