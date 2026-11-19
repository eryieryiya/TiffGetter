"""瓦片下载失败分类测试。

全部使用假 Session / FakeResponse，不产生任何真实网络请求。
"""
from __future__ import annotations

import requests

from core.errors import FailureKind
from providers.registry import get_source


class FakeResponse:
    """最小的 requests.Response 替身。"""

    def __init__(self, status_code=200, headers=None, content=b""):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.content = content


class FakeSession:
    """按顺序返回预置响应，并记录每次 get 调用。"""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if not self._responses:
            raise AssertionError("FakeSession 没有更多预置响应")
        return self._responses.pop(0)


class RaisingSession:
    """get 调用时直接抛出预置异常，用于模拟网络层失败。"""

    def __init__(self, exc):
        self._exc = exc
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        raise self._exc


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"tile-payload" * 32


def _osm_source_with_session(session):
    source = get_source("osm")
    source.session = session
    return source


# ----------------------------------------------------------------------
# 成功
# ----------------------------------------------------------------------
def test_success_returns_content():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(200, {"Content-Type": "image/png"}, PNG_BYTES)
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is True
    assert result.content == PNG_BYTES
    assert result.kind is None
    assert result.retryable is False
    assert result.http_status is None


# ----------------------------------------------------------------------
# HTTP 状态码分类
# ----------------------------------------------------------------------
def test_http_403_classified_as_forbidden():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(403, {"Content-Type": "text/plain"}, b"forbidden")
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.FORBIDDEN
    assert result.http_status == 403
    assert result.retryable is False


def test_http_429_classified_as_rate_limited():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(429, {"Content-Type": "text/plain"}, b"slow down")
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.RATE_LIMITED
    assert result.http_status == 429
    assert result.retryable is True


def test_http_500_classified_as_server():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(500, {"Content-Type": "text/plain"}, b"server error")
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.SERVER
    assert result.http_status == 500
    assert result.retryable is True


# ----------------------------------------------------------------------
# 响应内容分类
# ----------------------------------------------------------------------
def test_x_blocked_classified_as_blocked():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(
            200,
            {"Content-Type": "image/png", "X-Blocked": "true"},
            PNG_BYTES,
        )
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.BLOCKED
    assert result.http_status == 200
    assert result.retryable is False


def test_text_html_classified_as_invalid_content():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(
            200,
            {"Content-Type": "text/html; charset=utf-8"},
            b"<html>blocked</html>" * 10,
        )
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.INVALID_CONTENT
    assert result.http_status == 200
    assert result.retryable is False


def test_short_content_classified_as_invalid_content():
    source = _osm_source_with_session(FakeSession(
        FakeResponse(200, {"Content-Type": "image/png"}, b"\x89PNG")
    ))

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.INVALID_CONTENT
    assert result.http_status == 200
    assert result.retryable is False


# ----------------------------------------------------------------------
# 异常分类
# ----------------------------------------------------------------------
def test_timeout_classified_as_timeout():
    source = _osm_source_with_session(
        RaisingSession(requests.exceptions.Timeout('read timeout'))
    )

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.TIMEOUT
    assert result.detail == 'Timeout: read timeout'
    assert result.retryable is True


def test_ssl_error_classified_as_tls():
    source = _osm_source_with_session(
        RaisingSession(requests.exceptions.SSLError('bad cert'))
    )

    result = source._fetch_image("https://example.invalid/tile.png")

    assert result.ok is False
    assert result.kind is FailureKind.TLS
    assert result.detail == 'SSLError: bad cert'
    assert result.retryable is False
