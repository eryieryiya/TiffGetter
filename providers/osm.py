"""OpenStreetMap 标准 XYZ 瓦片数据源。"""
from typing import Dict, List

from .xyz import XYZSource

OSM_TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# OSM 瓦片使用政策要求可识别的 User-Agent 并提供联系方式。
# 详见 https://operations.osmfoundation.org/policies/tiles/
OSM_USER_AGENT = (
    'TiffGetter/2.0 (satellite imagery downloader; '
    '+https://github.com/eryieryiya/TiffGetter)'
)


class OsmSource(XYZSource):
    """使用 OSM 官方瓦片地址，仅提供 current 版本。

    固定使用 ``tile.openstreetmap.org``（官方已不推荐 a/b/c 子域），
    并发上限由 :class:`~providers.base.SourceInfo` 的
    ``max_concurrency=2`` 控制。
    """

    def headers(self) -> Dict[str, str]:
        return {
            'User-Agent': OSM_USER_AGENT,
            'Accept': 'image/png,image/*;q=0.8,*/*;q=0.5',
        }

    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        return OSM_TILE_URL_TEMPLATE.format(z=z, x=x, y=y)

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
