"""影像获取核心实现包。

子模块职责：
- geo     : 瓦片坐标、WGS84 边界与 PNG 裁剪等纯几何逻辑
- dedup   : 字节级 MD5 / 感知 dHash 去重
- release : metadata 读取与 release 日期筛选
- fetch   : ImageFetcher 下载编排、拼接与 GeoTIFF 输出
"""
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# 与旧版 satellite_processor 保持一致：仅在根 logger 尚未配置时
# （独立运行 / 单测场景）自建 handler，避免日志重复输出。
if not logger.handlers and not logging.getLogger().handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.propagate = False
