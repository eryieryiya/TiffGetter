# 多数据源影像获取模块（兼容门面，默认 ESRI Wayback）
#
# 历史实现已拆分到 core/ 子模块：
#   core.geo / core.dedup / core.release / core.fetch
# 本文件仅做 re-export，保证 `from satellite_processor import ImageFetcher`
# 以及 `satellite_processor.X` 等旧用法继续可用。
import logging
import time

from core.dedup import (
    DHASH_DUP_THRESHOLD,
    DHASH_SIZE,
    DHASH_TILE_THRESHOLD,
    _hamming,
    compute_dhash_int,
    compute_dhash_int_from_path,
    compute_image_hash,
)
from core.fetch import ImageFetcher, IncompleteTilesError
from core.geo import (
    _buffer_wgs84_rect,
    _center_tile,
    _crop_png_to_wgs84_rect,
    _tile_bounds_wgs84,
    get_tile_coords,
    latlon_to_tile,
    tile_to_lonlat,
)
from core.release import (
    _read_metadata_source,
    filter_releases_by_date_range,
    select_releases,
)

logger = logging.getLogger('TiffGetter')
logger.setLevel(logging.INFO)
# 仅当根 logger 尚未配置时才自建 handler（独立运行 / 单测场景）。
# main.py 入口会先 basicConfig 配置 root(stdout)，此时本 logger 直接
# 传播到 root 即可；否则同一条日志会同时打到 stderr 与 stdout，
# 导致终端与 GUI 日志面板（stderr 并入 stdout）重复显示。
if not logger.handlers and not logging.getLogger().handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.propagate = False

# `time` 由旧版模块级导入保留：测试通过
# `monkeypatch.setattr(satellite_processor.time, "sleep", ...)` 控制重试节奏。
__all__ = [
    "ImageFetcher",
    "IncompleteTilesError",
    "latlon_to_tile",
    "tile_to_lonlat",
    "get_tile_coords",
    "_tile_bounds_wgs84",
    "_buffer_wgs84_rect",
    "_crop_png_to_wgs84_rect",
    "_center_tile",
    "compute_image_hash",
    "compute_dhash_int",
    "compute_dhash_int_from_path",
    "_hamming",
    "DHASH_SIZE",
    "DHASH_DUP_THRESHOLD",
    "DHASH_TILE_THRESHOLD",
    "_read_metadata_source",
    "filter_releases_by_date_range",
    "select_releases",
    "time",
]
