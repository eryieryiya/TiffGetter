"""数据源使用边界提示的离线单元测试（不联网、不创建 Tk 窗口）。"""

import logging

import pytest

from providers.registry import get_source, source_usage_note


def test_osm_usage_note_mentions_batch():
    note = get_source("osm").info.usage_note
    assert note
    assert "批量" in note


def test_google_usage_note_mentions_experimental():
    note = get_source("google").info.usage_note
    assert note
    assert "实验性" in note


def test_other_sources_have_empty_usage_note():
    for name in ("wayback", "esri", "bing"):
        assert get_source(name).info.usage_note == ""


def test_source_usage_note_known_and_unknown():
    assert source_usage_note("osm") == get_source("osm").info.usage_note
    assert source_usage_note("google") == get_source("google").info.usage_note
    assert source_usage_note("not-a-source") == ""
    assert source_usage_note() == ""


@pytest.mark.parametrize(
    ("source_name", "keyword"),
    [("osm", "批量"), ("google", "实验性")],
)
def test_fetcher_warns_usage_note_once(
    caplog, monkeypatch, fetcher_factory, source_name, keyword
):
    # satellite_processor 自建 handler 时会关闭传播，这里临时打开以便 caplog 捕获
    logger = logging.getLogger("TiffGetter")
    monkeypatch.setattr(logger, "propagate", True)
    caplog.set_level(logging.WARNING, logger="TiffGetter")

    fetcher = fetcher_factory(source=source_name)

    assert fetcher.info.usage_note
    hits = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and "数据源提示" in record.getMessage()
        and keyword in record.getMessage()
    ]
    assert len(hits) == 1
    assert fetcher.info.usage_note in hits[0]
