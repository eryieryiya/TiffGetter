"""基于 URL 模板的 XYZ 瓦片数据源。"""
import logging
from abc import abstractmethod
from typing import Dict

from core.errors import FailureKind, TileResult, classify_exception

from .base import TileSource


logger = logging.getLogger(__name__)


class XYZSource(TileSource):
    """用模板方法复用“校验响应并返回字节”的下载流程。

    子类只需实现 :meth:`build_url`。
    """

    def __init__(self, info):
        super().__init__(info)
        self._logged_status = set()  # 每种 HTTP 状态只提示一次，避免逐瓦片刷屏

    def headers(self) -> Dict[str, str]:
        return {'User-Agent': 'TiffGetter/2.0'}

    @abstractmethod
    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        """构造瓦片 URL，由子类实现。"""

    def _fetch_image(self, url: str) -> TileResult:
        """请求并校验单张瓦片，返回结构化的 TileResult。"""
        try:
            resp = self.session.get(url, headers=self.headers(), timeout=60)
            if resp.status_code != 200:
                if resp.status_code not in self._logged_status:
                    self._logged_status.add(resp.status_code)
                    if resp.status_code == 403:
                        logger.error(
                            "瓦片请求被拒绝 (403)：服务商可能已限制本机访问。"
                            "OpenStreetMap 要求遵守 tile usage policy，"
                            "请降低频率或改用其它数据源。"
                        )
                    else:
                        logger.warning(
                            f"瓦片请求返回 HTTP {resp.status_code}: {url}"
                        )
                if resp.status_code in (401, 403):
                    kind = FailureKind.FORBIDDEN
                elif resp.status_code == 429:
                    kind = FailureKind.RATE_LIMITED
                elif resp.status_code >= 500:
                    kind = FailureKind.SERVER
                else:
                    kind = FailureKind.HTTP_ERROR
                return TileResult.failure(
                    kind,
                    detail=f"HTTP {resp.status_code}",
                    url=url,
                    http_status=resp.status_code,
                )
            # OSM 拦截时可能用 HTTP 200 返回“Access blocked”图片，
            # 只能通过 X-Blocked 响应头识别。
            blocked = resp.headers.get('X-Blocked')
            if blocked:
                if 'X-Blocked' not in self._logged_status:
                    self._logged_status.add('X-Blocked')
                    logger.error(
                        f"瓦片服务返回拦截页 (X-Blocked): {blocked}。"
                        "请降低请求频率、等待解封，或改用其它数据源。"
                    )
                return TileResult.failure(
                    FailureKind.BLOCKED,
                    detail=f"X-Blocked: {blocked}",
                    url=url,
                    http_status=resp.status_code,
                )
            content_type = resp.headers.get('Content-Type', '')
            if not content_type.lower().startswith('image/'):
                return TileResult.failure(
                    FailureKind.INVALID_CONTENT,
                    detail=f"Content-Type: {content_type}",
                    url=url,
                    http_status=resp.status_code,
                )
            if len(resp.content) <= 100:
                return TileResult.failure(
                    FailureKind.INVALID_CONTENT,
                    detail=f"内容长度 {len(resp.content)} 字节",
                    url=url,
                    http_status=resp.status_code,
                )
            return TileResult.success(resp.content, url)
        except Exception as e:
            kind = classify_exception(e)
            return TileResult.failure(
                kind, detail=f"{type(e).__name__}: {e}", url=url,
            )

    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> TileResult:
        url = self.build_url(z, x, y, release)
        if not url:
            return TileResult.failure(FailureKind.INTERNAL, '空瓦片 URL')
        return self._fetch_image(url)
