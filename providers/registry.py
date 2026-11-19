"""数据源注册表（简单工厂）。"""
import importlib
from typing import Dict, List, Optional, Type

from .base import SourceInfo, TileSource, UnknownSourceError

DEFAULT_SOURCE = 'wayback'

_SOURCES: Dict[str, SourceInfo] = {
    'wayback': SourceInfo(
        name='wayback',
        display_name='ESRI Wayback',
        supports_history=True,
        min_zoom=1,
        max_zoom=20,
        max_concurrency=10,
        attribution='Esri World Imagery Wayback',
        verify_tls=False,
    ),
    'esri': SourceInfo(
        name='esri',
        display_name='ESRI 当前影像',
        supports_history=False,
        min_zoom=1,
        max_zoom=18,
        max_concurrency=8,
        attribution='Esri World Imagery',
        verify_tls=False,
    ),
    'google': SourceInfo(
        name='google',
        display_name='Google Earth（实验性）',
        supports_history=True,
        min_zoom=1,
        max_zoom=20,
        max_concurrency=4,
        attribution='Google',
        experimental=True,
        usage_note='实验性：使用非公开接口，可能随时失效；不建议用于生产批量任务。',
    ),
    'bing': SourceInfo(
        name='bing',
        display_name='Bing 影像',
        supports_history=False,
        min_zoom=1,
        max_zoom=19,
        max_concurrency=4,
        attribution='Microsoft Bing Maps',
    ),
    'osm': SourceInfo(
        name='osm',
        display_name='OpenStreetMap',
        supports_history=False,
        min_zoom=1,
        max_zoom=19,
        max_concurrency=2,
        attribution='© OpenStreetMap contributors',
        usage_note='OSM 公共瓦片仅适合轻量、单点使用；批量下载请改用 ESRI 或 Bing，否则可能被限流或封禁。',
    ),
}

# 惰性导入映射：避免在注册表加载时引入所有数据源实现。
_FACTORIES: Dict[str, str] = {
    'wayback': 'providers.wayback:WaybackSource',
    'esri': 'providers.esri_current:EsriCurrentSource',
    'bing': 'providers.bing:BingSource',
    'osm': 'providers.osm:OsmSource',
    'google': 'providers.google_earth:GoogleEarthSource',
}


def _load_factory(spec: str) -> Type[TileSource]:
    module_name, _, class_name = spec.partition(':')
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def list_sources() -> List[SourceInfo]:
    """返回全部已注册数据源的静态信息。"""
    return list(_SOURCES.values())


def source_names() -> List[str]:
    """返回全部已注册数据源名称。"""
    return list(_SOURCES.keys())


def source_usage_note(name: Optional[str] = None) -> str:
    """返回数据源的使用边界提示；未知名称返回空字符串。"""
    key = (name or "").strip().lower()
    info = _SOURCES.get(key)
    return info.usage_note if info else ""


def get_source(name: Optional[str] = None) -> TileSource:
    """按名称创建数据源实例；未知名称抛出 UnknownSourceError。"""
    key = (name or DEFAULT_SOURCE).strip().lower()
    if key not in _SOURCES:
        raise UnknownSourceError(
            f"未知数据源: {name!r}，可选: {', '.join(source_names())}"
        )
    factory = _load_factory(_FACTORIES[key])
    return factory(_SOURCES[key])
