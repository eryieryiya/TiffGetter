"""Wayback 元数据缓存与来源标记的离线单元测试。

全部使用假 Session / FakeResponse，不产生任何真实网络请求，
磁盘缓存路径统一重定向到 pytest 的 tmp_path。
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import pytest

import providers.wayback as wayback
from providers.registry import get_source


class FakeResponse:
    """最小的 requests.Response 替身，支持 json() 解析预置载荷。"""

    def __init__(self, status_code=200, headers=None, content=b"", payload=None):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.content = content
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """按顺序返回预置响应或抛出预置异常，并记录每次 get 调用。"""

    def __init__(self, *items):
        self._items = list(items)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if not self._items:
            raise AssertionError("FakeSession 没有更多预置响应")
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def cache_file(monkeypatch, tmp_path):
    """把磁盘缓存重定向到 tmp_path，并在每个测试前后重置模块内存缓存。"""
    path = tmp_path / "wayback_releases.json"
    monkeypatch.setattr(wayback, "CACHE_PATH", str(path))
    wayback._reset_memory_cache()
    yield path
    wayback._reset_memory_cache()


def _wayback_source_with(*items):
    """构造 wayback 数据源，并用 FakeSession 替换真实网络会话。"""
    source = get_source("wayback")
    source.session = FakeSession(*items)
    return source


def _selection_payload(*entries):
    """构造 ESRI 元数据响应 JSON；entries 为 (M, Name) 序列。"""
    return {
        "Service": "Wayback",
        "Selection": [
            {"Name": name, "M": wayback_id, "ID": f"WB_{wayback_id}"}
            for wayback_id, name in entries
        ],
    }


def test_online_metadata_is_cached(cache_file):
    payload = _selection_payload(
        ("111", "World Imagery (Wayback 2026-05-28)"),
        ("222", "World Imagery (Wayback 2024-08-15)"),
    )
    first_source = _wayback_source_with(FakeResponse(200, payload=payload))

    first = first_source.available_releases(0.0, 0.0, 12)

    assert len(first) == 2
    assert all(item["metadata_source"] == "online" for item in first)
    assert cache_file.exists()
    assert len(first_source.session.calls) == 1

    second_source = _wayback_source_with(
        AssertionError("命中缓存时不应发起网络请求")
    )
    second = second_source.available_releases(0.0, 0.0, 12)

    assert second_source.session.calls == []
    assert all(item["metadata_source"] == "cache" for item in second)
    assert [item["id"] for item in second] == [item["id"] for item in first]


def test_stale_cache_is_refreshed(cache_file):
    stale_at = wayback._now_utc() - timedelta(days=2)
    stale_payload = {
        "fetched_at": stale_at.isoformat(),
        "releases": [
            {
                "id": "999",
                "date": "1999-01-01",
                "name": "stale release",
                "source": "wayback",
                "attribution": "Esri World Imagery Wayback",
            }
        ],
    }
    cache_file.write_text(json.dumps(stale_payload), encoding="utf-8")

    payload = _selection_payload(
        ("333", "World Imagery (Wayback 2025-01-01)"),
    )
    source = _wayback_source_with(FakeResponse(200, payload=payload))

    releases = source.available_releases(0.0, 0.0, 12)

    assert [item["id"] for item in releases] == ["333"]
    assert all(item["metadata_source"] == "online" for item in releases)
    assert len(source.session.calls) == 1

    refreshed = json.loads(cache_file.read_text(encoding="utf-8"))
    assert refreshed["fetched_at"] != stale_payload["fetched_at"]
    assert [item["id"] for item in refreshed["releases"]] == ["333"]


def test_fallback_marks_source_and_verified_date(cache_file, caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("TiffGetter"), "propagate", True)
    caplog.set_level(logging.WARNING, logger="TiffGetter")
    assert not cache_file.exists()

    source = _wayback_source_with(FakeResponse(500, content=b"server error"))

    releases = source.available_releases(0.0, 0.0, 12)

    assert releases
    assert all(item["metadata_source"] == "fallback" for item in releases)
    assert all(
        item["metadata_fetched_at"] == wayback.KNOWN_WAYBACK_VERIFIED_AT
        for item in releases
    )
    messages = [record.getMessage() for record in caplog.records]
    assert any("最近确认" in message for message in messages)
    assert not cache_file.exists()


def test_release_metadata_fields_present(cache_file):
    payload = _selection_payload(
        ("444", "World Imagery (Wayback 2026-05-28)"),
    )
    source = _wayback_source_with(FakeResponse(200, payload=payload))

    releases = source.available_releases(10.0, 20.0, 8)

    assert len(releases) >= 1
    for item in releases:
        assert "metadata_source" in item
        assert "metadata_fetched_at" in item
