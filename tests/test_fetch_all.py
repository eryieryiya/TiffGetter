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
        return None


@pytest.fixture
def make_fetcher(fetcher_factory, monkeypatch, tmp_path):
    """构造已接假数据源、且临时目录/GeoTIFF/探针均被隔离的 ImageFetcher。"""

    mkdtemp_root = tmp_path / "_mkdtemp"
    mkdtemp_root.mkdir()
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        satellite_processor.tempfile,
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

    def _make(dates, dedup=True):
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
            return len(tile_coords)

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
