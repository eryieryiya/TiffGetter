"""数据源抽象：统一描述数据源能力与瓦片获取接口。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List

import requests

from core.errors import TileResult


@dataclass(frozen=True)
class SourceInfo:
    """数据源静态能力描述。"""

    name: str
    display_name: str
    supports_history: bool
    min_zoom: int
    max_zoom: int
    max_concurrency: int
    attribution: str
    experimental: bool = False
    usage_note: str = ""
    verify_tls: bool = True


class UnknownSourceError(ValueError):
    """请求了未注册的数据源。"""


def build_session(verify_tls: bool = True) -> requests.Session:
    """创建带重试的 requests 会话（沿用现有 HTTPAdapter 配置）。"""
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=10,
        pool_maxsize=20,
        max_retries=requests.packages.urllib3.util.retry.Retry(
            total=3, backoff_factor=0.5
        ),
    )
    session = requests.Session()
    session.mount('https://', adapter)
    session.verify = verify_tls
    return session


class TileSource(ABC):
    """瓦片数据源接口。

    release 统一结构至少包含 ``id``、``date``、``name``、``source``、
    ``attribution`` 五个字段。
    """

    def __init__(self, info: SourceInfo):
        self.info = info
        self.session = build_session(verify_tls=info.verify_tls)

    @abstractmethod
    def available_releases(self, lat: float, lon: float, zoom: int) -> List[Dict]:
        """返回该坐标可用的 release 列表（按日期升序）。"""

    @abstractmethod
    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> TileResult:
        """下载单张瓦片；失败返回带失败类型的 TileResult。"""
