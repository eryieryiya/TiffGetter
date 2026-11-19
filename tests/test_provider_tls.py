"""数据源 TLS 校验开关测试。

仅检查会话配置，不发起任何网络请求。
"""
from __future__ import annotations

import pytest

from providers.registry import get_source


@pytest.mark.parametrize(
    "name, expected",
    [
        ("wayback", False),
        ("esri", False),
        ("bing", True),
        ("osm", True),
        ("google", True),
    ],
)
def test_source_session_tls_verification(name, expected):
    """验证各数据源的 session.verify 配置。"""
    assert get_source(name).session.verify is expected
