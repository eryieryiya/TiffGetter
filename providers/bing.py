"""Bing 影像数据源（quadkey 瓦片）。"""
from typing import Dict, List

from .xyz import XYZSource


class BingSource(XYZSource):
    """Bing Maps 影像，仅提供当前影像（无历史版本）。"""

    TILE_URL_TEMPLATE = 'https://t0.tiles.virtualearth.net/tiles/a{quadkey}?g=1'

    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        return self.TILE_URL_TEMPLATE.format(quadkey=self._quadkey(x, y, z))

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

    @staticmethod
    def _quadkey(x: int, y: int, z: int) -> str:
        """按 Bing 规则逐位生成 quadkey。"""
        digits = []
        for i in range(z - 1, -1, -1):
            tx = (x >> i) & 1
            ty = (y >> i) & 1
            digits.append(str(tx + (ty << 1)))
        return ''.join(digits)
