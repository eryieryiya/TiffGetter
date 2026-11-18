"""Google Earth 日期编码与四叉树路径换算的离线测试。"""

import itertools
import random
import re

import pytest

from providers.google_earth_client import (
    _node_index,
    date_to_hex,
    decode_ge_date,
    encode_ge_date,
    lat_lon_to_quadtree_path,
    quadtree_path_bounds,
    quadtree_path_to_row_col,
    quadtree_path_to_xyz,
    row_col_to_quadtree_path,
    xyz_to_quadtree_path,
)


# ---------------------------------------------------------------------------
# 日期编码 / 解码
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("year", "month", "day"),
    [
        (1970, 1, 1),
        (2000, 2, 29),
        (2014, 12, 31),
        (2023, 6, 15),
        (2030, 11, 30),
        (2047, 1, 31),
    ],
)
def test_encode_decode_roundtrip(year, month, day):
    packed = encode_ge_date(year, month, day)
    assert decode_ge_date(packed) == (year, month, day)


def test_encode_bit_layout():
    year, month, day = 2023, 6, 15
    assert encode_ge_date(year, month, day) == ((year & 0x7FF) << 9) | ((month & 0xF) << 5) | (day & 0x1F)


@pytest.mark.parametrize(
    ("year", "month", "day"),
    [(2000, 1, 1), (2023, 6, 15), (2047, 12, 31)],
)
def test_date_to_hex_is_valid_hex(year, month, day):
    hex_date = date_to_hex(year, month, day)
    assert isinstance(hex_date, str)
    assert re.fullmatch(r"[0-9a-f]+", hex_date)
    assert int(hex_date, 16) == encode_ge_date(year, month, day)


# ---------------------------------------------------------------------------
# XYZ 与四叉树路径互转
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("z", [0, 1, 2, 3, 4, 5])
def test_xyz_quadtree_roundtrip_all_tiles(z):
    n = 1 << z
    for x in range(n):
        for y in range(n):
            path = xyz_to_quadtree_path(x, y, z)
            assert path.startswith("0")
            assert len(path) == z + 1
            assert quadtree_path_to_xyz(path) == (x, y, z)


@pytest.mark.parametrize("z", [8, 12, 18])
def test_xyz_quadtree_roundtrip_sampled_high_zoom(z):
    n = 1 << z
    rng = random.Random(z)
    samples = [(0, 0), (n - 1, 0), (0, n - 1), (n - 1, n - 1)]
    samples += [(rng.randrange(n), rng.randrange(n)) for _ in range(50)]
    for x, y in samples:
        assert quadtree_path_to_xyz(xyz_to_quadtree_path(x, y, z)) == (x, y, z)


# ---------------------------------------------------------------------------
# 等距圆柱行列与四叉树路径互转
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("level", [0, 1, 2, 5, 8])
def test_row_col_roundtrip(level):
    n = 1 << level
    cells = itertools.product(range(n), repeat=2) if level <= 2 else [
        (0, 0), (0, n - 1), (n - 1, 0), (n - 1, n - 1), (n // 2, n // 3)
    ]
    for row, col in cells:
        path = row_col_to_quadtree_path(row, col, level)
        assert len(path) == level + 1
        assert path.startswith("0")
        assert quadtree_path_to_row_col(path) == (row, col, level)


def test_row_col_out_of_range_raises():
    with pytest.raises(ValueError):
        row_col_to_quadtree_path(4, 0, 2)
    with pytest.raises(ValueError):
        row_col_to_quadtree_path(0, 4, 2)
    with pytest.raises(ValueError):
        row_col_to_quadtree_path(0, 0, -1)


def test_quadtree_path_to_row_col_rejects_bad_path():
    with pytest.raises(ValueError):
        quadtree_path_to_row_col("")
    with pytest.raises(ValueError):
        quadtree_path_to_row_col("1")


# ---------------------------------------------------------------------------
# 经纬度直接换算的一致性
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("lat", "lon", "level"),
    [
        (0.0, 0.0, 0),
        (0.0, 0.0, 1),
        (39.9, 116.4, 5),
        (-33.86, 151.21, 10),
        (89.9, 179.9, 7),
        (-90.0, -180.0, 6),
        (90.0, 180.0, 6),
    ],
)
def test_lat_lon_matches_row_col(lat, lon, level):
    n = 1 << level
    row = max(0, min(n - 1, int((lat + 180.0) / 360.0 * n)))
    col = max(0, min(n - 1, int((lon + 180.0) / 360.0 * n)))
    assert lat_lon_to_quadtree_path(lat, lon, level) == row_col_to_quadtree_path(
        row, col, level
    )


@pytest.mark.parametrize(
    ("lat", "lon", "level"),
    [(91.0, 0.0, 5), (-91.0, 0.0, 5), (0.0, 181.0, 5), (0.0, -181.0, 5), (0.0, 0.0, -1)],
)
def test_lat_lon_rejects_invalid_input(lat, lon, level):
    with pytest.raises(ValueError):
        lat_lon_to_quadtree_path(lat, lon, level)


def test_lat_lon_rejects_non_int_level():
    with pytest.raises(ValueError):
        lat_lon_to_quadtree_path(0.0, 0.0, 5.0)


# ---------------------------------------------------------------------------
# 路径边界
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("lat", "lon", "level"),
    [
        (0.0, 0.0, 0),
        (39.9, 116.4, 5),
        (-33.86, 151.21, 10),
        (89.9, 179.9, 7),
        (-90.0, -180.0, 6),
        (90.0, 180.0, 6),
        (-0.0001, 0.0001, 12),
    ],
)
def test_quadtree_path_bounds_contains_point(lat, lon, level):
    path = lat_lon_to_quadtree_path(lat, lon, level)
    min_lat, min_lon, max_lat, max_lon = quadtree_path_bounds(path)

    assert min_lat <= lat <= max_lat
    assert min_lon <= lon <= max_lon
    assert min_lat < max_lat
    assert min_lon < max_lon

    cell = 360.0 / (1 << level)
    assert max_lat - min_lat == pytest.approx(cell)
    assert max_lon - min_lon == pytest.approx(cell)


def test_quadtree_path_bounds_root():
    assert quadtree_path_bounds("0") == (-180.0, -180.0, 180.0, 180.0)


# ---------------------------------------------------------------------------
# 数据包节点索引
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "level", "base_level", "expected"),
    [
        ("0", 0, 0, 0),
        ("01", 1, 0, 2),
        ("012", 2, 0, 11),
        ("0123", 3, 0, 48),
        ("0123", 3, 3, 0),
        ("01230", 4, 3, 1),
        ("012301", 5, 3, 6),
        ("0123012", 6, 3, 27),
        ("01230123", 7, 3, 112),
    ],
)
def test_node_index_expected_offsets(path, level, base_level, expected):
    assert _node_index(path, level, base_level) == expected


def test_node_index_ordinary_packet_spans_all_children():
    indices = {
        _node_index("0123" + "".join(quad), 7, 3)
        for quad in itertools.product("0123", repeat=4)
    }
    assert len(indices) == 256
    assert min(indices) == 85
    assert max(indices) == 340


def test_node_index_children_are_contiguous():
    assert {_node_index("0123" + str(q), 4, 3) for q in range(4)} == {1, 2, 3, 4}


@pytest.mark.parametrize(
    ("path", "level", "base_level"),
    [
        ("01", 1, 2),        # 相对层级为负
        ("012345", 5, 0),    # 相对层级为 5
        ("0123456", 6, 1),   # 相对层级为 5
    ],
)
def test_node_index_invalid_relative_level_raises(path, level, base_level):
    with pytest.raises(ValueError):
        _node_index(path, level, base_level)
