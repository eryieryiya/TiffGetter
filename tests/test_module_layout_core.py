"""模块拆分后的兼容门面与 core 包布局测试。"""

from __future__ import annotations


def test_facade_exports_image_fetcher():
    from satellite_processor import ImageFetcher

    assert ImageFetcher is not None


def test_image_fetcher_lives_in_core_fetch():
    from satellite_processor import ImageFetcher

    assert ImageFetcher.__module__ == "core.fetch"


def test_core_modules_importable():
    import core.dedup
    import core.geo
    import core.release

    assert core.geo.latlon_to_tile(0.0, 0.0, 1) == (1, 1)
    assert callable(core.dedup.compute_image_hash)
    assert callable(core.release._read_metadata_source)


def test_image_fetcher_public_methods_present():
    from satellite_processor import ImageFetcher

    for name in ("fetch_all", "fetch_batch", "download_image", "compute_dhash_int"):
        assert callable(getattr(ImageFetcher, name))
