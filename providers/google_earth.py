"""Google Earth（实验性）数据源适配器。"""
import io
import logging
import math
import os
import tempfile
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .base import TileSource
from .google_earth_client import (
    GoogleEarthClient,
    lat_lon_to_quadtree_path,
    quadtree_path_bounds,
    row_col_to_quadtree_path,
)

logger = logging.getLogger('TiffGetter')

_RESAMPLE = getattr(Image, 'Resampling', Image).BILINEAR


class GoogleEarthSource(TileSource):
    """把 TimeMachine 客户端适配为统一的 :class:`TileSource`。

    Google Earth 使用等距圆柱四叉树，和管线默认的 Web Mercator XYZ
    不一致。适配器按 XYZ 瓦片的经纬度范围取覆盖的 Google Earth 瓦片，
    拼接后重采样成 256×256，使上层拼接与 GeoTIFF 边界保持正确。
    """

    _CLIENT_TIMEOUT = 20
    _MAX_DATA_LEVEL = 16

    def __init__(self, info):
        super().__init__(info)
        self._client: Optional[GoogleEarthClient] = None
        self._init_attempted = False

    # ------------------------------------------------------------------
    # 客户端懒加载
    # ------------------------------------------------------------------
    def _ensure_client(self) -> Optional[GoogleEarthClient]:
        if self._client is not None:
            return self._client
        if self._init_attempted:
            return None
        self._init_attempted = True
        try:
            client = GoogleEarthClient(timeout=self._CLIENT_TIMEOUT)
            if not client.initialize():
                logger.warning("Google Earth 客户端初始化失败，该数据源暂不可用")
                self._client = None
                return None
            self._client = client
        except Exception as e:
            logger.warning(f"Google Earth 客户端初始化异常: {e}")
            self._client = None
        return self._client

    # ------------------------------------------------------------------
    # release 列表
    # ------------------------------------------------------------------
    def available_releases(self, lat: float, lon: float, zoom: int) -> List[Dict]:
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
        if not isinstance(zoom, int) or not (1 <= zoom <= self.info.max_zoom):
            raise ValueError(
                f"zoom 越界 {zoom!r}，必须为 1..{self.info.max_zoom} 的整数"
            )

        client = self._ensure_client()
        if client is None:
            return []

        dates: List[Dict] = []
        data_level = 0
        for level in self._candidate_levels(zoom):
            path = lat_lon_to_quadtree_path(lat, lon, level)
            try:
                dates = client.get_dates_for_path(path)
            except Exception as e:
                logger.warning(f"Google Earth 历史日期查询失败 (level={level}): {e}")
                dates = []
            if dates:
                data_level = level
                break

        if not dates:
            logger.warning("Google Earth 该位置没有可用历史日期")
            return []

        center_path = lat_lon_to_quadtree_path(lat, lon, data_level)
        current_item = self._latest_working_date(client, center_path, dates)
        cutoff = current_item['date']

        releases: List[Dict] = []
        for item in dates:
            if item['date'] >= cutoff:
                continue
            release = self._to_release(item, data_level)
            if release is not None:
                releases.append(release)

        releases.append({
            'id': 'current',
            'date': cutoff,
            'name': f"当前影像（{cutoff}）",
            'source': self.info.name,
            'attribution': self.info.attribution,
            'ge_level': data_level,
            'is_current': True,
        })
        return releases

    def _latest_working_date(
        self, client: GoogleEarthClient, path: str, dates: List[Dict]
    ) -> Dict:
        """返回中心瓦片真正可下载的最新日期，避免把 404 日期当作 current。"""
        for item in reversed(dates[-5:]):
            fd, tmp_path = tempfile.mkstemp(prefix='ge_probe_', suffix='.jpg')
            os.close(fd)
            try:
                if client.download_tile_for_path(
                    path, item['hex_date'], item['epoch'], tmp_path
                ):
                    with Image.open(tmp_path) as img:
                        extrema = img.convert('RGB').getextrema()
                    if any(high > 0 for _low, high in extrema):
                        return item
            except Exception:
                continue
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return dates[-1]

    def _candidate_levels(self, zoom: int) -> List[int]:
        levels = []
        level = min(zoom, self._MAX_DATA_LEVEL)
        while level >= 5:
            levels.append(level)
            level -= 1
        return levels

    def _to_release(self, item: Dict, ge_level: int) -> Optional[Dict]:
        date_str = str(item.get('date') or '').strip()
        hex_date = str(item.get('hex_date') or '').strip()
        epoch = item.get('epoch')
        if not date_str or not hex_date or epoch is None:
            return None
        try:
            epoch = int(epoch)
        except (TypeError, ValueError):
            return None
        return {
            'id': f"{date_str}-{hex_date}-{epoch}",
            'date': date_str,
            'name': date_str,
            'source': self.info.name,
            'attribution': self.info.attribution,
            'ge_level': ge_level,
            'hex_date': hex_date,
            'epoch': epoch,
        }

    # ------------------------------------------------------------------
    # 瓦片下载
    # ------------------------------------------------------------------
    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> Optional[bytes]:
        try:
            client = self._ensure_client()
            if client is None:
                return None

            ge_level = int(release.get('ge_level') or min(z, self._MAX_DATA_LEVEL))
            date_str = None if release.get('is_current') else release.get('date')
            dst_bounds = self._xyz_tile_bounds(z, x, y)
            paths = self._covering_paths(*dst_bounds, ge_level)
            if not paths:
                return None

            canvas = Image.new('RGB', (256, 256), (0, 0, 0))
            fetched = 0
            for path in paths:
                fd, tmp_path = tempfile.mkstemp(prefix='ge_tile_', suffix='.jpg')
                os.close(fd)
                try:
                    if not client.download_tile_for_date(path, date_str, tmp_path):
                        logger.debug(
                            f"Google Earth 瓦片不可用 {path} date={date_str or 'latest'}"
                        )
                        return None
                    with Image.open(tmp_path) as img:
                        self._paste(
                            canvas,
                            img.convert('RGB'),
                            quadtree_path_bounds(path),
                            dst_bounds,
                        )
                    fetched += 1
                finally:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

            if fetched == 0:
                return None

            buffer = io.BytesIO()
            canvas.save(buffer, format='PNG')
            return buffer.getvalue()
        except Exception as e:
            logger.warning(f"Google Earth 瓦片处理失败 ({z}/{x}/{y}): {e}")
            return None

    @staticmethod
    def _xyz_tile_bounds(z: int, x: int, y: int) -> Tuple[float, float, float, float]:
        """返回 XYZ 瓦片的 WGS84 边界 (min_lon, min_lat, max_lon, max_lat)。"""
        n = 2 ** z
        lon_left = x / n * 360.0 - 180.0
        lon_right = (x + 1) / n * 360.0 - 180.0
        lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return lon_left, lat_bottom, lon_right, lat_top

    @staticmethod
    def _covering_paths(
        lon_left: float, lat_bottom: float, lon_right: float, lat_top: float,
        level: int,
    ) -> List[str]:
        """返回覆盖目标经纬度矩形的 Google Earth 四叉树路径。"""
        n = 1 << level
        eps = 1e-9

        def clamp_col(value: float) -> int:
            return max(0, min(n - 1, int(math.floor(value))))

        col_start = clamp_col((lon_left + 180.0) / 360.0 * n)
        col_end = clamp_col((lon_right - eps + 180.0) / 360.0 * n)
        row_start = clamp_col((lat_bottom + 180.0) / 360.0 * n)
        row_end = clamp_col((lat_top - eps + 180.0) / 360.0 * n)

        paths: List[str] = []
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                paths.append(row_col_to_quadtree_path(row, col, level))
        return paths

    @staticmethod
    def _paste(
        canvas: Image.Image,
        source: Image.Image,
        source_bounds: Tuple[float, float, float, float],
        dest_bounds: Tuple[float, float, float, float],
    ) -> None:
        """把等距圆柱源瓦片的相交区域贴到目标瓦片像素网格。"""
        src_min_lat, src_min_lon, src_max_lat, src_max_lon = source_bounds
        dst_min_lon, dst_min_lat, dst_max_lon, dst_max_lat = dest_bounds

        left = max(src_min_lon, dst_min_lon)
        right = min(src_max_lon, dst_max_lon)
        bottom = max(src_min_lat, dst_min_lat)
        top = min(src_max_lat, dst_max_lat)
        if left >= right or bottom >= top:
            return

        sw, sh = source.size
        dw, dh = canvas.size

        sx0 = (left - src_min_lon) / (src_max_lon - src_min_lon) * sw
        sx1 = (right - src_min_lon) / (src_max_lon - src_min_lon) * sw
        sy0 = (src_max_lat - top) / (src_max_lat - src_min_lat) * sh
        sy1 = (src_max_lat - bottom) / (src_max_lat - src_min_lat) * sh

        dx0 = (left - dst_min_lon) / (dst_max_lon - dst_min_lon) * dw
        dx1 = (right - dst_min_lon) / (dst_max_lon - dst_min_lon) * dw
        dy0 = (dst_max_lat - top) / (dst_max_lat - dst_min_lat) * dh
        dy1 = (dst_max_lat - bottom) / (dst_max_lat - dst_min_lat) * dh

        # 低层级下目标瓦片可能小于一个源像素，至少保留 1 像素再放大。
        if sx1 - sx0 < 1.0:
            center = (sx0 + sx1) / 2.0
            sx0, sx1 = center - 0.5, center + 0.5
        if sy1 - sy0 < 1.0:
            center = (sy0 + sy1) / 2.0
            sy0, sy1 = center - 0.5, center + 0.5

        sx0 = max(0, min(sw - 1, int(math.floor(sx0))))
        sx1 = max(sx0 + 1, min(sw, int(math.ceil(sx1))))
        sy0 = max(0, min(sh - 1, int(math.floor(sy0))))
        sy1 = max(sy0 + 1, min(sh, int(math.ceil(sy1))))
        dx0 = max(0, min(dw - 1, int(round(dx0))))
        dx1 = max(dx0 + 1, min(dw, int(round(dx1))))
        dy0 = max(0, min(dh - 1, int(round(dy0))))
        dy1 = max(dy0 + 1, min(dh, int(round(dy1))))

        crop = source.crop((sx0, sy0, sx1, sy1))
        crop = crop.resize((dx1 - dx0, dy1 - dy0), _RESAMPLE)
        canvas.paste(crop, (dx0, dy0))
