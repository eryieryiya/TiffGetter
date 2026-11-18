"""Google Earth（实验性）数据源适配器。"""
import logging
import math
import os
import tempfile
from typing import Dict, List, Optional, Tuple

from .base import TileSource
from .google_earth_client import GoogleEarthClient

logger = logging.getLogger('TiffGetter')


class GoogleEarthSource(TileSource):
    """把旧版 :class:`GoogleEarthClient` 适配为统一的 :class:`TileSource`。

    旧客户端的瓦片下载方法直接把图像写入 ``save_path`` 并返回 bool，
    因此这里用临时文件承接，再读回字节。
    """

    _CLIENT_TIMEOUT = 15

    def __init__(self, info):
        super().__init__(info)
        self._client: Optional[GoogleEarthClient] = None
        self._init_attempted = False

    # ------------------------------------------------------------------
    # 客户端懒加载
    # ------------------------------------------------------------------
    def _ensure_client(self) -> Optional[GoogleEarthClient]:
        """首次使用时初始化客户端；任何失败只记录日志，不向外抛。"""
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

        releases: List[Dict] = []
        client = self._ensure_client()
        if client is not None:
            try:
                x, y = self._lat_lon_to_tile(lat, lon, zoom)
                dates = client.get_dates_for_area(x, y, zoom) or []
                for item in dates:
                    release = self._to_release(item)
                    if release is not None:
                        releases.append(release)
            except Exception as e:
                logger.warning(f"Google Earth 历史日期查询失败: {e}")

        if not releases:
            logger.warning("Google Earth 无可用历史日期，回退到 current 版本")
            return [self._current_release()]

        releases.sort(key=lambda r: r['date'])
        return releases

    def _current_release(self) -> Dict:
        return {
            'id': 'current',
            'date': 'current',
            'name': '当前影像',
            'source': self.info.name,
            'attribution': self.info.attribution,
        }

    def _to_release(self, item: Dict) -> Optional[Dict]:
        """把旧客户端日期字典转换为统一 release。"""
        date_str = str(item.get('date') or '').strip()
        hex_date = str(item.get('hex_date') or '').strip()
        packed = item.get('packed_date')
        if not hex_date and packed is not None:
            try:
                hex_date = format(int(packed), 'x')
            except (TypeError, ValueError):
                hex_date = ''
        epoch = item.get('epoch')
        if not date_str or not hex_date or epoch is None:
            return None
        try:
            epoch = int(epoch)
        except (TypeError, ValueError):
            return None
        return {
            'id': f"{hex_date}-{epoch}",
            'date': date_str,
            'name': date_str,
            'source': self.info.name,
            'attribution': self.info.attribution,
            'hex_date': hex_date,
            'epoch': epoch,
        }

    @staticmethod
    def _parse_history_id(release: Dict) -> Tuple[str, Optional[int]]:
        """从 release 中取出旧客户端需要的 hex_date 与 epoch。"""
        hex_date = str(release.get('hex_date') or '').strip()
        epoch = release.get('epoch')
        if hex_date and epoch is not None:
            try:
                return hex_date, int(epoch)
            except (TypeError, ValueError):
                return '', None

        release_id = str(release.get('id', '')).strip()
        hex_date, sep, epoch_str = release_id.rpartition('-')
        if not sep or not hex_date:
            return '', None
        try:
            return hex_date, int(epoch_str)
        except ValueError:
            return '', None

    # ------------------------------------------------------------------
    # 瓦片下载
    # ------------------------------------------------------------------
    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> Optional[bytes]:
        try:
            client = self._ensure_client()
            if client is None:
                return None

            release_id = str(release.get('id', '')).strip()
            fd, tmp_path = tempfile.mkstemp(prefix='ge_tile_', suffix='.jpg')
            os.close(fd)
            try:
                if release_id == 'current':
                    ok = client.download_current_tile(x, y, z, tmp_path)
                else:
                    hex_date, epoch = self._parse_history_id(release)
                    if not hex_date or epoch is None:
                        return None
                    ok = client.download_historical_tile(
                        x, y, z, hex_date, epoch, tmp_path
                    )
                if not ok:
                    return None
                with open(tmp_path, 'rb') as f:
                    data = f.read()
                return data or None
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning(f"Google Earth 瓦片下载失败 ({z}/{x}/{y}): {e}")
            return None

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """经纬度 → 覆盖该点的 XYZ 瓦片坐标。"""
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        x = max(0, min(int(n) - 1, x))
        y = max(0, min(int(n) - 1, y))
        return x, y
