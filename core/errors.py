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


FAILURE_HINTS = {
    FailureKind.NO_RELEASES: '该位置或缩放级别没有可用历史版本，可尝试降低 zoom 或改用其他数据源',
    FailureKind.OUT_OF_RANGE: '坐标或缩放级别超出数据源范围，请调整参数',
    FailureKind.NETWORK: '网络连接失败，请检查网络、代理或 DNS 设置',
    FailureKind.TIMEOUT: '请求超时，请检查网络或代理设置后稍后重试',
    FailureKind.TLS: 'TLS 证书校验失败，请检查系统证书或代理设置',
    FailureKind.HTTP_ERROR: '服务端返回错误状态，请稍后重试或改用其他数据源',
    FailureKind.FORBIDDEN: '访问被拒绝（403），该源可能限制当前区域或请求频率，请稍后重试或改用其他数据源',
    FailureKind.RATE_LIMITED: '请求过多（429），请降低并发数或稍后重试',
    FailureKind.SERVER: '服务端错误（5xx），请稍后重试',
    FailureKind.BLOCKED: '请求被服务商拦截，请降低请求频率或改用其他数据源',
    FailureKind.INVALID_CONTENT: '响应内容不是有效影像，可能被拦截或瓦片地址已失效',
    FailureKind.INCOMPLETE_TILES: '瓦片不完整，部分瓦片缺失，可重试该日期',
    FailureKind.INTERFACE_CHANGED: '外部接口可能已变更（如 Google Earth 非公开接口），请更新程序或改用其他数据源',
    FailureKind.INTERNAL: '程序内部处理失败，请查看日志中的详细错误',
}


def failure_hint(kind) -> str:
    """返回失败类型的操作建议；未知类型返回空字符串。"""
    if isinstance(kind, FailureKind):
        return FAILURE_HINTS.get(kind, '')
    if isinstance(kind, str):
        try:
            return FAILURE_HINTS.get(FailureKind(kind), '')
        except ValueError:
            return ''
    return ''


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
