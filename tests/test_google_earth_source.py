"""Google Earth 数据源适配器的离线单元测试（不触发网络初始化）。"""

import pytest
import requests
from PIL import Image

from core.errors import FailureKind, ProviderError
from providers.base import SourceInfo
from providers.google_earth import GoogleEarthSource
from providers.google_earth_client import quadtree_path_bounds
from providers.registry import get_source

BLACK = (0, 0, 0)


@pytest.fixture
def source():
    instance = get_source("google")
    assert isinstance(instance, GoogleEarthSource)
    return instance


def _solid(size, color):
    return Image.new("RGB", size, color)


# ---------------------------------------------------------------------------
# 注册表与懒加载
# ---------------------------------------------------------------------------
def test_get_source_metadata_without_client_init(source):
    assert isinstance(source.info, SourceInfo)
    assert source.info.name == "google"
    assert source.info.supports_history is True
    assert source.info.max_zoom == 20
    assert source.info.experimental is True
    # 构造过程不得触发网络初始化
    assert source._client is None
    assert source._init_attempted is False


# ---------------------------------------------------------------------------
# 候选层级
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("zoom", "expected"),
    [
        (1, []),
        (4, []),
        (5, [5]),
        (6, [6, 5]),
        (10, [10, 9, 8, 7, 6, 5]),
        (16, list(range(16, 4, -1))),
        (20, list(range(16, 4, -1))),
        (25, list(range(16, 4, -1))),
    ],
)
def test_candidate_levels(source, zoom, expected):
    assert source._candidate_levels(zoom) == expected


def test_candidate_levels_monotonic_and_bounded(source):
    for zoom in range(1, 31):
        levels = source._candidate_levels(zoom)
        assert all(level <= source._MAX_DATA_LEVEL for level in levels)
        assert levels == sorted(levels, reverse=True)
        assert len(levels) == len(set(levels))
        if levels:
            assert levels[-1] == 5


# ---------------------------------------------------------------------------
# XYZ 瓦片边界
# ---------------------------------------------------------------------------
def test_xyz_tile_bounds_root(source):
    lon_left, lat_bottom, lon_right, lat_top = source._xyz_tile_bounds(0, 0, 0)
    assert (lon_left, lon_right) == (-180.0, 180.0)
    assert lat_bottom == pytest.approx(-85.0511288, abs=1e-6)
    assert lat_top == pytest.approx(85.0511288, abs=1e-6)


def test_xyz_tile_bounds_known_tile(source):
    lon_left, lat_bottom, lon_right, lat_top = source._xyz_tile_bounds(2, 1, 1)
    assert lon_left == pytest.approx(-90.0)
    assert lon_right == pytest.approx(0.0)
    assert lat_bottom == pytest.approx(0.0)
    assert lat_top == pytest.approx(66.51326044, abs=1e-6)


@pytest.mark.parametrize(("z", "x", "y"), [(1, 0, 0), (5, 10, 20), (10, 512, 512), (14, 10000, 6000)])
def test_xyz_tile_bounds_ordering(source, z, x, y):
    lon_left, lat_bottom, lon_right, lat_top = source._xyz_tile_bounds(z, x, y)
    assert lon_left < lon_right
    assert lat_bottom < lat_top
    assert lon_right - lon_left == pytest.approx(360.0 / (1 << z))
    assert -180.0 <= lon_left and lon_right <= 180.0
    assert -90.0 < lat_bottom and lat_top < 90.0


# ---------------------------------------------------------------------------
# 覆盖路径
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("z", "x", "y", "level"),
    [
        (3, 0, 0, 5),
        (4, 5, 5, 5),
        (8, 100, 100, 10),
        (10, 512, 512, 12),
        (14, 10000, 6000, 16),
    ],
)
def test_covering_paths_cover_target_tile(source, z, x, y, level):
    lon_left, lat_bottom, lon_right, lat_top = source._xyz_tile_bounds(z, x, y)
    paths = source._covering_paths(lon_left, lat_bottom, lon_right, lat_top, level)

    assert paths
    assert len(paths) == len(set(paths))

    boxes = []
    for path in paths:
        assert path.startswith("0")
        assert len(path) == level + 1
        min_lat, min_lon, max_lat, max_lon = quadtree_path_bounds(path)
        assert min_lat < max_lat
        assert min_lon < max_lon
        # 每个路径都必须与目标瓦片相交
        assert min_lon <= lon_right and max_lon >= lon_left
        assert min_lat <= lat_top and max_lat >= lat_bottom
        boxes.append((min_lat, min_lon, max_lat, max_lon))

    # 所有覆盖路径的并集必须包住目标瓦片
    assert min(box[0] for box in boxes) <= lat_bottom + 1e-6
    assert max(box[2] for box in boxes) >= lat_top - 1e-6
    assert min(box[1] for box in boxes) <= lon_left + 1e-6
    assert max(box[3] for box in boxes) >= lon_right - 1e-6


def test_covering_paths_level_zero_is_root(source):
    assert source._covering_paths(-180.0, -90.0, 180.0, 90.0, 0) == ["0"]


# ---------------------------------------------------------------------------
# 图像粘贴
# ---------------------------------------------------------------------------
def test_paste_full_cover(source):
    canvas = Image.new("RGB", (256, 256), BLACK)
    src = _solid((100, 100), (255, 0, 0))
    source_bounds = (-180.0, -180.0, 180.0, 180.0)
    dest_bounds = (-180.0, -90.0, 180.0, 90.0)
    source._paste(canvas, src, source_bounds, dest_bounds)
    assert canvas.getcolors() == [(256 * 256, (255, 0, 0))]


def test_paste_source_larger_than_destination(source):
    canvas = Image.new("RGB", (64, 64), BLACK)
    src = _solid((512, 512), (0, 0, 255))
    source_bounds = (-180.0, -180.0, 180.0, 180.0)
    dest_bounds = (-180.0, -90.0, 180.0, 90.0)
    source._paste(canvas, src, source_bounds, dest_bounds)
    assert canvas.getcolors() == [(64 * 64, (0, 0, 255))]


def test_paste_partial_overlap_keeps_outside_black(source):
    canvas = Image.new("RGB", (256, 256), BLACK)
    src = _solid((64, 64), (255, 0, 0))
    source_bounds = (0.0, 5.0, 10.0, 10.0)
    dest_bounds = (0.0, 0.0, 10.0, 10.0)
    source._paste(canvas, src, source_bounds, dest_bounds)

    assert canvas.getpixel((200, 128)) == (255, 0, 0)
    assert canvas.getpixel((127, 128)) == BLACK


def test_paste_sub_pixel_region(source):
    """目标矩形远小于源瓦片时，至少落在 1 个目标像素上。"""
    canvas = Image.new("RGB", (256, 256), BLACK)
    src = _solid((2, 2), (255, 0, 255))
    source_bounds = (0.0, 0.0, 1e-7, 1e-7)
    dest_bounds = (-180.0, -90.0, 180.0, 90.0)
    source._paste(canvas, src, source_bounds, dest_bounds)

    assert canvas.getpixel((128, 128)) == (255, 0, 255)
    assert canvas.getpixel((127, 128)) == BLACK
    assert canvas.getpixel((129, 128)) == BLACK
    assert canvas.getpixel((128, 127)) == BLACK


def test_paste_tiny_source_crop_expands_to_one_pixel(source):
    """源瓦片像素远大于目标矩形时，裁剪至少保留 1 个源像素。"""
    canvas = Image.new("RGB", (256, 256), BLACK)
    src = _solid((4, 4), (0, 200, 0))
    source_bounds = (0.0, 0.0, 45.0, 45.0)
    dest_bounds = (0.0, 0.0, 0.001, 0.001)
    source._paste(canvas, src, source_bounds, dest_bounds)

    assert canvas.getpixel((0, 0)) == (0, 200, 0)
    assert canvas.getpixel((255, 255)) == (0, 200, 0)


def test_paste_disjoint_bounds_is_noop(source):
    canvas = Image.new("RGB", (32, 32), BLACK)
    src = _solid((16, 16), (255, 0, 0))
    source._paste(canvas, src, (0.0, 0.0, 10.0, 10.0), (20.0, 20.0, 30.0, 30.0))
    assert canvas.getcolors() == [(32 * 32, BLACK)]


# ---------------------------------------------------------------------------
# release 字段映射
# ---------------------------------------------------------------------------
def test_to_release_maps_all_fields(source):
    item = {"date": "2023-06-15", "hex_date": "fce0f", "epoch": "321"}
    release = source._to_release(item, 12)

    assert release == {
        "id": "2023-06-15-fce0f-321",
        "date": "2023-06-15",
        "name": "2023-06-15",
        "source": "google",
        "attribution": "Google",
        "ge_level": 12,
        "hex_date": "fce0f",
        "epoch": 321,
    }


def test_to_release_strips_whitespace_and_coerces_epoch(source):
    release = source._to_release(
        {"date": " 2020-01-02 ", "hex_date": " abc ", "epoch": 0}, 6
    )
    assert release is not None
    assert release["date"] == "2020-01-02"
    assert release["hex_date"] == "abc"
    assert release["epoch"] == 0


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"date": "2023-06-15"},
        {"date": "2023-06-15", "hex_date": "abc"},
        {"date": "", "hex_date": "abc", "epoch": 1},
        {"date": "2023-06-15", "hex_date": "", "epoch": 1},
        {"date": "2023-06-15", "hex_date": "abc", "epoch": None},
        {"date": "2023-06-15", "hex_date": "abc", "epoch": "not-int"},
    ],
)
def test_to_release_returns_none_for_incomplete_item(source, item):
    assert source._to_release(item, 8) is None


# ---------------------------------------------------------------------------
# 协议错误分类
# ---------------------------------------------------------------------------
def test_client_init_failure_raises_interface_changed(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=30):
            self.last_error = RuntimeError("dbRoot 失败")

        def initialize(self):
            return False

    monkeypatch.setattr("providers.google_earth.GoogleEarthClient", FakeClient)
    source = GoogleEarthSource(get_source("google").info)

    with pytest.raises(ProviderError) as excinfo:
        source.available_releases(0, 0, 10)

    assert excinfo.value.kind == FailureKind.INTERFACE_CHANGED
    assert "dbRoot 失败" in excinfo.value.detail


def test_client_parse_error_raises_interface_changed(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=30):
            self.last_error = None

        def initialize(self):
            return True

        def get_dates_for_path(self, path):
            raise ValueError("packet parse failed")

    monkeypatch.setattr("providers.google_earth.GoogleEarthClient", FakeClient)
    source = GoogleEarthSource(get_source("google").info)

    with pytest.raises(ProviderError) as excinfo:
        source.available_releases(0, 0, 10)

    assert excinfo.value.kind == FailureKind.INTERFACE_CHANGED
    assert "packet parse failed" in excinfo.value.detail


def test_client_network_error_raises_timeout(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=30):
            self.last_error = None

        def initialize(self):
            return True

        def get_dates_for_path(self, path):
            raise requests.exceptions.Timeout("read timeout")

    monkeypatch.setattr("providers.google_earth.GoogleEarthClient", FakeClient)
    source = GoogleEarthSource(get_source("google").info)

    with pytest.raises(ProviderError) as excinfo:
        source.available_releases(0, 0, 10)

    assert excinfo.value.kind == FailureKind.TIMEOUT
    assert "read timeout" in excinfo.value.detail
