"""main.py CLI 退出码与失败分类统计测试。"""

from __future__ import annotations

from core.errors import FailureKind
from main import _compute_exit_code, _failure_counts


def _result(status: str, kind=None) -> dict:
    """构造单条结果字典用于退出码测试。"""
    result = {'status': status}
    if kind is not None:
        result['failure_kind'] = kind
    return result


def test_empty_results_exit_4():
    """空结果列表返回 4。"""
    assert _compute_exit_code([]) == 4


def test_all_success_exit_0():
    """没有失败结果返回 0。"""
    results = [
        _result('success'),
        _result('duplicate'),
        _result('existing'),
    ]
    assert _compute_exit_code(results) == 0


def test_partial_failure_exit_3():
    """存在部分失败返回 3。"""
    results = [
        _result('success'),
        _result('failed', FailureKind.FORBIDDEN),
    ]
    assert _compute_exit_code(results) == 3


def test_all_failed_forbidden_exit_4():
    """全部失败且非接口变更返回 4。"""
    results = [
        _result('failed', FailureKind.FORBIDDEN),
        _result('failed', FailureKind.TIMEOUT),
    ]
    assert _compute_exit_code(results) == 4


def test_all_failed_interface_changed_exit_5():
    """全部失败且均为接口变更返回 5。"""
    results = [
        _result('failed', FailureKind.INTERFACE_CHANGED),
        _result('failed', FailureKind.INTERFACE_CHANGED),
    ]
    assert _compute_exit_code(results) == 5


def test_duplicate_and_existing_not_counted_as_failure():
    """duplicate / existing 不计入失败。"""
    results = [
        _result('duplicate'),
        _result('existing'),
        _result('failed', FailureKind.FORBIDDEN),
    ]
    assert _compute_exit_code(results) == 3
    assert _failure_counts(results) == {'forbidden': 1}
