"""ESRI World Imagery Wayback 数据源。"""
import logging
import re
from typing import Dict, List, Optional

from .xyz import XYZSource

logger = logging.getLogger('TiffGetter')

# ESRI 在线 wayback 服务元数据 endpoint（实测确认）
# 响应 JSON 含 "Selection" 列表：{"Name": "World Imagery (Wayback YYYY-MM-DD)",
#                                  "M": "26334", "ID": "WB_2026_R07"}
WAYBACK_METADATA_URL = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "world_imagery/MapServer?f=json"
)
# 瓦片 URL 主模板（实测可用，wayback_id 即 Selection[].M）
WAYBACK_TILE_URL_TEMPLATE = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "world_imagery/MapServer/tile/{wayback_id}/{z}/{y}/{x}"
)
# 备用 WMTS 模板（wayback-a 子域名，实测同样返回内容）
WAYBACK_TILE_URL_FALLBACK = (
    "https://wayback-a.maptiles.arcgis.com/arcgis/rest/services/"
    "world_imagery/wmts/1.0.0/default028mm/mapserver/tile/"
    "{wayback_id}/{z}/{y}/{x}"
)

# ESRI Wayback 版本列表（fallback 用，仅当在线 endpoint 完全不可用时的最后兜底）
# 仅保留最近确认的 5 条 ID；在线路径优先。
KNOWN_WAYBACK_VERSIONS = [
    {"id": "20512", "date": "2026-05-28"},
    {"id": "32553", "date": "2024-08-15"},
    {"id": "64776", "date": "2023-08-31"},
    {"id": "296", "date": "2023-02-23"},
    {"id": "273", "date": "2023-01-27"},
]


class WaybackSource(XYZSource):
    """从 ESRI 官方 endpoint 动态获取 release，并下载 wayback 瓦片。"""

    # Name 形如 "World Imagery (Wayback 2026-08-05)"
    _DATE_PATTERN = re.compile(r'Wayback[ \(](\d{4}-\d{2}-\d{2})\)')

    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        return WAYBACK_TILE_URL_TEMPLATE.format(
            wayback_id=release.get('id', ''), z=z, y=y, x=x
        )

    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> Optional[bytes]:
        release_id = str(release.get('id', '')).strip()
        if not release_id:
            return None

        content = self._fetch_image(self.build_url(z, x, y, release))
        if content is not None:
            return content

        return self._fetch_image(
            WAYBACK_TILE_URL_FALLBACK.format(
                wayback_id=release_id, z=z, y=y, x=x
            )
        )

    def available_releases(self, lat: float, lon: float, zoom: int) -> List[Dict]:
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
        if not isinstance(zoom, int) or not (1 <= zoom <= 20):
            raise ValueError(f"zoom 越界 {zoom!r}，必须为 1..20 的整数")

        online = self._fetch_online_releases()
        if online:
            logger.info(f"在线元数据返回 {len(online)} 个 release")
            result = online
        else:
            logger.warning("在线元数据不可用，回退到 KNOWN_WAYBACK_VERSIONS")
            result = [
                self._make_release(v['id'], v['date'], v['date'])
                for v in KNOWN_WAYBACK_VERSIONS
            ]

        # 统一按日期升序（最早的在前），使输出子文件夹按时间线排列
        result.sort(key=lambda d: d['date'])
        return result

    def _make_release(self, release_id: str, date: str, name: str,
                      release_code: str = '') -> Dict:
        release = {
            'id': release_id,
            'date': date,
            'name': name,
            'source': self.info.name,
            'attribution': self.info.attribution,
        }
        if release_code:
            release['release_id'] = release_code
        return release

    def _fetch_online_releases(self) -> Optional[List[Dict]]:
        """从 ESRI 官方 endpoint 动态获取 wayback release 列表。

        响应 JSON 结构（实测确认）：
            {"Service": "Wayback", "Selection": [ ... ]}
        其中 Selection 为 release 列表（按日期降序，最新在前），每项形如：
            {"Name": "World Imagery (Wayback 2026-08-05)",
             "M": "26334",
             "ID": "WB_2026_R07"}
        - M   : 瓦片 URL 中使用的数字 ID（即 wayback_id）
        - Name: 展示名，其中含发布日期 "Wayback YYYY-MM-DD"
        - ID  : 发布代号（如 WB_2026_R07）

        网络不可达 / 解析失败时返回 None，调用方回退到 KNOWN_WAYBACK_VERSIONS。
        """
        try:
            resp = self.session.get(WAYBACK_METADATA_URL, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"wayback 元数据返回 HTTP {resp.status_code}")
                return None
            data = resp.json()
        except Exception as e:
            logger.warning(f"无法获取 wayback 元数据: {e}")
            return None

        selection = data.get('Selection')
        if not isinstance(selection, list) or not selection:
            logger.warning("wayback 元数据缺少 Selection 列表，无法解析 release")
            return None

        releases = []
        for item in selection:
            name = str(item.get('Name', ''))
            m_id = str(item.get('M', '')).strip()
            if not m_id:
                continue
            match = self._DATE_PATTERN.search(name)
            date_str = match.group(1) if match else '1970-01-01'
            releases.append(self._make_release(
                m_id, date_str, name, str(item.get('ID', ''))
            ))

        if not releases:
            logger.warning("wayback Selection 中未解析出任何 release id")
            return None

        return releases
