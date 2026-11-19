"""失败类型操作建议（FAILURE_HINTS / failure_hint）测试。

全部离线：仅验证纯函数映射，不发起任何网络请求。
"""

from __future__ import annotations

import pytest

from core.errors import FAILURE_HINTS, FailureKind, failure_hint


@pytest.mark.parametrize('kind', list(FailureKind))
def test_every_failure_kind_has_hint(kind):
    """每个失败类型都必须有非空的中文操作建议。"""
    assert FAILURE_HINTS.get(kind)
    assert failure_hint(kind)
    assert failure_hint(kind.value)


def test_forbidden_hint_mentions_limit_or_retry():
    """FORBIDDEN 建议需提示区域/频率限制或稍后重试。"""
    hint = failure_hint(FailureKind.FORBIDDEN)
    assert ('限制' in hint) or ('稍后重试' in hint)


def test_string_and_enum_hints_are_equal():
    """字符串形式的类型与枚举得到相同建议。"""
    assert failure_hint('timeout') == failure_hint(FailureKind.TIMEOUT)


def test_unknown_kind_returns_empty_string():
    """None 与未知字符串都返回空字符串。"""
    assert failure_hint(None) == ''
    assert failure_hint('weird_error') == ''
