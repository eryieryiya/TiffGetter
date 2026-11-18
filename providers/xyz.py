"""基于 URL 模板的 XYZ 瓦片数据源。"""
from abc import abstractmethod
from typing import Dict, Optional

from .base import TileSource


class XYZSource(TileSource):
    """用模板方法复用“校验响应并返回字节”的下载流程。

    子类只需实现 :meth:`build_url`。
    """

    def headers(self) -> Dict[str, str]:
        return {'User-Agent': 'TiffGetter/2.0'}

    @abstractmethod
    def build_url(self, z: int, x: int, y: int, release: Dict) -> str:
        """构造瓦片 URL，由子类实现。"""

    def _fetch_image(self, url: str) -> Optional[bytes]:
        """请求并校验单张瓦片；任何失败返回 None。"""
        try:
            resp = self.session.get(url, headers=self.headers(), timeout=60)
            if resp.status_code != 200:
                return None
            content_type = resp.headers.get('Content-Type', '')
            if not content_type.lower().startswith('image/'):
                return None
            if len(resp.content) <= 100:
                return None
            return resp.content
        except Exception:
            return None

    def fetch_tile(self, z: int, x: int, y: int, release: Dict) -> Optional[bytes]:
        url = self.build_url(z, x, y, release)
        if not url:
            return None
        return self._fetch_image(url)
