"""ESRI 当前影像（World Imagery）数据源。"""
from typing import Dict, List

from .xyz import XYZSource

ESRI_CURRENT_TILE_URL_TEMPLATE = (
    "https://server.arcgisonline.com/arcgis/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)


class EsriCurrentSource(XYZSource):
    """使用 ArcGIS World Imagery 瓦片地址，仅提供 current 版本。"""

    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        return ESRI_CURRENT_TILE_URL_TEMPLATE.format(z=z, y=y, x=x)

    def available_releases(self, lat: float, lon: float, zoom: int) -> List[Dict]:
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
        if not isinstance(zoom, int) or not (1 <= zoom <= 18):
            raise ValueError(f"zoom 越界 {zoom!r}，必须为 1..18 的整数")

        return [{
            'id': 'current',
            'date': 'current',
            'name': '当前影像',
            'source': self.info.name,
            'attribution': self.info.attribution,
        }]
