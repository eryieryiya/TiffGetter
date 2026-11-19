"""``fetch_all`` 的日期筛选与去重行为测试。

全部离线：使用实现 ``TileSource`` 的假数据源替换 ``fetcher.source`` /
``fetcher.info``，并把瓦片下载替换为「写出纯色 PNG」，从而真实执行
``fetch_all`` 的去重、日期区间筛选与预填充逻辑（不 mock ``fetch_all`` 本身）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from PIL import Image

import satellite_processor
import utils.cleanup as cleanup_utils
from core.errors import FailureKind, TileBatchStats, TileResult
from providers.base import SourceInfo, TileSource
from satellite_processor import ImageFetcher

LAT, LON, ZOOM = 31.2304, 121.4737, 18
TILE_PX = (256, 256)
TILE_COLOR = (40, 80, 120)


class FakeSource(TileSource):
    """固定返回若干 release 的假数据源（不发起任何网络请求）。"""

    def __init__(self, dates):
        self.info = SourceInfo(
            name="fake",
            display_name="Fake 数据源",
            supports_history=True,
            min_zoom=1,
            max_zoom=20,
            max_concurrency=4,
            attribution="Fake",
        )
        self._dates = list(dates)

    def available_releases(self, lat, lon, zoom):
        return [
            {
                "id": f"rel-{d}",
                "date": d,
                "name": f"Fake {d}",
                "source": self.info.name,
                "attribution": self.info.attribution,
            }
            for d in self._dates
        ]

    def fetch_tile(self, z, x, y, release):
        return TileResult.success(b"fake-tile")


@pytest.fixture
def make_fetcher(fetcher_factory, monkeypatch, tmp_path):
    """构造已接假数据源、且临时目录/GeoTIFF/探针均被隔离的 ImageFetcher。"""

    mkdtemp_root = tmp_path / "_mkdtemp"
    mkdtemp_root.mkdir()
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        cleanup_utils.tempfile,
        "mkdtemp",
        lambda prefix=None, dir=None: real_mkdtemp(prefix=prefix, dir=str(mkdtemp_root)),
    )
    monkeypatch.setattr(satellite_processor.time, "sleep", lambda *_a, **_k: None)
    # 关闭中心瓦片预筛（避免网络），让整图 MD5/dHash 去重逻辑真实执行
    monkeypatch.setattr(
        ImageFetcher, "_fetch_center_tile_dhash", lambda self, *a, **k: None
    )
    # GeoTIFF 输出与本测试无关，降级为仅 PNG（避免依赖 rasterio 写文件）
    monkeypatch.setattr(ImageFetcher, "png_to_geotiff", lambda *a, **k: False)

    def _make(dates, dedup=True, fake_tiles=True):
        fetcher = fetcher_factory(dedup=dedup)
        fake = FakeSource(dates)
        fetcher.source = fake
        fetcher.info = fake.info
        fetcher.thread_pool_size = 2

        def _fake_download(tile_coords, zoom, temp_dir, release):
            os.makedirs(temp_dir, exist_ok=True)
            for x, y in tile_coords:
                Image.new("RGB", TILE_PX, TILE_COLOR).save(
                    os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png"),
                    format="PNG",
                )
            return TileBatchStats(available=len(tile_coords))

        if fake_tiles:
            fetcher.download_tiles_batch = _fake_download
        return fetcher

    return _make


def _output_dirs(output_dir: Path):
    return sorted(
        p.name
        for p in output_dir.iterdir()
        if p.is_dir() and not p.name.startswith("_probe")
    )


def test_fetch_all_keeps_only_earliest_of_identical_imagery(tmp_path, make_fetcher):
    """多期影像完全相同时，仅最早日期落盘，其余标记 duplicate。"""
    dates = ["2015-06-01", "2016-06-01", "2017-06-01"]
    fetcher = make_fetcher(dates)
    out = tmp_path / "out"

    results = fetcher.fetch_all(LAT, LON, ZOOM, str(out), buffer_size=500)

    assert [r["date"] for r in results] == dates
    assert [r["status"] for r in results] == ["success", "duplicate", "duplicate"]
    assert _output_dirs(out) == ["2015-06-01"]
    # 落盘目录的同源 metadata 正确
    meta = json.loads((out / dates[0] / "metadata.json").read_text(encoding="utf-8"))
    assert meta["source"] == "fake"
    assert (out / dates[0] / f"{dates[0]}.png").exists()


def test_fetch_all_range_ignores_older_out_of_range_output(tmp_path, make_fetcher):
    """输出目录已有区间外旧影像时，新区间仍输出区间内最早日期。"""
    out = tmp_path / "out"
    old_dir = out / "2010-01-01"
    old_dir.mkdir(parents=True)
    Image.new("RGB", (64, 64), (1, 2, 3)).save(
        old_dir / "2010-01-01.png", format="PNG"
    )
    (old_dir / "metadata.json").write_text(
        json.dumps({"source": "fake"}), encoding="utf-8"
    )

    dates = ["2014-01-01", "2015-03-01", "2015-09-01", "2016-05-01", "2017-01-01"]
    fetcher = make_fetcher(dates)
    date_range = ("2015-01-01", "2016-12-31")

    results = fetcher.fetch_all(
        LAT, LON, ZOOM, str(out), buffer_size=500, date_range=date_range
    )

    assert [r["date"] for r in results] == ["2015-03-01", "2015-09-01", "2016-05-01"]
    assert results[0]["status"] == "success"
    assert results[0]["date"] == "2015-03-01"
    assert (out / "2015-03-01" / "2015-03-01.png").exists()
    assert all(r["status"] == "duplicate" for r in results[1:])
    # 区间外旧影像未被覆盖，区间外日期也未新增输出
    assert (out / "2010-01-01" / "2010-01-01.png").exists()
    assert _output_dirs(out) == ["2010-01-01", "2015-03-01"]


def test_fetch_all_dedup_disabled_outputs_every_date(tmp_path, make_fetcher):
    """dedup=False 时每个日期都完整输出，即使影像完全相同。"""
    dates = ["2015-06-01", "2016-06-01", "2017-06-01"]
    fetcher = make_fetcher(dates, dedup=False)
    out = tmp_path / "out"

    results = fetcher.fetch_all(
        LAT, LON, ZOOM, str(out), buffer_size=500, dedup=False
    )

    assert [r["status"] for r in results] == ["success"] * 3
    assert _output_dirs(out) == dates
    for d in dates:
        assert (out / d / f"{d}.png").exists()
        assert (out / d / "metadata.json").exists()


def test_fetch_all_no_releases_returns_no_releases(tmp_path, make_fetcher):
    """数据源没有任何 release 时返回单条 NO_RELEASES 失败结果。"""
    fetcher = make_fetcher([])
    out = tmp_path / "out"

    results = fetcher.fetch_all(LAT, LON, ZOOM, str(out), buffer_size=500)

    assert len(results) == 1
    assert results[0]["date"] == "metadata"
    assert results[0]["status"] == "failed"
    assert results[0]["failure_kind"] == FailureKind.NO_RELEASES
    assert results[0]["detail"] == "没有可用 release"
    assert not out.exists()


def test_fetch_all_all_tiles_failed_returns_failure_kind(
    tmp_path, make_fetcher, monkeypatch
):
    """所有瓦片下载失败时结果携带具体失败类型，且不生成日期目录。"""
    fetcher = make_fetcher(["2015-06-01"], fake_tiles=False)
    monkeypatch.setattr(
        fetcher.source,
        "fetch_tile",
        lambda z, x, y, release: TileResult.failure(
            FailureKind.FORBIDDEN, "HTTP 403", http_status=403
        ),
    )
    out = tmp_path / "out"

    results = fetcher.fetch_all(LAT, LON, ZOOM, str(out), buffer_size=500)

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["failure_kind"] == FailureKind.FORBIDDEN
    assert results[0]["detail"] == "HTTP 403"
    assert not (out / "2015-06-01").exists()


def test_write_metadata_includes_diagnostics(tmp_path, fetcher_factory):
    """metadata.json 汇总失败类型计数与样本。"""
    fetcher = fetcher_factory()
    fake = FakeSource(["2015-06-01"])
    release_info = fake.available_releases(LAT, LON, ZOOM)[0]
    date_dir = tmp_path / "2015-06-01"
    date_dir.mkdir()
    bounds = {
        "min_lon": 121.4,
        "min_lat": 31.2,
        "max_lon": 121.5,
        "max_lat": 31.3,
    }
    failures = [
        TileResult.failure(
            FailureKind.FORBIDDEN,
            "HTTP 403",
            url="https://example.invalid/a.png",
            http_status=403,
        ),
        TileResult.failure(
            FailureKind.TIMEOUT,
            "read timeout",
            url="https://example.invalid/b.png",
        ),
    ]

    fetcher._write_metadata(
        str(date_dir), release_info, LAT, LON, ZOOM, 500, bounds,
        "2015-06-01.png", None, failures=failures,
    )

    meta = json.loads((date_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["metadata_source"] == "native"
    assert meta["diagnostics"]["failed_tiles"] == 2
    assert meta["diagnostics"]["by_kind"] == {"forbidden": 1, "timeout": 1}
    assert len(meta["diagnostics"]["samples"]) == 2


def test_download_tiles_batch_returns_stats(tmp_path, fetcher_factory, monkeypatch):
    """download_tiles_batch 统计可用瓦片并收集失败明细。"""
    fetcher = fetcher_factory()
    fake = FakeSource(["2015-06-01"])
    fetcher.source = fake
    fetcher.info = fake.info
    fetcher.thread_pool_size = 1

    def _fetch(z, x, y, release):
        if x == 100:
            return TileResult.success(b"fake-tile-ok")
        return TileResult.failure(FailureKind.TIMEOUT, "read timeout")

    monkeypatch.setattr(fake, "fetch_tile", _fetch)
    temp_dir = tmp_path / "tiles"
    temp_dir.mkdir()

    stats = fetcher.download_tiles_batch(
        [(100, 200), (101, 200)], ZOOM, str(temp_dir),
        {"id": "rel-2015-06-01", "date": "2015-06-01"},
    )

    assert stats.available == 1
    assert len(stats.failures) == 1
    assert stats.failures[0].kind == FailureKind.TIMEOUT
