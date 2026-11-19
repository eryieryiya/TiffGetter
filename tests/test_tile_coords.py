"""Task 2：瓦片坐标与几何计算测试（纯离线，不访问网络）。

覆盖 ImageFetcher 的：
- latlon_to_tile / tile_to_lonlat
- get_tile_coords
- _tile_bounds_wgs84 / _buffer_wgs84_rect

所有 ImageFetcher 实例均通过 ``fetcher_factory`` 夹具构造，以隔离启动清理逻辑。
"""

from __future__ import annotations

import math

import pytest

# 东京塔（已知点，zoom 17）的预期瓦片坐标
TOKYO_TOWER_LAT = 35.6586
TOKYO_TOWER_LON = 139.7454
TOKYO_TOWER_ZOOM = 17
TOKYO_TOWER_TILE = (116415, 51623)

# Web Mercator 在赤道处的最大纬度（zoom 0 单瓦片顶边）
MERCATOR_MAX_LAT = math.degrees(math.atan(math.sinh(math.pi)))


@pytest.fixture
def fetcher(fetcher_factory):
    """已隔离启动清理的 wayback ImageFetcher。"""
    return fetcher_factory("wayback")


# ----------------------------------------------------------------------
# latlon_to_tile / tile_to_lonlat
# ----------------------------------------------------------------------
def test_latlon_to_tile_known_point_tokyo_tower(fetcher):
    x, y = fetcher.latlon_to_tile(
        TOKYO_TOWER_LAT, TOKYO_TOWER_LON, TOKYO_TOWER_ZOOM
    )
    assert (x, y) == TOKYO_TOWER_TILE


@pytest.mark.parametrize(
    "lat, lon, zoom, expected",
    [
        (0.0, 0.0, 0, (0, 0)),
        (0.0, 0.0, 1, (1, 1)),
        (0.0, 0.0, 2, (2, 2)),
        (0.0, -180.0, 1, (0, 1)),  # 本初子午线以西 + 赤道
        (0.0, 179.9, 1, (1, 1)),   # 接近东经边界
    ],
)
def test_latlon_to_tile_origin_and_zoom_boundaries(fetcher, lat, lon, zoom, expected):
    assert fetcher.latlon_to_tile(lat, lon, zoom) == expected


def test_tile_to_lonlat_known_corners(fetcher):
    # zoom 0 只有一张瓦片：左上角为 (-180, 85.0511...)
    lon, lat = fetcher.tile_to_lonlat(0, 0, 0)
    assert lon == pytest.approx(-180.0)
    assert lat == pytest.approx(MERCATOR_MAX_LAT)

    # zoom 1 的 (1, 1) 瓦片左上角恰为 (0, 0)
    lon, lat = fetcher.tile_to_lonlat(1, 1, 1)
    assert lon == pytest.approx(0.0)
    assert lat == pytest.approx(0.0)

    # zoom 1 的 (0, 0) 瓦片左上角同样是 (-180, 85.0511...)
    lon, lat = fetcher.tile_to_lonlat(0, 0, 1)
    assert lon == pytest.approx(-180.0)
    assert lat == pytest.approx(MERCATOR_MAX_LAT)


@pytest.mark.parametrize(
    "x, y, zoom",
    [
        (0, 0, 0),
        (0, 0, 1),
        (0, 1, 1),
        (1, 0, 1),
        (1, 1, 1),
        (TOKYO_TOWER_TILE[0], TOKYO_TOWER_TILE[1], TOKYO_TOWER_ZOOM),
    ],
)
def test_tile_to_lonlat_corner_is_nw_of_center_and_center_roundtrip(
    fetcher, x, y, zoom
):
    """tile_to_lonlat 返回左上角；左上角位于中心点西北方向；
    取瓦片中心反算应得到同一瓦片。"""
    n = 2.0 ** zoom
    corner_lon, corner_lat = fetcher.tile_to_lonlat(x, y, zoom)

    # 左上角经度 = 瓦片左边界，纬度 = 瓦片上边界
    center_lon = (x + 0.5) / n * 360.0 - 180.0
    center_lat = math.degrees(
        math.atan(math.sinh(math.pi * (1 - 2.0 * (y + 0.5) / n)))
    )

    assert corner_lon == pytest.approx(center_lon - 180.0 / n)
    assert corner_lat > center_lat

    assert fetcher.latlon_to_tile(center_lat, center_lon, zoom) == (x, y)


# ----------------------------------------------------------------------
# get_tile_coords
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "lat, lon, zoom, buffer_size",
    [
        (TOKYO_TOWER_LAT, TOKYO_TOWER_LON, 17, 500),
        (TOKYO_TOWER_LAT, TOKYO_TOWER_LON, 12, 2000),
        (0.0, 0.0, 10, 1000),
        (-33.8688, 151.2093, 15, 800),   # 悉尼（南半球）
        (60.0, -120.0, 8, 5000),
    ],
)
def test_get_tile_coords_range_monotonic_and_nonempty(
    fetcher, lat, lon, zoom, buffer_size
):
    x_min, x_max, y_min, y_max = fetcher.get_tile_coords(
        lat, lon, zoom, buffer_size
    )
    assert x_min <= x_max
    assert y_min <= y_max
    # 范围必须落在该 zoom 的合法瓦片索引内
    limit = 2 ** zoom - 1
    assert 0 <= x_min <= x_max <= limit
    assert 0 <= y_min <= y_max <= limit


@pytest.mark.parametrize(
    "lat, lon, zoom, buffer_size",
    [
        (TOKYO_TOWER_LAT, TOKYO_TOWER_LON, 17, 500),
        (TOKYO_TOWER_LAT, TOKYO_TOWER_LON, 14, 1000),
        (0.0, 0.0, 10, 1000),
        (-33.8688, 151.2093, 15, 800),
        (60.0, -120.0, 8, 5000),
    ],
)
def test_tile_bounds_cover_buffer_rect_within_one_tile(
    fetcher, lat, lon, zoom, buffer_size
):
    x_min, x_max, y_min, y_max = fetcher.get_tile_coords(
        lat, lon, zoom, buffer_size
    )
    min_lon, min_lat, max_lon, max_lat = fetcher._tile_bounds_wgs84(
        x_min, x_max, y_min, y_max, zoom
    )
    clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat = (
        fetcher._buffer_wgs84_rect(lat, lon, buffer_size)
    )

    n = 2.0 ** zoom
    tol_lon = 360.0 / n  # 1 个瓦片的经度跨度
    lat_top = fetcher.tile_to_lonlat(x_min, y_min, zoom)[1]
    lat_bot = fetcher.tile_to_lonlat(x_min, y_min + 1, zoom)[1]
    tol_lat = abs(lat_top - lat_bot)  # 1 个瓦片的纬度跨度

    assert min_lon <= clip_min_lon + tol_lon
    assert max_lon >= clip_max_lon - tol_lon
    assert min_lat <= clip_min_lat + tol_lat
    assert max_lat >= clip_max_lat - tol_lat


def test_get_tile_coords_grows_with_buffer(fetcher):
    lat, lon, zoom = TOKYO_TOWER_LAT, TOKYO_TOWER_LON, 17
    ranges = [
        fetcher.get_tile_coords(lat, lon, zoom, buf)
        for buf in (100, 500, 2000)
    ]

    for smaller, larger in zip(ranges, ranges[1:]):
        assert larger[0] <= smaller[0]  # x_min 只减不增
        assert larger[1] >= smaller[1]  # x_max 只增不减
        assert larger[2] <= smaller[2]  # y_min 只减不增
        assert larger[3] >= smaller[3]  # y_max 只增不减


def test_tile_bounds_degenerate_single_tile(fetcher):
    """单瓦片边界应与 tile_to_lonlat 的四角一致。"""
    zoom = 9
    x, y = 200, 300
    min_lon, min_lat, max_lon, max_lat = fetcher._tile_bounds_wgs84(
        x, x, y, y, zoom
    )
    nw_lon, nw_lat = fetcher.tile_to_lonlat(x, y, zoom)
    se_lon, se_lat = fetcher.tile_to_lonlat(x + 1, y + 1, zoom)

    assert min_lon == pytest.approx(nw_lon)
    assert max_lat == pytest.approx(nw_lat)
    assert max_lon == pytest.approx(se_lon)
    assert min_lat == pytest.approx(se_lat)


# ----------------------------------------------------------------------
# _tile_bounds_wgs84 / _buffer_wgs84_rect 基本性质
# ----------------------------------------------------------------------
def test_tile_bounds_lon_increases_with_x_lat_decreases_with_y(fetcher):
    zoom = 10
    y = 400
    left = fetcher._tile_bounds_wgs84(100, 100, y, y, zoom)
    right = fetcher._tile_bounds_wgs84(101, 101, y, y, zoom)
    assert right[0] > left[0]
    assert right[2] > left[2]

    x = 100
    north = fetcher._tile_bounds_wgs84(x, x, 400, 400, zoom)
    south = fetcher._tile_bounds_wgs84(x, x, 401, 401, zoom)
    assert south[1] < north[1]
    assert south[3] < north[3]


def test_buffer_rect_is_symmetric_around_center(fetcher):
    lat, lon, buffer_size = 35.6586, 139.7454, 500
    clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat = (
        fetcher._buffer_wgs84_rect(lat, lon, buffer_size)
    )

    # 中心点与入参一致
    assert (clip_min_lon + clip_max_lon) / 2 == pytest.approx(lon)
    assert (clip_min_lat + clip_max_lat) / 2 == pytest.approx(lat)

    # 东西、南北半宽各自对称且为正
    half_lon = clip_max_lon - lon
    half_lat = clip_max_lat - lat
    assert half_lon > 0
    assert half_lat > 0
    assert lon - clip_min_lon == pytest.approx(half_lon)
    assert lat - clip_min_lat == pytest.approx(half_lat)

    # 与按米换算的期望值一致（经度按 cos(lat) 修正）
    expected_half_lon = buffer_size / (
        111320.0 * math.cos(math.radians(lat))
    )
    expected_half_lat = buffer_size / 111320.0
    assert half_lon == pytest.approx(expected_half_lon)
    assert half_lat == pytest.approx(expected_half_lat)


def test_buffer_rect_at_equator_has_equal_deg_spans(fetcher):
    """赤道处经度无需 cos 修正，经纬半宽（度）应相等。"""
    buffer_size = 1000
    clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat = (
        fetcher._buffer_wgs84_rect(0.0, 0.0, buffer_size)
    )
    assert (clip_max_lon - clip_min_lon) == pytest.approx(
        clip_max_lat - clip_min_lat
    )
