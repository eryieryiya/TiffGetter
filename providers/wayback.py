"""ESRI World Imagery Wayback 数据源。"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from core.errors import FailureKind, TileResult

from .xyz import XYZSource

logger = logging.getLogger('TiffGetter')

# 元数据缓存有效期（秒）：24 小时
CACHE_TTL_SECONDS = 24 * 60 * 60
# 元数据磁盘缓存路径（仓库根目录下的 data/cache/wayback_releases.json）
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'cache', 'wayback_releases.json',
)
# 内置兜底列表最近一次人工确认的日期
KNOWN_WAYBACK_VERIFIED_AT = '2026-05-28'

_memory_cache: Optional[List[Dict]] = None
_memory_cached_at: Optional[datetime] = None
_cache_lock = threading.Lock()

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


def _now_utc() -> datetime:
    """返回带 UTC 时区的当前时间。"""
    return datetime.now(timezone.utc)


def _parse_fetched_at(value) -> Optional[datetime]:
    """解析 ISO 8601 时间字符串；失败或缺失时返回 None。

    Args:
        value: 缓存文件中 ``fetched_at`` 字段的原始值。

    Returns:
        带时区的 datetime；无法解析时返回 None。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cache_is_fresh(fetched_at) -> bool:
    """判断缓存获取时间是否仍在 TTL 内。

    Args:
        fetched_at: 缓存写入时间（带时区 datetime）；None 视为过期。

    Returns:
        True 表示未过期，False 表示已过期或无法判断。
    """
    if fetched_at is None:
        return False
    age = _now_utc() - fetched_at
    return age < timedelta(seconds=CACHE_TTL_SECONDS)


def _load_disk_cache() -> Optional[Tuple[List[Dict], datetime]]:
    """读取磁盘元数据缓存，仅在结构合法且未过期时返回。

    Returns:
        (releases, fetched_at)；文件缺失、JSON 损坏、结构非法或已过期时
        返回 None。
    """
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except OSError as e:
        logger.warning(f"读取 wayback 元数据缓存失败: {e}")
        return None
    except ValueError as e:
        logger.warning(f"解析 wayback 元数据缓存失败: {e}")
        return None

    if not isinstance(data, dict):
        return None
    releases = data.get('releases')
    if not isinstance(releases, list) or not releases:
        return None
    if not all(isinstance(item, dict) for item in releases):
        return None

    fetched_at = _parse_fetched_at(data.get('fetched_at'))
    if fetched_at is None or not _cache_is_fresh(fetched_at):
        return None
    return releases, fetched_at


def _save_disk_cache(releases: List[Dict], fetched_at: datetime) -> None:
    """把 release 列表与获取时间写入磁盘缓存。

    Args:
        releases  : 待缓存的 release 字典列表。
        fetched_at: 本次获取时间（带时区 datetime），以 ISO 字符串写入。
    """
    directory = os.path.dirname(CACHE_PATH)
    try:
        os.makedirs(directory, exist_ok=True)
        payload = {'fetched_at': fetched_at.isoformat(), 'releases': releases}
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"写入 wayback 元数据缓存失败: {e}")


def _reset_memory_cache() -> None:
    """清空模块级内存缓存（供测试调用）。"""
    global _memory_cache, _memory_cached_at
    _memory_cache = None
    _memory_cached_at = None


class WaybackSource(XYZSource):
    """从 ESRI 官方 endpoint 动态获取 release，并下载 wayback 瓦片。"""

    # Name 形如 "World Imagery (Wayback 2026-08-05)"
    _DATE_PATTERN = re.compile(r'Wayback[ \(](\d{4}-\d{2}-\d{2})\)')

    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        return WAYBACK_TILE_URL_TEMPLATE.format(
            wayback_id=release.get('id', ''), z=z, y=y, x=x
        )

    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> TileResult:
        release_id = str(release.get('id', '')).strip()
        if not release_id:
            return TileResult.failure(FailureKind.INTERNAL, 'release 缺少 id', url='')

        primary = self._fetch_image(self.build_url(z, x, y, release))
        if primary.ok:
            return primary

        fallback_url = WAYBACK_TILE_URL_FALLBACK.format(
            wayback_id=release_id, z=z, y=y, x=x
        )
        fallback = self._fetch_image(fallback_url)
        if fallback.ok:
            return fallback

        primary_kind = primary.kind.value if primary.kind else 'unknown'
        fallback_kind = fallback.kind.value if fallback.kind else 'unknown'
        detail = (
            f"主模板: {primary_kind} - {primary.detail}; "
            f"备用模板: {fallback_kind} - {fallback.detail}"
        )
        return TileResult.failure(
            fallback.kind if fallback.kind else FailureKind.INTERNAL,
            detail=detail,
            url=fallback_url,
            http_status=fallback.http_status,
        )

    def available_releases(self, lat: float, lon: float, zoom: int) -> List[Dict]:
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
        if not isinstance(zoom, int) or not (1 <= zoom <= 20):
            raise ValueError(f"zoom 越界 {zoom!r}，必须为 1..20 的整数")

        result, source, fetched_at = self._resolve_releases()
        result = [
            dict(item, metadata_source=source, metadata_fetched_at=fetched_at)
            for item in result
        ]
        # 统一按日期升序（最早的在前），使输出子文件夹按时间线排列
        result.sort(key=lambda d: d['date'])
        return result

    def _resolve_releases(self) -> Tuple[List[Dict], str, str]:
        """按内存缓存 → 磁盘缓存 → 在线请求 → 内置兜底的顺序解析 release 列表。

        整段查找与在线请求都在模块级锁内完成，保证同一批量任务只请求一次。

        Returns:
            (releases, source, fetched_at)，其中 source 取值为
            ``'cache'``、``'online'`` 或 ``'fallback'``。
        """
        global _memory_cache, _memory_cached_at
        with _cache_lock:
            if _memory_cache and _cache_is_fresh(_memory_cached_at):
                iso = _memory_cached_at.isoformat()
                logger.info(f"使用缓存的 wayback 元数据（获取于 {iso}）")
                return list(_memory_cache), 'cache', iso

            disk = _load_disk_cache()
            if disk is not None:
                releases, fetched_at = disk
                _memory_cache = releases
                _memory_cached_at = fetched_at
                iso = fetched_at.isoformat()
                logger.info(f"使用缓存的 wayback 元数据（获取于 {iso}）")
                return list(releases), 'cache', iso

            online = self._fetch_online_releases()
            if online:
                logger.info(f"在线元数据返回 {len(online)} 个 release")
                _memory_cache = online
                _memory_cached_at = _now_utc()
                _save_disk_cache(online, _memory_cached_at)
                return list(online), 'online', _memory_cached_at.isoformat()

            logger.warning(
                f"在线元数据与缓存均不可用，回退到内置列表（最近确认 {KNOWN_WAYBACK_VERIFIED_AT}）"
            )
            fallback = [
                self._make_release(v['id'], v['date'], v['date'])
                for v in KNOWN_WAYBACK_VERSIONS
            ]
            return fallback, 'fallback', KNOWN_WAYBACK_VERIFIED_AT

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
