"""Provider HTTP 响应处理测试。

全部使用假 Session / FakeResponse，不产生任何真实网络请求。
"""
from __future__ import annotations

import logging

import pytest

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


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"tile-payload" * 32


def _osm_source_with(*responses):
    source = get_source("osm")
    source.session = FakeSession(*responses)
    return source


# ----------------------------------------------------------------------
# XYZSource._fetch_image
# ----------------------------------------------------------------------
def test_fetch_image_returns_bytes_for_valid_png():
    source = _osm_source_with(
        FakeResponse(200, {"Content-Type": "image/png"}, PNG_BYTES)
    )

    result = source._fetch_image("https://example.invalid/1/2/3.png")

    assert result == PNG_BYTES
    assert len(source.session.calls) == 1
    call = source.session.calls[0]
    assert call["url"] == "https://example.invalid/1/2/3.png"
    assert call["timeout"] == 60
    assert "User-Agent" in call["headers"]


def test_fetch_image_x_blocked_returns_none_and_logs_once(caplog):
    caplog.set_level(logging.ERROR, logger="providers.xyz")
    blocked = FakeResponse(
        200,
        {"Content-Type": "image/png", "X-Blocked": "true"},
        PNG_BYTES,
    )
    source = _osm_source_with(blocked, blocked)

    assert source._fetch_image("https://example.invalid/tile.png") is None
    assert source._fetch_image("https://example.invalid/tile.png") is None

    records = [
        r for r in caplog.records
        if r.levelno == logging.ERROR and "X-Blocked" in r.getMessage()
    ]
    assert len(records) == 1
    assert "拦截页" in records[0].getMessage()
    assert len(source.session.calls) == 2


def test_fetch_image_403_returns_none():
    source = _osm_source_with(
        FakeResponse(403, {"Content-Type": "text/plain"}, b"forbidden"),
    )

    assert source._fetch_image("https://example.invalid/tile.png") is None


def test_fetch_image_html_content_type_returns_none():
    source = _osm_source_with(
        FakeResponse(200, {"Content-Type": "text/html; charset=utf-8"},
                     b"<html>blocked</html>" * 10),
    )

    assert source._fetch_image("https://example.invalid/tile.png") is None


def test_fetch_image_too_short_content_returns_none():
    source = _osm_source_with(
        FakeResponse(200, {"Content-Type": "image/png"}, b"\x89PNG"),
    )

    assert source._fetch_image("https://example.invalid/tile.png") is None


# ----------------------------------------------------------------------
# OsmSource 基本行为
# ----------------------------------------------------------------------
def test_osm_build_url():
    source = get_source("osm")

    assert source.build_url(3, 4, 5, {}) == (
        "https://tile.openstreetmap.org/3/4/5.png"
    )


def test_osm_headers_contain_contact():
    headers = get_source("osm").headers()

    assert headers["User-Agent"].startswith("TiffGetter/")
    assert "github.com" in headers["User-Agent"]
    assert "Accept" in headers


def test_osm_available_releases_only_current():
    releases = get_source("osm").available_releases(35.0, 139.0, 12)

    assert len(releases) == 1
    release = releases[0]
    assert release["id"] == "current"
    assert release["date"] == "current"
    assert release["source"] == "osm"
    assert release["attribution"]


# ----------------------------------------------------------------------
# 非历史数据源
# ----------------------------------------------------------------------
@pytest.mark.parametrize("name,max_zoom", [("esri", 18), ("bing", 19)])
def test_non_history_source_only_current_release(name, max_zoom):
    source = get_source(name)

    assert source.info.supports_history is False
    releases = source.available_releases(0.0, 0.0, min(10, max_zoom))

    assert len(releases) == 1
    assert releases[0]["id"] == "current"
    assert releases[0]["date"] == "current"
    assert releases[0]["source"] == name


@pytest.mark.parametrize("name", ["esri", "bing", "osm"])
def test_available_releases_rejects_out_of_range_zoom(name):
    source = get_source(name)

    with pytest.raises(ValueError):
        source.available_releases(0.0, 0.0, 0)
