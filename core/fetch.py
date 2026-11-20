# 多数据源影像获取实现（默认 ESRI Wayback）
import os
import time
import json
import concurrent.futures
import math
import shutil
import logging
import re
import importlib.util
import urllib3
from datetime import datetime
from PIL import Image
from typing import List, Dict, Tuple, Optional
import numpy as np
import warnings
from config import WGS84_WKT, THREAD_POOL_SIZE
from core import dedup, geo, release, events
from core.errors import FailureKind, ProviderError, TileBatchStats, failure_hint
from providers.registry import DEFAULT_SOURCE, get_source
from utils.cleanup import (
    cleanup_stale_temp_tiles,
    create_temp_dir,
    touch_temp_heartbeat,
)
warnings.filterwarnings('ignore')

# 仓库根目录（satellite_processor.py 所在目录）：用于启动时扫描残留临时瓦片
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _configure_rasterio_data_paths():
    """将 PROJ/GDAL 数据目录指向 rasterio 自带副本，避免系统 PostgreSQL PROJ 库版本冲突。"""
    spec = importlib.util.find_spec("rasterio")
    if spec is None or not spec.submodule_search_locations:
        return
    package_dir = os.fspath(next(iter(spec.submodule_search_locations)))
    proj_dir = os.path.join(package_dir, "proj_data")
    gdal_dir = os.path.join(package_dir, "gdal_data")
    if os.path.isdir(proj_dir):
        os.environ["PROJ_LIB"] = proj_dir
        os.environ["PROJ_DATA"] = proj_dir
    if os.path.isdir(gdal_dir):
        os.environ["GDAL_DATA"] = gdal_dir


_configure_rasterio_data_paths()

# rasterio 是 GeoTIFF 输出所必需，但部分 Conda 环境可能缺失 expat；
# 采用延迟导入：仅在调用 png_to_geotiff 时尝试 import，
# 让瓦片下载/拼接/批量入口等核心功能在 rasterio 不可用时仍可使用。
_RASTERIO_AVAILABLE = False
try:
    import rasterio  # noqa: F401
    from rasterio.transform import from_bounds
    _RASTERIO_AVAILABLE = True
    HAS_RASTERIO = True
except Exception:
    # rasterio 不可用时降级：仅输出 PNG，不打印导入异常
    rasterio = None
    from_bounds = None
    HAS_RASTERIO = False

# 关闭 ESRI wayback 域名的 SSL 警告（其证书链有时触发告警）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


# 自定义异常：瓦片未下载完整
class IncompleteTilesError(Exception):
    pass


class ImageFetcher:
    def __init__(self, source: str = DEFAULT_SOURCE, dedup: bool = True):
        self.source = get_source(source)
        self.info = self.source.info
        self.dedup = dedup
        # 线程池大小来自 config，并受数据源并发上限约束
        self.thread_pool_size = min(
            THREAD_POOL_SIZE or 10, self.info.max_concurrency
        )
        self._downloaded_hashes = set()         # 字节级 MD5：100% 精确重复
        self._downloaded_dhashes: set = set()   # 感知级 dHash(int)：视觉重复
        self._probe_tile_dhashes: Dict[str, int] = {}  # 预筛：(坐标zoom -> release_id -> tile dhash)
        self._diag_done: set = set()            # zoom×buffer 诊断节流：(zoom,lat1,lon1,buf)

        # 数据源使用边界提示：仅在实例化时打印一次，避免批量任务重复刷屏
        if self.info.usage_note:
            logger.warning(f"数据源提示: {self.info.usage_note}")
        elif self.info.experimental:
            logger.warning(
                f"{self.info.display_name} 为实验性数据源，接口可能随时失效"
            )

        # 启动时自动清理根目录残留的 temp_tiles_*/ 临时瓦片目录
        self._cleanup_residual_temp_tiles()

    # ------------------------------------------------------------------
    # 瓦片坐标 / 边界计算
    # ------------------------------------------------------------------
    @staticmethod
    def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        return geo.latlon_to_tile(lat, lon, zoom)

    @staticmethod
    def tile_to_lonlat(x: int, y: int, zoom: int) -> Tuple[float, float]:
        """瓦片 (x, y) 左上角的 WGS84 经纬度"""
        return geo.tile_to_lonlat(x, y, zoom)

    def get_tile_coords(self, lat: float, lon: float, zoom: int,
                        buffer_size: int = 500) -> Tuple[int, int, int, int]:
        """计算覆盖 (lat, lon) ± buffer 米 范围所需的瓦片坐标范围。

        返回 (x_min, x_max, y_min, y_max)，其中：
        - x_min/x_max 包含两端（含）
        - y_min 是 tile y 的较小值（对应更北 / 更大纬度）
        - y_max 是 tile y 的较大值（对应更南 / 更小纬度）

        注意：
            最终下载范围 = 瓦片拼接后的整块矩形，其大小受 ``zoom`` 级别决定。
            例如 zoom=12 单瓦片在 35°N 约覆盖 16km(EW) × 8km(NS)，
            此时即使 buffer=200m，最终输出也必然 ≥ 单瓦片尺寸。
            若用户希望"输出范围约等于 buffer"，请选择 zoom ≥ 17。
        """
        return geo.get_tile_coords(lat, lon, zoom, buffer_size, self._diag_done)

    def _log_zoom_buffer_diagnostic(self, lat: float, lon: float, zoom: int,
                                    buffer_size: int, cos_lat: float) -> None:
        """首次调用时打印 zoom / buffer 与地面覆盖的对应关系，异常时 WARNING。
        节流键：同一 (zoom, round(lat,1), round(lon,1), buffer_size) 只打印一次。
        """
        geo._log_zoom_buffer_diagnostic(
            lat, lon, zoom, buffer_size, cos_lat, self._diag_done,
        )

    def _tile_bounds_wgs84(self, x_min: int, x_max: int, y_min: int, y_max: int,
                          zoom: int) -> Tuple[float, float, float, float]:
        """基于瓦片四角精确计算覆盖范围的 WGS84 边界。

        返回 (min_lon, min_lat, max_lon, max_lat)。
        """
        return geo._tile_bounds_wgs84(x_min, x_max, y_min, y_max, zoom)

    @staticmethod
    def _buffer_wgs84_rect(lat: float, lon: float,
                           buffer_size: int) -> Tuple[float, float, float, float]:
        """返回 (lat, lon) ± buffer 米 的 WGS84 裁剪矩形：
        (clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat)。
        """
        return geo._buffer_wgs84_rect(lat, lon, buffer_size)

    def _crop_png_to_wgs84_rect(self,
                                png_path: str,
                                canvas_bounds: Tuple[float, float, float, float],
                                clip_rect: Tuple[float, float, float, float],
                                ) -> Tuple[Dict[str, float], Tuple[int, int, int, int], bool]:
        """按 WGS84 裁剪矩形裁剪 PNG 文件（原地覆盖写回）。

        Args:
            png_path      : 待裁剪的 PNG（通常是整张瓦片拼接图）。
            canvas_bounds : 该 PNG 对应的 WGS84 边界 (min_lon, min_lat, max_lon, max_lat)。
            clip_rect     : 用户想要的裁剪矩形 (min_lon, min_lat, max_lon, max_lat)。

        Returns:
            (new_bounds, px_box, did_crop) ——
                new_bounds: 裁剪后实际的 WGS84 边界字典（已按图像像素做整数对齐，
                            可能与 clip_rect 差 ±1 像素对应的度数）。
                px_box    : (left, top, right, bottom) 实际裁剪的像素 box（若未裁剪则为整图 (0,0,w,h)）。
                did_crop  : True 表示实际发生了裁剪（图像尺寸变小）；
                            False 表示 clip_rect 已与画布接近全同，未动文件。
        """
        return geo._crop_png_to_wgs84_rect(png_path, canvas_bounds, clip_rect)

    # ------------------------------------------------------------------
    # 数据源 release 列表
    # ------------------------------------------------------------------
    def get_available_dates(self, lat: float, lon: float, zoom: int = 18) -> List[Dict]:
        # 入参校验
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界: {lat}")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界: {lon}")
        if not (1 <= zoom <= 20):
            raise ValueError(f"zoom 越界: {zoom}")

        logger.info(
            f"查询坐标 ({lat:.6f}, {lon:.6f}) 的 "
            f"{self.info.display_name} 可用版本..."
        )
        result = self.source.available_releases(lat, lon, zoom)
        logger.info(f"找到 {len(result)} 个版本")
        return result

    # ------------------------------------------------------------------
    # 瓦片下载
    # ------------------------------------------------------------------
    def download_tiles_batch(self, tile_coords: List[Tuple[int, int]], zoom: int,
                             temp_dir: str, release: Dict) -> TileBatchStats:
        """并发下载瓦片，返回可用/缓存数量与失败明细。"""
        stats = TileBatchStats()

        def download_one(x, y, z, save_path):
            """下载单张瓦片：成功写入文件并返回结果，失败清理半成品后返回结果。"""
            result = self.source.fetch_tile(z, x, y, release)
            if result.ok and result.content is not None:
                with open(save_path, 'wb') as f:
                    f.write(result.content)
                return result
            # 失败时清理半成品文件
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except OSError:
                    pass
            return result

        tasks = []
        for x, y in tile_coords:
            tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
            if os.path.exists(tile_path) and os.path.getsize(tile_path) > 1000:
                stats.cached += 1
                stats.available += 1
            else:
                tasks.append((x, y, zoom, tile_path))

        if tasks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_pool_size) as ex:
                for i, result in enumerate(ex.map(lambda t: download_one(*t), tasks), 1):
                    if result.ok:
                        stats.available += 1
                    else:
                        stats.failures.append(result)
                    if i % 20 == 0:
                        touch_temp_heartbeat(temp_dir)
        if os.path.isdir(temp_dir):
            touch_temp_heartbeat(temp_dir)
        return stats

    # ------------------------------------------------------------------
    # 拼接
    # ------------------------------------------------------------------
    def stitch_tiles(self, temp_dir: str, expected_tile_count: int,
                     save_path: str) -> Tuple[bool, int]:
        """拼接瓦片到 PNG。

        - 以实际下载到的瓦片坐标范围建画布
        - 若缺失瓦片，抛出 IncompleteTilesError（不输出黑边图）
        - 返回 (success, actual_count)
        """
        try:
            tile_files = [
                f for f in os.listdir(temp_dir)
                if f.startswith('tile_') and f.endswith('.png')
            ]
            if not tile_files:
                return False, 0

            tiles_info = []
            for tf in tile_files:
                parts = tf.replace('tile_', '').replace('.png', '').split('_')
                if len(parts) == 3:
                    tiles_info.append({
                        'x': int(parts[0]),
                        'y': int(parts[1]),
                        'file': os.path.join(temp_dir, tf)
                    })

            if not tiles_info:
                return False, 0

            # 使用实际下载到的瓦片坐标范围
            min_x = min(t['x'] for t in tiles_info)
            max_x = max(t['x'] for t in tiles_info)
            min_y = min(t['y'] for t in tiles_info)
            max_y = max(t['y'] for t in tiles_info)

            actual_count = len(tiles_info)
            if actual_count < expected_tile_count:
                # 缺失瓦片：抛错，不输出黑边 GeoTIFF
                raise IncompleteTilesError(
                    f"瓦片下载不完整：实际 {actual_count}/{expected_tile_count}"
                )

            first_tile = Image.open(tiles_info[0]['file'])
            tw, th = first_tile.size
            first_tile.close()

            # 拼接：y_min（更北的瓦片）贴到图像顶部（y=0）
            canvas_w = (max_x - min_x + 1) * tw
            canvas_h = (max_y - min_y + 1) * th
            result = Image.new('RGB', (canvas_w, canvas_h))

            for tile in tiles_info:
                tile_img = Image.open(tile['file'])
                result.paste(tile_img, ((tile['x'] - min_x) * tw, (tile['y'] - min_y) * th))
                tile_img.close()

            result.save(save_path, 'PNG')
            result.close()
            return True, actual_count
        except IncompleteTilesError:
            raise
        except Exception as e:
            logger.error(f"拼接失败: {e}")
            return False, 0

    # ------------------------------------------------------------------
    # GeoTIFF 输出
    # ------------------------------------------------------------------
    def png_to_geotiff(self, png_path: str, tiff_path: str,
                       bounds: Dict) -> bool:
        if not _RASTERIO_AVAILABLE:
            logger.error("rasterio 不可用，无法生成 GeoTIFF（请安装 rasterio 与 expat）")
            return False
        try:
            with Image.open(png_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                width, height = img.size
                img_array = np.array(img)

            transform = from_bounds(
                bounds['min_lon'], bounds['min_lat'],
                bounds['max_lon'], bounds['max_lat'],
                width, height
            )

            with rasterio.open(
                tiff_path, 'w', driver='GTiff',
                height=height, width=width, count=3,
                dtype=img_array.dtype, crs=rasterio.CRS.from_wkt(WGS84_WKT),
                transform=transform, compress='lzw'
            ) as dst:
                dst.write(img_array[:, :, 0], 1)
                dst.write(img_array[:, :, 1], 2)
                dst.write(img_array[:, :, 2], 3)
            return True
        except Exception as e:
            logger.error(f"转换失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 哈希（字节级 + 感知级）
    # ------------------------------------------------------------------
    DHASH_SIZE = dedup.DHASH_SIZE
    DHASH_DUP_THRESHOLD = dedup.DHASH_DUP_THRESHOLD
    DHASH_TILE_THRESHOLD = dedup.DHASH_TILE_THRESHOLD

    def compute_image_hash(self, image_path: str,
                           chunk_size: int = 1 << 20) -> Optional[str]:
        """字节级 MD5（流式，避免一次读入大文件）。命中即 100% 确定重复。"""
        return dedup.compute_image_hash(image_path, chunk_size)

    @classmethod
    def compute_dhash_int(cls, img) -> Optional[int]:
        """计算 dHash（差异哈希）整数（抗 PNG 编码、JPEG 压缩、色深差异）。

        img: PIL.Image（或任何已打开的图像）。内部会转为 L 并 resize。
        返回 int（DHASH_SIZE^2 bits）。失败返回 None。
        """
        return dedup.compute_dhash_int(img, cls.DHASH_SIZE)

    @classmethod
    def compute_dhash_int_from_path(cls, path: str) -> Optional[int]:
        return dedup.compute_dhash_int_from_path(path, cls.DHASH_SIZE)

    @staticmethod
    def _hamming(a: Optional[int], b: Optional[int]) -> int:
        return dedup._hamming(a, b, ImageFetcher.DHASH_SIZE)

    def _fetch_center_tile_dhash(self, lat: float, lon: float, zoom: int,
                                 release: Dict, temp_root: str) -> Optional[int]:
        """为指定坐标 + release，预下载 1 张「覆盖中心点」的瓦片，返回其 dHash。

        作为 1-tile / ~50KB 量级的预筛；比下完几 MB 整片再发现重复，
        能节省 90%+ 的网络开销。失败返回 None，调用方应放弃预筛。
        """
        try:
            release_id = str(release.get('id', 'unknown')).replace('/', '_')
            x, y = self._center_tile(lat, lon, zoom)
            tmp_dir = os.path.join(temp_root, f"probe_{release_id}")
            os.makedirs(tmp_dir, exist_ok=True)
            save_path = os.path.join(tmp_dir, f"{x}_{y}.png")
            if os.path.exists(save_path) and os.path.getsize(save_path) > 1000:
                pass  # 复用之前探针
            else:
                result = self.source.fetch_tile(zoom, x, y, release)
                if not result.ok or result.content is None:
                    return None
                with open(save_path, 'wb') as f:
                    f.write(result.content)
            with Image.open(save_path) as im:
                return self.compute_dhash_int(im)
        except Exception:
            return None

    @staticmethod
    def _center_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """返回覆盖 (lat, lon, zoom) 的瓦片坐标（int, int）。"""
        return geo._center_tile(lat, lon, zoom)

    def _is_duplicate_image(self, path_or_dhash, byte_hashes=None,
                            dhashes=None, strict: bool = False):
        """判定输入是否与历史记录重复。

        path_or_dhash: 图片路径(str) 或 预计算的 (md5, dhash) 二元组；
        byte_hashes:   字节级 MD5 set；
        dhashes:       感知 dhash int set；
        strict:        False 使用 DHASH_DUP_THRESHOLD；True 更严格（仅 0/1）。
        返回 (is_dup: bool, matched_md5, matched_dhash)。
        """
        return dedup._is_duplicate_image(
            path_or_dhash,
            byte_hashes=byte_hashes,
            dhashes=dhashes,
            strict=strict,
            dup_threshold=self.DHASH_DUP_THRESHOLD,
        )

    # ------------------------------------------------------------------
    # 单日期版本下载主流程
    # ------------------------------------------------------------------
    def download_image(self, lat: float, lon: float, zoom: int,
                       date_info: Dict, output_dir: str,
                       buffer_size: int = 500,
                       probe_root: Optional[str] = None,
                       dedup: bool = True) -> Optional[Dict]:
        """下载单日期版本影像。

        probe_root: 若指定，先下载中心瓦片做 dHash 预筛；命中直接跳过，
                    可节省 90%+ 重复发布的网络/CPU。为 None 则跳过预筛。
        dedup: 是否启用重复检测；False 时跳过中心瓦片预筛与整图去重，
               每个日期都完整下载并输出。

        显式参数：lat / lon / zoom / buffer_size 会在此行同时打印，
                  便于用户一眼核对「级别」与「缓冲距离」是否按预期传递。
        """
        date_str = date_info['date']
        release_id = str(date_info.get('id', ''))

        x_min, x_max, y_min, y_max = self.get_tile_coords(lat, lon, zoom, buffer_size)
        expected_tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
        min_lon, min_lat, max_lon, max_lat = self._tile_bounds_wgs84(
            x_min, x_max, y_min, y_max, zoom
        )
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        ew_m = (max_lon - min_lon) * 111320.0 * cos_lat
        ns_m = (max_lat - min_lat) * 111320.0

        logger.info(
            f"下载 {date_str} (ID: {release_id}) "
            f"[{self.info.display_name}, zoom={zoom}, buffer={buffer_size}m, "
            f"瓦片 {x_max-x_min+1}×{y_max-y_min+1}={expected_tile_count}, "
            f"地面覆盖 ~ {ew_m:.0f}m × {ns_m:.0f}m]"
        )

        # ---------- 0) 预筛：1 张中心瓦片 dHash 短路（避免整片区下载） ----------
        if probe_root and dedup:
            tile_dhash = self._fetch_center_tile_dhash(
                lat, lon, zoom, date_info, probe_root,
            )
            if tile_dhash is not None and self._probe_tile_dhashes:
                for known in self._probe_tile_dhashes.values():
                    if self._hamming(tile_dhash, known) <= self.DHASH_TILE_THRESHOLD:
                        logger.info(
                            f"[预筛-中心瓦片] {date_str} 与已收录版本视觉相同，"
                            f"跳过 (dHash 距离 {self._hamming(tile_dhash, known)})"
                        )
                        self._probe_tile_dhashes.setdefault(release_id, tile_dhash)
                        return {
                            'status': 'duplicate',
                            'date': date_str,
                            'tile_dhash': tile_dhash,
                            'reason': 'precheck-tile-dhash',
                        }
            if tile_dhash is not None:
                self._probe_tile_dhashes.setdefault(release_id, tile_dhash)

        temp_dir = create_temp_dir(os.getcwd(), self.info.name, date_str)

        tile_coords = [(x, y) for x in range(x_min, x_max + 1)
                      for y in range(y_min, y_max + 1)]
        stats = self.download_tiles_batch(tile_coords, zoom, temp_dir, date_info)

        if stats.available == 0:
            first_failure = stats.failures[0] if stats.failures else None
            failure_kind = (
                first_failure.kind if first_failure else FailureKind.INTERNAL
            )
            failure_detail = (
                first_failure.detail if first_failure else '没有可用瓦片'
            )
            logger.error(
                f"瓦片下载失败: {date_str} ({failure_kind.value}: {failure_detail})"
            )
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                'status': 'failed',
                'date': date_str,
                'failure_kind': failure_kind,
                'detail': failure_detail,
                'failures': stats.failures,
            }

        # 精确边界（基于瓦片四角）
        min_lon, min_lat, max_lon, max_lat = self._tile_bounds_wgs84(
            x_min, x_max, y_min, y_max, zoom
        )
        bounds = {
            'min_lon': min_lon,
            'max_lon': max_lon,
            'min_lat': min_lat,
            'max_lat': max_lat,
        }

        # 拼接（缺失瓦片会抛 IncompleteTilesError）
        temp_png_path = os.path.join(temp_dir, f"{date_str}.png")
        try:
            ok, actual_count = self.stitch_tiles(
                temp_dir, expected_tile_count, temp_png_path
            )
        except IncompleteTilesError as e:
            logger.error(f"{date_str}: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                'status': 'failed',
                'date': date_str,
                'failure_kind': FailureKind.INCOMPLETE_TILES,
                'detail': str(e),
                'failures': stats.failures,
            }

        if not ok:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                'status': 'failed',
                'date': date_str,
                'failure_kind': FailureKind.INTERNAL,
                'detail': '拼接失败',
                'failures': stats.failures,
            }

        # ---------- 1) 整图 MD5 + 感知 dHash 双重去重 ----------
        img_md5 = self.compute_image_hash(temp_png_path)
        img_dhash = self.compute_dhash_int_from_path(temp_png_path)
        is_dup = False
        if dedup:
            is_dup, _, _ = self._is_duplicate_image(
                (img_md5, img_dhash),
                byte_hashes=self._downloaded_hashes,
                dhashes=self._downloaded_dhashes,
            )
        if is_dup:
            logger.info(f"[整图去重] {date_str} 与之前版本视觉相同，跳过")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                'status': 'duplicate',
                'hash': img_md5,
                'dhash': img_dhash,
                'date': date_str,
                'failures': stats.failures,
            }

        # ---------- 2) 按用户 buffer 精确裁剪中心矩形（解决低 zoom 单瓦片过大的问题） ----------
        clip_rect = self._buffer_wgs84_rect(lat, lon, buffer_size)
        canvas_bounds = (min_lon, min_lat, max_lon, max_lat)
        try:
            new_bounds, px_box, did_crop = self._crop_png_to_wgs84_rect(
                temp_png_path,
                canvas_bounds,
                clip_rect,
            )
        except ValueError as e:
            logger.error(f"{date_str} 裁剪失败：{e}；回退为输出原始瓦片矩形")
            new_bounds = bounds
            did_crop = False
            px_box = (0, 0, 0, 0)

        # 裁剪后的实际输出范围（米），用于日志
        out_ew_m = (new_bounds['max_lon'] - new_bounds['min_lon']) * 111320.0 * cos_lat
        out_ns_m = (new_bounds['max_lat'] - new_bounds['min_lat']) * 111320.0
        if did_crop:
            logger.info(
                f"[范围] 瓦片覆盖 {ew_m:.0f}×{ns_m:.0f}m → 裁剪后输出 "
                f"{out_ew_m:.0f}×{out_ns_m:.0f}m (px box {px_box})"
            )
        else:
            logger.info(
                f"[范围] 瓦片覆盖 {ew_m:.0f}×{ns_m:.0f}m → 直接输出 "
                f"{out_ew_m:.0f}×{out_ns_m:.0f}m"
            )
        bounds = new_bounds

        # 写入输出
        date_dir = os.path.join(output_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)
        png_path = os.path.join(date_dir, f"{date_str}.png")
        tif_path = os.path.join(date_dir, f"{date_str}.tif")

        if self.png_to_geotiff(temp_png_path, tif_path, bounds):
            # GeoTIFF 成功，复制 PNG 到输出目录
            with open(temp_png_path, 'rb') as src:
                with open(png_path, 'wb') as dst:
                    dst.write(src.read())
            if img_md5:
                self._downloaded_hashes.add(img_md5)
            if img_dhash is not None:
                self._downloaded_dhashes.add(img_dhash)
            shutil.rmtree(temp_dir, ignore_errors=True)
            self._write_metadata(
                date_dir, date_info, lat, lon, zoom, buffer_size, bounds,
                os.path.basename(png_path), os.path.basename(tif_path),
                failures=stats.failures,
            )
            logger.info(
                f"成功: {tif_path} "
                f"[最终覆盖 {out_ew_m:.0f}m(EW) × {out_ns_m:.0f}m(NS)]"
            )
            return {
                'status': 'success',
                'hash': img_md5,
                'dhash': img_dhash,
                'date': date_str,
                'path': tif_path,
                'failures': stats.failures,
            }
        else:
            # GeoTIFF 失败（rasterio 不可用），降级为仅输出 PNG
            logger.warning(f"GeoTIFF 转换失败，降级为仅输出 PNG: {date_str}")
            with open(temp_png_path, 'rb') as src:
                with open(png_path, 'wb') as dst:
                    dst.write(src.read())
            if img_md5:
                self._downloaded_hashes.add(img_md5)
            if img_dhash is not None:
                self._downloaded_dhashes.add(img_dhash)
            shutil.rmtree(temp_dir, ignore_errors=True)
            self._write_metadata(
                date_dir, date_info, lat, lon, zoom, buffer_size, bounds,
                os.path.basename(png_path), None,
                failures=stats.failures,
            )
            logger.info(
                f"成功（仅 PNG）: {png_path} "
                f"[最终覆盖 {out_ew_m:.0f}m(EW) × {out_ns_m:.0f}m(NS)]"
            )
            return {
                'status': 'success',
                'hash': img_md5,
                'dhash': img_dhash,
                'date': date_str,
                'path': png_path,
                'failures': stats.failures,
            }

    def _write_metadata(self, date_dir: str, release: Dict, lat: float, lon: float,
                        zoom: int, buffer_size: int, bounds: Dict,
                        png_name: str, tif_name: Optional[str],
                        failures: Optional[List] = None) -> None:
        """在 release 输出目录写入 metadata.json。"""
        metadata = {
            'source': self.info.name,
            'release_id': release.get('id'),
            'release_date': release.get('date'),
            'attribution': release.get('attribution') or self.info.attribution,
            'metadata_source': release.get('metadata_source', 'native'),
            'metadata_fetched_at': release.get('metadata_fetched_at', ''),
            'lat': lat,
            'lon': lon,
            'zoom': zoom,
            'buffer': buffer_size,
            'bounds': bounds,
            'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'files': {'png': png_name, 'tif': tif_name},
            'diagnostics': self._build_diagnostics(failures or []),
        }
        try:
            with open(os.path.join(date_dir, 'metadata.json'), 'w',
                      encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"写入 metadata.json 失败: {e}")

    @staticmethod
    def _build_diagnostics(failures: List) -> Dict:
        """把瓦片失败结果汇总为 metadata 中的诊断信息。

        Args:
            failures: TileResult 列表，kind 可能为 None。
        Returns:
            含 by_kind（类型 -> 数量）、failed_tiles（总数）、
            samples（前 3 条样本）的字典。
        """
        by_kind = {}
        for failure in failures:
            key = failure.kind.value if failure.kind else 'internal'
            by_kind[key] = by_kind.get(key, 0) + 1
        samples = [
            {
                'kind': failure.kind.value if failure.kind else 'internal',
                'http_status': failure.http_status,
                'url': failure.url,
                'detail': failure.detail,
            }
            for failure in failures[:3]
        ]
        return {
            'by_kind': by_kind,
            'failed_tiles': len(failures),
            'samples': samples,
        }

    @staticmethod
    def _read_metadata_source(date_dir: str) -> str:
        """读取 release 目录的数据源；缺少/损坏 metadata 时按 wayback 处理。"""
        return release._read_metadata_source(date_dir)

    # ------------------------------------------------------------------
    # 批量入口
    # ------------------------------------------------------------------
    def _emit_result(self, result: Dict, coord_index=None) -> None:
        """输出单条 date_result 事件，包含瓦片级失败上下文。"""
        failures = result.get('failures') or []
        tile_counts = {}
        for failure in failures:
            key = failure.kind.value if failure.kind else 'internal'
            tile_counts[key] = tile_counts.get(key, 0) + 1
        samples = [
            {
                'kind': failure.kind.value if failure.kind else 'internal',
                'http_status': failure.http_status,
                'url': failure.url,
                'detail': failure.detail,
            }
            for failure in failures[:3]
        ]
        kind = result.get('failure_kind')
        events.emit({
            'type': 'date_result',
            'coord_index': coord_index,
            'date': result.get('date'),
            'name': result.get('name'),
            'status': result.get('status'),
            'kind': kind.value if isinstance(kind, FailureKind) else None,
            'detail': result.get('detail', ''),
            'path': result.get('file_path'),
            'failed_tiles': len(failures),
            'tile_failure_counts': tile_counts,
            'samples': samples,
        })

    def _emit_results(self, results: List[Dict], coord_index=None) -> None:
        """把结果列表转换为 date_result 事件。

        Args:
            results: fetch_all 返回的结果列表（含 status/date/name/file_path 等）。
            coord_index: 批量模式下该坐标点的 1 起始序号；单点模式为 None。
        Returns:
            None。逐条通过 events.emit 输出 date_result 事件。
        """
        for result in results:
            self._emit_result(result, coord_index)

    def _log_failure_context(self, result: Dict) -> None:
        """在失败结果产生时立即输出分类提示与瓦片上下文。"""
        kind = result.get('failure_kind')
        hint = failure_hint(kind)
        logger.warning(f"[失败] {result.get('date')}: {result.get('detail') or '下载失败'}")
        if hint:
            logger.warning(f"  提示: {hint}")
        failures = result.get('failures') or []
        if failures:
            counts = {}
            for failure in failures:
                key = failure.kind.value if failure.kind else 'internal'
                counts[key] = counts.get(key, 0) + 1
            logger.warning(
                f"  失败瓦片: {len(failures)} 张（"
                f"{', '.join(f'{k}={v}' for k, v in sorted(counts.items()))}）"
            )
            logger.warning(f"  示例: {failures[0].url or '无'}")

    def _record_result(self, results: List[Dict], result: Dict,
                       emit_events: bool, coord_index=None) -> None:
        """记录单条结果；失败时立即提示，按需立即发事件。"""
        results.append(result)
        if result.get('status') == 'failed':
            self._log_failure_context(result)
        if emit_events:
            self._emit_result(result, coord_index)

    def fetch_all(self, lat: float, lon: float, zoom: int = 18,
                  output_dir: str = 'data/output/historical',
                  buffer_size: int = 500,
                  date_range: Optional[Tuple[str, str]] = None,
                  dedup: Optional[bool] = None,
                  emit_events: bool = False,
                  event_coord=None) -> List[Dict]:
        logger.info("=" * 60)
        logger.info(
            f"获取坐标 ({lat:.6f}, {lon:.6f}) 的 {self.info.display_name} 影像"
        )
        logger.info("=" * 60)

        if dedup is None:
            dedup = self.dedup
        if not dedup:
            logger.info("重复检测已关闭：每个历史日期都会单独输出")

        # 清空已下载哈希记录（双重：MD5 + dHash）
        self._downloaded_hashes.clear()
        self._downloaded_dhashes.clear()
        self._probe_tile_dhashes.clear()

        try:
            available = self.get_available_dates(lat, lon, zoom)
        except ProviderError as e:
            logger.error(f"获取版本列表失败: {e.detail}")
            results = [{
                'date': 'metadata',
                'name': self.info.display_name,
                'status': 'failed',
                'file_path': None,
                'failure_kind': e.kind,
                'detail': e.detail,
                'failures': [],
            }]
            self._log_failure_context(results[0])
            if emit_events:
                self._emit_results(results, event_coord)
            return results

        dates = release.select_releases(available, date_range)
        if not dates:
            logger.warning("没有可用 release")
            results = [{
                'date': 'metadata',
                'name': self.info.display_name,
                'status': 'failed',
                'file_path': None,
                'failure_kind': FailureKind.NO_RELEASES,
                'detail': '没有可用 release',
                'failures': [],
            }]
            self._log_failure_context(results[0])
            if emit_events:
                self._emit_results(results, event_coord)
            return results

        # 预筛临时目录：同一坐标点所有 release 共用（1 tile/release，非常小）
        probe_root = os.path.join(
            os.path.abspath(output_dir),
            f"_probe_{zoom}_{lat:.5f}_{lon:.5f}".replace('-', 'm').replace('.', 'p'),
        )
        try:
            os.makedirs(probe_root, exist_ok=True)
        except Exception:
            probe_root = None  # 建目录失败就放弃预筛，不影响主流程

        # 去重代表始终取最早日期：
        # 预填充只纳入「早于本次最早候选日期」且位于请求区间内的同源输出，
        # 避免已有较晚日期（或区间外日期）把区间内更早的影像判为重复而跳过。
        first_candidate = dates[0]['date'] if dates else None
        if not date_range and os.path.exists(output_dir):
            for date_dir in sorted(os.listdir(output_dir)):
                date_dir_path = os.path.join(output_dir, date_dir)
                png_path = os.path.join(date_dir_path, f'{date_dir}.png')
                if not os.path.isdir(date_dir_path) or not os.path.exists(png_path):
                    continue
                if self._read_metadata_source(date_dir_path) != self.info.name:
                    continue
                if first_candidate is not None and date_dir >= first_candidate:
                    continue
                img_md5 = self.compute_image_hash(png_path)
                img_dhash = self.compute_dhash_int_from_path(png_path)
                if img_md5:
                    self._downloaded_hashes.add(img_md5)
                if img_dhash is not None:
                    self._downloaded_dhashes.add(img_dhash)
                logger.info(f"已存在: {date_dir}")

        results = []
        skipped_duplicates = 0
        skipped_existing = 0

        for i, date_info in enumerate(dates, 1):
            date_str = date_info['date']
            logger.info(f"[{i}/{len(dates)}] {date_str}...")

            date_dir = os.path.join(output_dir, date_str)
            png_path = os.path.join(date_dir, f'{date_str}.png')
            tif_path = os.path.join(date_dir, f'{date_str}.tif')

            # ---------- 已有文件：去重 or 直接跳过（仅限同源） ----------
            if os.path.exists(png_path) and \
                    self._read_metadata_source(date_dir) == self.info.name:
                if not dedup:
                    skipped_existing += 1
                    logger.info(f"已存在文件，跳过下载: {date_str}")
                    self._record_result(results, {
                        'date': date_str,
                        'name': date_info.get('name', date_str),
                        'status': 'existing',
                        'file_path': tif_path if os.path.exists(tif_path) else None,
                    }, emit_events, event_coord)
                    continue
                is_dup, img_md5, img_dhash = self._is_duplicate_image(
                    png_path,
                    byte_hashes=self._downloaded_hashes,
                    dhashes=self._downloaded_dhashes,
                )
                if is_dup:
                    logger.info(f"[感知去重] {date_str} 与已保存版本视觉相同，标记重复")
                    skipped_duplicates += 1
                    self._record_result(results, {
                        'date': date_str,
                        'name': date_info.get('name', date_str),
                        'status': 'duplicate',
                        'file_path': tif_path if os.path.exists(tif_path) else None,
                    }, emit_events, event_coord)
                    continue
                # 非重复：把当前文件的 hash 登记，避免新下的覆盖它
                if img_md5:
                    self._downloaded_hashes.add(img_md5)
                if img_dhash is not None:
                    self._downloaded_dhashes.add(img_dhash)
                skipped_existing += 1
                logger.info(f"已存在文件，跳过下载: {date_str}")
                self._record_result(results, {
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'existing',
                    'file_path': tif_path if os.path.exists(tif_path) else None,
                }, emit_events, event_coord)
                continue

            # ---------- 新下载：启用中心瓦片预筛 ----------
            result = self.download_image(
                lat, lon, zoom, date_info, output_dir, buffer_size,
                probe_root=probe_root, dedup=dedup,
            )

            if result is None:
                self._record_result(results, {
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'failed',
                    'file_path': None,
                    'failure_kind': FailureKind.INTERNAL,
                    'detail': '下载返回空结果',
                    'failures': [],
                }, emit_events, event_coord)
            elif result['status'] == 'failed':
                self._record_result(results, {
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'failed',
                    'file_path': None,
                    'failure_kind': result['failure_kind'],
                    'detail': result['detail'],
                    'failures': result['failures'],
                }, emit_events, event_coord)
            elif result['status'] == 'duplicate':
                skipped_duplicates += 1
                self._record_result(results, {
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'duplicate',
                    'file_path': None,
                }, emit_events, event_coord)
            else:
                self._record_result(results, {
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'success',
                    'file_path': result['path'],
                }, emit_events, event_coord)
            time.sleep(0.3)

        # 清理：预筛目录用完即销毁（其内容对用户无意义）
        if probe_root and os.path.exists(probe_root):
            shutil.rmtree(probe_root, ignore_errors=True)

        # ---------- 区间校验：最早保留影像必须落在请求区间内 ----------
        if date_range:
            kept_dates = []
            if os.path.isdir(output_dir):
                for name in os.listdir(output_dir):
                    dir_path = os.path.join(output_dir, name)
                    if not os.path.isdir(dir_path):
                        continue
                    if not os.path.exists(os.path.join(dir_path, f'{name}.png')):
                        continue
                    if self._read_metadata_source(dir_path) != self.info.name:
                        continue
                    if date_range[0] <= name <= date_range[1]:
                        kept_dates.append(name)
            if kept_dates:
                logger.info(
                    f"[区间校验] 区间内最早保留影像日期: {min(kept_dates)}"
                    f"（区间 {date_range[0]} ~ {date_range[1]}）"
                )
            else:
                logger.warning(
                    f"[区间校验] 区间 {date_range[0]} ~ {date_range[1]} 内没有可用影像"
                )

        success = sum(1 for r in results if r['status'] == 'success')
        failed = sum(1 for r in results if r['status'] == 'failed')
        all_failures = []
        for r in results:
            all_failures.extend(r.get('failures') or [])
        failure_counts = {}
        for failure in all_failures:
            key = failure.kind.value if failure.kind else 'internal'
            failure_counts[key] = failure_counts.get(key, 0) + 1

        logger.info(f"\n完成！成功 {success}/{len(results)} 个")
        if skipped_existing > 0:
            logger.info(f"跳过已有文件: {skipped_existing} 个")
        if skipped_duplicates > 0:
            logger.info(f"跳过重复图片: {skipped_duplicates} 个")
        if failed > 0:
            logger.info(f"下载失败: {failed} 个")
        if failure_counts:
            logger.info(
                "失败分类: " + ", ".join(
                    f"{k}={v}" for k, v in sorted(failure_counts.items())
                )
            )

        return results

    # ------------------------------------------------------------------
    # 批量入口（多坐标）
    # ------------------------------------------------------------------
    def fetch_batch(self, coords: List[Dict],
                    output_root: str,
                    zoom: int = 18,
                    buffer_size: int = 500,
                    date_range: Optional[Tuple[str, str]] = None,
                    coord_concurrency: int = 1,
                    dedup: Optional[bool] = None,
                    emit_events: bool = False) -> List[Dict]:
        """批量获取多坐标点的影像。

        Args:
            coords: 由 coordinate_loader.load_coordinates_file 返回的坐标列表，
                    每项必须含 lat, lon；name, id 可选。
            output_root: 批量输出根目录；每个坐标点一个独立子目录。
            zoom, buffer_size, date_range: 同 fetch_all。
            coord_concurrency: 坐标级别并发数；默认 1（串行，避免 ESRI 限流）。

        Returns:
            每个坐标点的 (name, lat, lon, results, output_dir) 元信息列表。
        """
        if not coords:
            logger.warning("批量坐标列表为空")
            return []

        os.makedirs(output_root, exist_ok=True)

        # 实际生效的去重开关：显式入参优先，否则沿用实例配置
        effective_dedup = self.dedup if dedup is None else dedup

        summary = []
        total = len(coords)

        def _process(index: int, coord: Dict) -> Dict:
            """处理单个坐标点（可在线程池中并发执行），返回该坐标的汇总信息。

            Args:
                index: 1 起始的坐标序号，用于日志与 summary。
                coord: 含 lat/lon（必需）及 id/name（可选）的坐标字典。
            Returns:
                含 index/name/lat/lon/output_dir/total_dates/success/failed/results
                的汇总字典。
            """
            i = index
            lat = float(coord['lat'])
            lon = float(coord['lon'])
            raw_id = coord.get('id') or ''
            raw_name = coord.get('name') or ''
            sub = raw_id or raw_name or f"point_{i}_{lat:.6f}_{lon:.6f}"
            # 子目录名清洗（Windows 合法）
            sub = re.sub(r'[\\/:\*\?"<>\|\x00-\x1f]', '_', str(sub))
            sub = sub.replace(' ', '_').strip('._') or f"point_{i}"
            if len(sub) > 64:
                sub = sub[:64].rstrip('._')

            coord_out = os.path.join(output_root, sub)
            os.makedirs(coord_out, exist_ok=True)

            logger.info("=" * 60)
            logger.info(f"[{i}/{total}] 坐标点 {sub} ({lat:.6f}, {lon:.6f})")
            logger.info("=" * 60)

            # 并发时每个坐标使用独立实例，隔离 requests.Session 与去重状态
            if coord_concurrency <= 1:
                worker = self
            else:
                worker = ImageFetcher(source=self.info.name, dedup=effective_dedup)

            try:
                results = worker.fetch_all(
                    lat=lat,
                    lon=lon,
                    zoom=zoom,
                    output_dir=coord_out,
                    buffer_size=buffer_size,
                    date_range=date_range,
                    dedup=effective_dedup,
                    emit_events=emit_events,
                    event_coord=index,
                )
            except ValueError as e:
                logger.error(f"[{i}/{total}] {sub} 坐标越界: {e}")
                results = []

            success_n = sum(1 for r in results if r['status'] == 'success')
            failed_n = sum(1 for r in results if r['status'] == 'failed')
            return {
                'index': i,
                'name': sub,
                'lat': lat,
                'lon': lon,
                'output_dir': coord_out,
                'total_dates': len(results),
                'success': success_n,
                'failed': failed_n,
                'results': results,
            }

        if coord_concurrency <= 1:
            # 串行：按输入顺序逐个处理
            for i, coord in enumerate(coords, start=1):
                summary.append(_process(i, coord))
        else:
            # 并发：按输入顺序提交，按提交顺序收集，保证 summary 与输入同序
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=coord_concurrency
            ) as executor:
                futures = [
                    executor.submit(_process, i, coord)
                    for i, coord in enumerate(coords, start=1)
                ]
                for future in futures:
                    summary.append(future.result())

        total_success = sum(s['success'] for s in summary)
        total_failed = sum(s['failed'] for s in summary)
        logger.info("=" * 60)
        logger.info(f"批量完成！共 {total} 个坐标点")
        logger.info(f"  成功日期版本: {total_success}")
        logger.info(f"  失败日期版本: {total_failed}")
        logger.info("=" * 60)
        return summary

    # ------------------------------------------------------------------
    # 启动时清理残余临时瓦片
    # ------------------------------------------------------------------
    def _cleanup_residual_temp_tiles(self, root_dir: Optional[str] = None):
        """清理根目录下已过期（心跳超时）的 temp_tiles_* 残留目录。

        由 __init__ 自动调用，也可显式传入 root_dir 单独执行；
        活跃目录（心跳新鲜）不会被删除，避免并行进程之间互删正在使用的临时目录。

        Args:
            root_dir: 扫描根目录；默认 BASE_DIR。
        Returns:
            被清理的目录路径列表。
        """
        if root_dir is None:
            try:
                root_dir = BASE_DIR
            except Exception:
                root_dir = os.getcwd()

        removed = cleanup_stale_temp_tiles(root_dir)
        if removed:
            logger.info(f"启动清理临时瓦片: {len(removed)} 个目录")
        return removed
