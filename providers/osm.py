"""OpenStreetMap 标准 XYZ 瓦片数据源。"""
from typing import Dict, List

from .xyz import XYZSource

OSM_TILE_URL_TEMPLATE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

OSM_USER_AGENT = 'TiffGetter/2.0 (OpenStreetMap tiles; one-shot downloader)'


class OsmSource(XYZSource):
    """使用 OSM 官方瓦片地址，仅提供 current 版本。

    子域按 ``(x + y) % 3`` 轮换 a/b/c；并发上限由
    :class:`~providers.base.SourceInfo` 的 ``max_concurrency=2`` 控制。
    """

    def headers(self) -> Dict[str, str]:
        return {'User-Agent': OSM_USER_AGENT}

    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        subdomain = 'abc'[(x + y) % 3]
        return OSM_TILE_URL_TEMPLATE.format(s=subdomain, z=z, x=x, y=y)

    def available_releases(self, lat: float, lon: float, zoom: int) -> List[Dict]:
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
        if not isinstance(zoom, int) or not (1 <= zoom <= 19):
            raise ValueError(f"zoom 越界 {zoom!r}，必须为 1..19 的整数")

        return [{
            'id': 'current',
            'date': 'current',
            'name': '当前影像',
            'source': self.info.name,
            'attribution': self.info.attribution,
        }]
