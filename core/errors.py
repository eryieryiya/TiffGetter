"""统一的瓦片下载失败分类与结果对象。"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import requests


class FailureKind(str, Enum):
    """瓦片或元数据获取的失败类型。"""
    NO_RELEASES = 'no_releases'
    OUT_OF_RANGE = 'out_of_range'
    NETWORK = 'network'
    TIMEOUT = 'timeout'
    TLS = 'tls'
    HTTP_ERROR = 'http_error'
    FORBIDDEN = 'forbidden'
    RATE_LIMITED = 'rate_limited'
    SERVER = 'server'
    BLOCKED = 'blocked'
    INVALID_CONTENT = 'invalid_content'
    INCOMPLETE_TILES = 'incomplete_tiles'
    INTERFACE_CHANGED = 'interface_changed'
    INTERNAL = 'internal'


RETRYABLE_KINDS = {
    FailureKind.NETWORK,
    FailureKind.TIMEOUT,
    FailureKind.RATE_LIMITED,
    FailureKind.SERVER,
}


def classify_exception(exc: BaseException) -> FailureKind:
    """把 requests 异常映射为失败类型，其余归入 INTERNAL。"""
    if isinstance(exc, requests.exceptions.SSLError):
        return FailureKind.TLS
    if isinstance(exc, requests.exceptions.Timeout):
        return FailureKind.TIMEOUT
    if isinstance(exc, requests.exceptions.RequestException):
        return FailureKind.NETWORK
    return FailureKind.INTERNAL


@dataclass
class TileResult:
    """单张瓦片的请求结果。"""
    ok: bool
    content: Optional[bytes] = None
    kind: Optional[FailureKind] = None
    http_status: Optional[int] = None
    detail: str = ''
    url: str = ''

    @property
    def retryable(self) -> bool:
        """失败是否值得重试。"""
        return self.kind in RETRYABLE_KINDS

    @classmethod
    def success(cls, content: bytes, url: str = '') -> 'TileResult':
        """构造成功结果。"""
        return cls(ok=True, content=content, url=url)

    @classmethod
    def failure(cls, kind: FailureKind, detail: str = '', url: str = '',
                http_status: Optional[int] = None) -> 'TileResult':
        """构造失败结果。"""
        return cls(ok=False, kind=kind, detail=detail, url=url,
                   http_status=http_status)


@dataclass
class TileBatchStats:
    """一组瓦片的下载统计。"""
    available: int = 0
    cached: int = 0
    failures: List[TileResult] = field(default_factory=list)


class ProviderError(Exception):
    """数据源元数据或协议层失败。"""

    def __init__(self, kind: FailureKind, detail: str):
        """保存失败类型与说明。"""
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
