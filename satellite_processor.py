# ESRI Wayback 历史影像获取模块
import os
import time
import requests
import concurrent.futures
import math
import shutil
import logging
import hashlib
import re
import urllib3
from PIL import Image
from typing import List, Dict, Tuple, Optional
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# rasterio 是 GeoTIFF 输出所必需，但部分 Conda 环境可能缺失 expat；
# 采用延迟导入：仅在调用 png_to_geotiff 时尝试 import，
# 让瓦片下载/拼接/批量入口等核心功能在 rasterio 不可用时仍可使用。
_RASTERIO_AVAILABLE = False
try:
    import rasterio  # noqa: F401
    from rasterio.transform import from_bounds
    _RASTERIO_AVAILABLE = True
except ImportError:
    rasterio = None
    from_bounds = None

# 关闭 ESRI wayback 域名的 SSL 警告（其证书链有时触发告警）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger('TiffGetter')
logger.setLevel(logging.INFO)
# 仅当根 logger 尚未配置时才自建 handler（独立运行 / 单测场景）。
# main.py 入口会先 basicConfig 配置 root(stdout)，此时本 logger 直接
# 传播到 root 即可；否则同一条日志会同时打到 stderr 与 stdout，
# 导致终端与 GUI 日志面板（stderr 并入 stdout）重复显示。
if not logger.handlers and not logging.getLogger().handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.propagate = False

from config import WGS84_WKT, CONFIG, THREAD_POOL_SIZE

# 自定义异常：瓦片未下载完整
class IncompleteTilesError(Exception):
    pass


# ESRI Wayback 版本列表（fallback 用，仅当在线 endpoint 完全不可用时的最后兜底）
# 仅保留最近确认的 5 条 ID；在线路径优先。
KNOWN_WAYBACK_VERSIONS = [
    {"id": "20512", "date": "2026-05-28"},
    {"id": "32553", "date": "2024-08-15"},
    {"id": "64776", "date": "2023-08-31"},
    {"id": "296", "date": "2023-02-23"},
    {"id": "273", "date": "2023-01-27"},
]


class WaybackImageFetcher:
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

    def __init__(self):
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=3, backoff_factor=0.5
            )
        )
        self.session = requests.Session()
        self.session.mount('https://', adapter)
        self.session.verify = False
        # 从 config 读取线程数，缺省 10
        self.thread_pool_size = CONFIG['processing'].get('thread_pool_size', THREAD_POOL_SIZE) or 10
        self._downloaded_hashes = set()         # 字节级 MD5：100% 精确重复
        self._downloaded_dhashes: set = set()   # 感知级 dHash(int)：视觉重复
        self._probe_tile_dhashes: Dict[str, int] = {}  # 预筛：(坐标zoom -> release_id -> tile dhash)
        self._diag_done: set = set()            # zoom×buffer 诊断节流：(zoom,lat1,lon1,buf)
        self._wayback_tile_url_template = self.WAYBACK_TILE_URL_TEMPLATE

        # 启动时自动清理根目录残留的 temp_tiles_*/ 临时瓦片目录
        self._cleanup_residual_temp_tiles()

    # ------------------------------------------------------------------
    # 瓦片坐标 / 边界计算
    # ------------------------------------------------------------------
    @staticmethod
    def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        xtile = int((lon + 180.0) / 360.0 * n)
        ytile = int(
            (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
            / 2.0 * n
        )
        return xtile, ytile

    @staticmethod
    def tile_to_lonlat(x: int, y: int, zoom: int) -> Tuple[float, float]:
        """瓦片 (x, y) 左上角的 WGS84 经纬度"""
        n = 2.0 ** zoom
        lon = x / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2.0 * y / n)))
        lat = math.degrees(lat_rad)
        return lon, lat

    def get_tile_coords(self, lat: float, lon: float, zoom: int,
                        buffer_size: int = 500) -> Tuple[int, int, int, int]:
        """计算覆盖 (lat, lon) ± buffer 米 范围所需的瓦片坐标范围。

        返回 (x_min, x_max, y_min, y_max)，其中：
        - x_min/x_max 包含两端（含）
        - y_min 是 tile y 的较小值（对应更北 / 更大纬度）
        - y_max 是 tile y 的较大值（对应更南 / 更小纬度）

        注意：
            最终下载范围 = 瓦片拼接后的整块矩形，其大小受 ``zoom`` 级别决定。
            例如 zoom=12 单瓦片在 35°N 约覆盖 16km(EW) × 8km(NS)，
            此时即使 buffer=200m，最终输出也必然 ≥ 单瓦片尺寸。
            若用户希望"输出范围约等于 buffer"，请选择 zoom ≥ 17。
        """
        # ----- 入参硬断言：防止「米被当成度 / 级别当成米」这种灾难级错误 -----
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
        if not isinstance(zoom, int) or not (1 <= zoom <= 22):
            # Esri Wayback 实测支持到 z≤20，这里上限稍微放宽做防御
            raise ValueError(f"zoom 越界 {zoom!r}，必须为 1..22 的整数")
        if not isinstance(buffer_size, int) or not (10 <= buffer_size <= 200000):
            raise ValueError(f"buffer_size 越界 {buffer_size!r}，必须为 10..200000 的整数（米）")

        # 经度方向按纬度做 cos 修正，保证东西向距离正确
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        half_lon_deg = (buffer_size / 2) / (111320.0 * cos_lat)
        half_lat_deg = (buffer_size / 2) / 111320.0

        # ----- 防「buffer_size 被当成度」的二次防线 -----
        # 合法 buffer_size（米）换算后的半纬范围，即使 200km 也只有 ~1.8°；
        # 一旦超过 5°，只可能是「buffer 被当成度」或调用链把 zoom/buffer 传反了。
        if half_lat_deg > 5.0:
            raise ValueError(
                f"buffer_size 换算异常：half_lat_deg={half_lat_deg:.4f}° 过大，"
                f"请确认 buffer_size={buffer_size} 的单位是否为米、"
                f"以及调用时 zoom={zoom} 与 buffer_size 位置是否反传。"
            )

        # ----- zoom×buffer 合理性诊断（首次触发时打印一次） -----
        self._log_zoom_buffer_diagnostic(lat, lon, zoom, buffer_size, cos_lat)

        # 四个角点
        sx_tile, sy_tile = self.latlon_to_tile(lat - half_lat_deg, lon - half_lon_deg, zoom)
        nx_tile, ny_tile = self.latlon_to_tile(lat + half_lat_deg, lon + half_lon_deg, zoom)

        x_min, x_max = min(sx_tile, nx_tile), max(sx_tile, nx_tile)
        # 在 Web Mercator 中，纬度越高 y 越小，因此 y_min = 较大纬度对应的瓦片
        y_min, y_max = min(sy_tile, ny_tile), max(sy_tile, ny_tile)
        return x_min, x_max, y_min, y_max

    def _log_zoom_buffer_diagnostic(self, lat: float, lon: float, zoom: int,
                                    buffer_size: int, cos_lat: float) -> None:
        """首次调用时打印 zoom / buffer 与地面覆盖的对应关系，异常时 WARNING。
        节流键：同一 (zoom, round(lat,1), round(lon,1), buffer_size) 只打印一次。
        """
        key = (zoom, round(lat, 1), round(lon, 1), buffer_size)
        already = key in self._diag_done
        if already:
            return

        # 估算该 zoom 级单瓦片在 (lat, lon) 附近的大致地面覆盖尺寸
        n = 2.0 ** zoom
        one_tile_lon_deg = 360.0 / n
        # 纬度方向用相邻两张瓦片的纬度差近似（Mercator 非线性，但取局部差足够）
        x_tile, y_tile = self.latlon_to_tile(lat, lon, zoom)
        _lon1, lat_top = self.tile_to_lonlat(x_tile, y_tile, zoom)
        _lon2, lat_bot = self.tile_to_lonlat(x_tile, y_tile + 1, zoom)
        one_tile_ns_m = abs(lat_top - lat_bot) * 111320.0
        one_tile_ew_m = one_tile_lon_deg * 111320.0 * cos_lat

        # 单瓦片覆盖 与 buffer 的比值（判断 buffer 是否有意义）
        ratio_ns = one_tile_ns_m / max(buffer_size, 1)
        ratio_ew = one_tile_ew_m / max(buffer_size, 1)
        ratio = max(ratio_ns, ratio_ew)

        msg = (
            f"[瓦片粒度诊断] zoom={zoom}, buffer={buffer_size}m, "
            f"单瓦片≈ {one_tile_ew_m:.0f}m(EW) × {one_tile_ns_m:.0f}m(NS)；"
        )
        if ratio <= 4.0:
            logger.info(msg + f"单瓦片/缓冲 ≈ {ratio:.1f}×，覆盖范围将与 buffer 匹配 ✓")
        elif ratio <= 20.0:
            logger.warning(
                msg
                + f"单瓦片/缓冲 ≈ {ratio:.1f}×，最终输出 ≈ 单瓦片粒度（比 buffer 大）。"
                + " 若希望更小范围，请提高 zoom。"
            )
        else:
            logger.warning(
                msg
                + f"单瓦片/缓冲 ≈ {ratio:.0f}×！！！"
                + f" 此时 buffer={buffer_size}m 远小于 zoom={zoom} 的瓦片粒度，"
                + " 输出影像将覆盖 10+km 级别的范围（与 buffer 数值完全不匹配）。"
                + " 请大幅提高 zoom 级别（建议 zoom ≥ 17）或增大 buffer_size。"
            )
        self._diag_done.add(key)

    def _tile_bounds_wgs84(self, x_min: int, x_max: int, y_min: int, y_max: int,
                          zoom: int) -> Tuple[float, float, float, float]:
        """基于瓦片四角精确计算覆盖范围的 WGS84 边界。

        返回 (min_lon, min_lat, max_lon, max_lat)。
        """
        # y_min 是更靠北的瓦片（更小 y），其顶边 = max_lat
        # y_max 是更靠南的瓦片（更大 y），其底边 = min_lat
        lon_nw, lat_nw = self.tile_to_lonlat(x_min, y_min, zoom)
        lon_se, lat_se = self.tile_to_lonlat(x_max + 1, y_max + 1, zoom)
        min_lon = lon_nw
        max_lon = lon_se
        max_lat = lat_nw
        min_lat = lat_se
        return min_lon, min_lat, max_lon, max_lat

    @staticmethod
    def _buffer_wgs84_rect(lat: float, lon: float,
                           buffer_size: int) -> Tuple[float, float, float, float]:
        """返回 (lat, lon) ± buffer 米 的 WGS84 裁剪矩形：
        (clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat)。
        """
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        half_lon = (buffer_size / 2.0) / (111320.0 * cos_lat)
        half_lat = (buffer_size / 2.0) / 111320.0
        clip_min_lon = lon - half_lon
        clip_max_lon = lon + half_lon
        clip_min_lat = lat - half_lat  # 更南
        clip_max_lat = lat + half_lat  # 更北
        return clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat

    def _crop_png_to_wgs84_rect(self,
                                png_path: str,
                                canvas_bounds: Tuple[float, float, float, float],
                                clip_rect: Tuple[float, float, float, float],
                                ) -> Tuple[Dict[str, float], Tuple[int, int, int, int], bool]:
        """按 WGS84 裁剪矩形裁剪 PNG 文件（原地覆盖写回）。

        Args:
            png_path      : 待裁剪的 PNG（通常是整张瓦片拼接图）。
            canvas_bounds : 该 PNG 对应的 WGS84 边界 (min_lon, min_lat, max_lon, max_lat)。
            clip_rect     : 用户想要的裁剪矩形 (min_lon, min_lat, max_lon, max_lat)。

        Returns:
            (new_bounds, px_box, did_crop) ——
                new_bounds: 裁剪后实际的 WGS84 边界字典（已按图像像素做整数对齐，
                            可能与 clip_rect 差 ±1 像素对应的度数）。
                px_box    : (left, top, right, bottom) 实际裁剪的像素 box（若未裁剪则为整图 (0,0,w,h)）。
                did_crop  : True 表示实际发生了裁剪（图像尺寸变小）；
                            False 表示 clip_rect 已与画布接近全同，未动文件。
        """
        from PIL import Image

        c_min_lon, c_min_lat, c_max_lon, c_max_lat = canvas_bounds
        k_min_lon, k_min_lat, k_max_lon, k_max_lat = clip_rect

        # --- 与画布求交集（防御性：裁剪矩形不应超出 PNG 地理覆盖） ---
        #   命名统一：min_lon=西（小经度/左）、max_lon=东（大经度/右）、
        #            min_lat=南（小纬度/下）、max_lat=北（大纬度/上）
        i_min_lon = max(c_min_lon, k_min_lon)   # 交集西边界 = 两者西边中更东的那个
        i_max_lon = min(c_max_lon, k_max_lon)   # 交集东边界 = 两者东边中更西的那个
        i_min_lat = max(c_min_lat, k_min_lat)   # 交集南边界 = 两者南边中更北的那个（数值更大）
        i_max_lat = min(c_max_lat, k_max_lat)   # 交集北边界 = 两者北边中更南的那个（数值更小）
        # 判空：西 ≥ 东  或  南 ≥ 北
        if i_max_lon <= i_min_lon or i_min_lat >= i_max_lat:
            raise ValueError(
                f"裁剪矩形与画布无交集：clip={clip_rect}, canvas={canvas_bounds}"
            )

        with Image.open(png_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            w, h = img.size
            lon_per_px = (c_max_lon - c_min_lon) / float(w)
            lat_per_px = (c_max_lat - c_min_lat) / float(h)  # >0（度/像素向下）

            # 图像左上角 = (c_min_lon, c_max_lat)，向下 y+ → 纬度减小
            px_left_f   = (i_min_lon - c_min_lon) / lon_per_px
            px_right_f  = (i_max_lon - c_min_lon) / lon_per_px
            px_top_f    = (c_max_lat - i_max_lat) / lat_per_px   # max_lat 为更北（图像顶部），减去大纬度得 top
            px_bottom_f = (c_max_lat - i_min_lat) / lat_per_px   # 减去小纬度得到 bottom（更大 y）

            # --- 判断是否"基本没裁"：交集 ≈ 画布（<1px 差异）就直接跳过 ---
            no_crop_east  = (abs(px_left_f)       < 0.95) and (abs(w - px_right_f)  < 0.95)
            no_crop_north = (abs(px_top_f)        < 0.95) and (abs(h - px_bottom_f) < 0.95)
            if no_crop_east and no_crop_north:
                new_bounds = {
                    'min_lon': c_min_lon, 'min_lat': c_min_lat,
                    'max_lon': c_max_lon, 'max_lat': c_max_lat,
                }
                return new_bounds, (0, 0, w, h), False

            # --- 像素取整（floor(左/上)、ceil(右/下) 保证覆盖 clip 矩形，±1px 无差） ---
            px_left   = max(0, int(math.floor(px_left_f)))
            px_top    = max(0, int(math.floor(px_top_f)))
            px_right  = min(w, int(math.ceil(px_right_f)))
            px_bottom = min(h, int(math.ceil(px_bottom_f)))
            # 保证 1px 以上尺寸
            px_right  = max(px_right,  px_left   + 1)
            px_bottom = max(px_bottom, px_top    + 1)

            cropped = img.crop((px_left, px_top, px_right, px_bottom))
            cropped.save(png_path, 'PNG')
            new_w, new_h = cropped.size
            cropped.close()

        # 按裁剪后实际像素反推 WGS84 边界（与整数像素对齐，避免 ±半度浮点缝）
        new_min_lon = c_min_lon + px_left  * lon_per_px
        new_max_lon = c_min_lon + px_right * lon_per_px
        new_max_lat = c_max_lat - px_top    * lat_per_px
        new_min_lat = c_max_lat - px_bottom * lat_per_px

        new_bounds = {
            'min_lon': new_min_lon, 'min_lat': new_min_lat,
            'max_lon': new_max_lon, 'max_lat': new_max_lat,
        }
        return new_bounds, (px_left, px_top, px_right, px_bottom), True

    # ------------------------------------------------------------------
    # ESRI 在线 release 列表
    # ------------------------------------------------------------------
    def _fetch_wayback_releases(self) -> Optional[List[Dict]]:
        """从 ESRI 官方 endpoint 动态获取 wayback release 列表。

        Endpoint: GET WAYBACK_METADATA_URL（world_imagery/MapServer?f=json）
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
            resp = self.session.get(self.WAYBACK_METADATA_URL, timeout=15)
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

        # Name 形如 "World Imagery (Wayback 2026-08-05)"
        date_pattern = re.compile(r'Wayback[ \(](\d{4}-\d{2}-\d{2})\)')
        releases = []
        for item in selection:
            name = str(item.get('Name', ''))
            m_id = str(item.get('M', '')).strip()
            if not m_id:
                continue
            m = date_pattern.search(name)
            date_str = m.group(1) if m else '1970-01-01'
            releases.append({
                'id': m_id,
                'date': date_str,
                'name': name,
                'release_id': str(item.get('ID', '')),
                'source': 'wayback-online',
            })

        if not releases:
            logger.warning("wayback Selection 中未解析出任何 release id")
            return None

        return releases

    def get_available_dates(self, lat: float, lon: float, zoom: int = 18) -> List[Dict]:
        # 入参校验
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"lat 越界: {lat}")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"lon 越界: {lon}")
        if not (1 <= zoom <= 20):
            raise ValueError(f"zoom 越界: {zoom}")

        logger.info(f"查询坐标 ({lat:.6f}, {lon:.6f}) 的可用历史影像...")

        # 在线列表优先
        online = self._fetch_wayback_releases()
        if online:
            logger.info(f"在线元数据返回 {len(online)} 个 release")
            result = online
        else:
            logger.warning("在线元数据不可用，回退到 KNOWN_WAYBACK_VERSIONS")
            result = [
                {'id': v['id'], 'date': v['date'], 'name': v['date'], 'source': 'wayback'}
                for v in KNOWN_WAYBACK_VERSIONS
            ]

        # 统一按日期升序（最早的在前），使输出子文件夹按时间线排列
        result.sort(key=lambda d: d['date'])

        logger.info(f"找到 {len(result)} 个版本")
        return result

    # ------------------------------------------------------------------
    # 瓦片下载
    # ------------------------------------------------------------------
    def _resolve_tile_url(self, wayback_id: str, z: int, y: int, x: int) -> str:
        """构造瓦片 URL。优先用动态模板，失败时使用 fallback 模板。"""
        template = self._wayback_tile_url_template or self.WAYBACK_TILE_URL_FALLBACK
        try:
            return template.format(wayback_id=wayback_id, z=z, y=y, x=x)
        except KeyError:
            return self.WAYBACK_TILE_URL_FALLBACK.format(
                wayback_id=wayback_id, z=z, y=y, x=x
            )

    def download_tiles_batch(self, tile_coords: List[Tuple[int, int]], zoom: int,
                             temp_dir: str, wayback_id: str = None) -> int:
        """并发下载瓦片，返回成功下载数（包含本地已缓存的）。"""
        downloaded = [0]
        headers = {'User-Agent': 'Mozilla/5.0'}

        def download_one(x, y, z, save_path):
            try:
                if wayback_id:
                    url = self._resolve_tile_url(wayback_id, z, y, x)
                else:
                    url = (
                        f"https://server.arcgisonline.com/arcgis/rest/services/"
                        f"World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    )
                resp = self.session.get(url, headers=headers, timeout=60)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    with open(save_path, 'wb') as f:
                        f.write(resp.content)
                    downloaded[0] += 1
                else:
                    # 失败时清理半成品文件
                    if os.path.exists(save_path):
                        try:
                            os.remove(save_path)
                        except OSError:
                            pass
            except Exception:
                if os.path.exists(save_path):
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass

        tasks = []
        for x, y in tile_coords:
            tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
            if os.path.exists(tile_path) and os.path.getsize(tile_path) > 1000:
                downloaded[0] += 1
            else:
                tasks.append((x, y, zoom, tile_path))

        if tasks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_pool_size) as ex:
                list(ex.map(lambda t: download_one(*t), tasks))
        return downloaded[0]

    # ------------------------------------------------------------------
    # 拼接
    # ------------------------------------------------------------------
    def stitch_tiles(self, temp_dir: str, expected_tile_count: int,
                     save_path: str) -> Tuple[bool, int]:
        """拼接瓦片到 PNG。

        - 以实际下载到的瓦片坐标范围建画布
        - 若缺失瓦片，抛出 IncompleteTilesError（不输出黑边图）
        - 返回 (success, actual_count)
        """
        try:
            tile_files = [
                f for f in os.listdir(temp_dir)
                if f.startswith('tile_') and f.endswith('.png')
            ]
            if not tile_files:
                return False, 0

            tiles_info = []
            for tf in tile_files:
                parts = tf.replace('tile_', '').replace('.png', '').split('_')
                if len(parts) == 3:
                    tiles_info.append({
                        'x': int(parts[0]),
                        'y': int(parts[1]),
                        'file': os.path.join(temp_dir, tf)
                    })

            if not tiles_info:
                return False, 0

            # 使用实际下载到的瓦片坐标范围
            min_x = min(t['x'] for t in tiles_info)
            max_x = max(t['x'] for t in tiles_info)
            min_y = min(t['y'] for t in tiles_info)
            max_y = max(t['y'] for t in tiles_info)

            actual_count = len(tiles_info)
            if actual_count < expected_tile_count:
                # 缺失瓦片：抛错，不输出黑边 GeoTIFF
                raise IncompleteTilesError(
                    f"瓦片下载不完整：实际 {actual_count}/{expected_tile_count}"
                )

            first_tile = Image.open(tiles_info[0]['file'])
            tw, th = first_tile.size
            first_tile.close()

            # 拼接：y_min（更北的瓦片）贴到图像顶部（y=0）
            canvas_w = (max_x - min_x + 1) * tw
            canvas_h = (max_y - min_y + 1) * th
            result = Image.new('RGB', (canvas_w, canvas_h))

            for tile in tiles_info:
                tile_img = Image.open(tile['file'])
                result.paste(tile_img, ((tile['x'] - min_x) * tw, (tile['y'] - min_y) * th))
                tile_img.close()

            result.save(save_path, 'PNG')
            result.close()
            return True, actual_count
        except IncompleteTilesError:
            raise
        except Exception as e:
            logger.error(f"拼接失败: {e}")
            return False, 0

    # ------------------------------------------------------------------
    # GeoTIFF 输出
    # ------------------------------------------------------------------
    def png_to_geotiff(self, png_path: str, tiff_path: str,
                       bounds: Dict) -> bool:
        if not _RASTERIO_AVAILABLE:
            logger.error("rasterio 不可用，无法生成 GeoTIFF（请安装 rasterio 与 expat）")
            return False
        try:
            with Image.open(png_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                width, height = img.size
                img_array = np.array(img)

            transform = from_bounds(
                bounds['min_lon'], bounds['min_lat'],
                bounds['max_lon'], bounds['max_lat'],
                width, height
            )

            with rasterio.open(
                tiff_path, 'w', driver='GTiff',
                height=height, width=width, count=3,
                dtype=img_array.dtype, crs=rasterio.CRS.from_wkt(WGS84_WKT),
                transform=transform, compress='lzw'
            ) as dst:
                dst.write(img_array[:, :, 0], 1)
                dst.write(img_array[:, :, 1], 2)
                dst.write(img_array[:, :, 2], 3)
            return True
        except Exception as e:
            logger.error(f"转换失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 哈希（字节级 + 感知级）
    # ------------------------------------------------------------------
    # 感知哈希汉明距阈值：<=DHASH_DUP_THRESHOLD 即视为「视觉同一影像」。
    # dHash16 的 256 bits 中经验上：完全相同图像=0~2；轻微压缩差异<8；同一场景不同季节一般>30。
    DHASH_SIZE = 16
    DHASH_DUP_THRESHOLD = 6
    # 预筛（单瓦片）使用更宽松阈值，避免误跳：瓦片粒度细节差异更大
    DHASH_TILE_THRESHOLD = 4

    def compute_image_hash(self, image_path: str,
                           chunk_size: int = 1 << 20) -> Optional[str]:
        """字节级 MD5（流式，避免一次读入大文件）。命中即 100% 确定重复。"""
        try:
            h = hashlib.md5()
            with open(image_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    @classmethod
    def compute_dhash_int(cls, img) -> Optional[int]:
        """计算 dHash（差异哈希）整数（抗 PNG 编码、JPEG 压缩、色深差异）。

        img: PIL.Image（或任何已打开的图像）。内部会转为 L 并 resize。
        返回 int（DHASH_SIZE^2 bits）。失败返回 None。
        """
        try:
            sz = cls.DHASH_SIZE
            gray = img.convert('L').resize((sz + 1, sz), Image.LANCZOS)
            try:
                # Pillow >= 10
                px = gray.get_flattened_data()
            except AttributeError:
                px = list(gray.getdata())
            w = sz + 1
            bits = 0
            idx = 0
            for y in range(sz):
                row = y * w
                for x in range(sz):
                    if px[row + x] > px[row + x + 1]:
                        bits |= 1 << idx
                    idx += 1
            return bits
        except Exception:
            return None

    @classmethod
    def compute_dhash_int_from_path(cls, path: str) -> Optional[int]:
        try:
            with Image.open(path) as im:
                return cls.compute_dhash_int(im)
        except Exception:
            return None

    @staticmethod
    def _hamming(a: Optional[int], b: Optional[int]) -> int:
        if a is None or b is None:
            return (WaybackImageFetcher.DHASH_SIZE *
                    WaybackImageFetcher.DHASH_SIZE)  # 最坏距离，永不判重
        return bin(a ^ b).count('1')

    def _fetch_center_tile_dhash(self, lat: float, lon: float, zoom: int,
                                 wayback_id: str, temp_root: str) -> Optional[int]:
        """为指定坐标 + wayback 版本，预下载 1 张「覆盖中心点」的瓦片，返回其 dHash。

        作为 1-tile / ~50KB 量级的预筛；比下完几 MB 整片再发现重复，
        能节省 90%+ 的网络开销。失败返回 None，调用方应放弃预筛。
        """
        try:
            x, y = self._center_tile(lat, lon, zoom)
            tmp_dir = os.path.join(temp_root, f"probe_{wayback_id}")
            os.makedirs(tmp_dir, exist_ok=True)
            save_path = os.path.join(tmp_dir, f"{x}_{y}.png")
            if os.path.exists(save_path) and os.path.getsize(save_path) > 1000:
                pass  # 复用之前探针
            else:
                url = self._resolve_tile_url(wayback_id, zoom, y, x)
                headers = {'User-Agent': 'Mozilla/5.0'}
                try:
                    resp = self.session.get(url, headers=headers, timeout=30)
                    if resp.status_code != 200 or len(resp.content) <= 1000:
                        return None
                    with open(save_path, 'wb') as f:
                        f.write(resp.content)
                except Exception:
                    return None
            with Image.open(save_path) as im:
                return self.compute_dhash_int(im)
        except Exception:
            return None

    @staticmethod
    def _center_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """返回覆盖 (lat, lon, zoom) 的瓦片坐标（int, int）。"""
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        x = max(0, min(n - 1, x))
        y = max(0, min(n - 1, y))
        return x, y

    def _is_duplicate_image(self, path_or_dhash, byte_hashes=None,
                            dhashes=None, strict: bool = False):
        """判定输入是否与历史记录重复。

        path_or_dhash: 图片路径(str) 或 预计算的 (md5, dhash) 二元组；
        byte_hashes:   字节级 MD5 set；
        dhashes:       感知 dhash int set；
        strict:        False 使用 DHASH_DUP_THRESHOLD；True 更严格（仅 0/1）。
        返回 (is_dup: bool, matched_md5, matched_dhash)。
        """
        if isinstance(path_or_dhash, tuple) and len(path_or_dhash) == 2:
            img_md5, img_dhash = path_or_dhash
        else:
            img_md5 = self.compute_image_hash(path_or_dhash)
            img_dhash = self.compute_dhash_int_from_path(path_or_dhash)

        # 1) 字节级 exact match → 直接确定重复
        if img_md5 and byte_hashes is not None and img_md5 in byte_hashes:
            return True, img_md5, img_dhash

        # 2) 感知级近似 match → 视觉重复（ESRI 重发布的坑）
        if img_dhash is not None and dhashes is not None:
            thresh = 1 if strict else self.DHASH_DUP_THRESHOLD
            for known in dhashes:
                if self._hamming(img_dhash, known) <= thresh:
                    return True, img_md5, img_dhash
        return False, img_md5, img_dhash

    # ------------------------------------------------------------------
    # 单日期版本下载主流程
    # ------------------------------------------------------------------
    def download_image(self, lat: float, lon: float, zoom: int,
                       date_info: Dict, output_dir: str,
                       buffer_size: int = 500,
                       probe_root: Optional[str] = None) -> Optional[Dict]:
        """下载单日期版本影像。

        probe_root: 若指定，先下载中心瓦片做 dHash 预筛；命中直接跳过，
                    可节省 90%+ 重复发布的网络/CPU。为 None 则跳过预筛。

        显式参数：lat / lon / zoom / buffer_size 会在此行同时打印，
                  便于用户一眼核对「级别」与「缓冲距离」是否按预期传递。
        """
        date_str = date_info['date']
        wayback_id = date_info['id']

        x_min, x_max, y_min, y_max = self.get_tile_coords(lat, lon, zoom, buffer_size)
        expected_tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
        min_lon, min_lat, max_lon, max_lat = self._tile_bounds_wgs84(
            x_min, x_max, y_min, y_max, zoom
        )
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        ew_m = (max_lon - min_lon) * 111320.0 * cos_lat
        ns_m = (max_lat - min_lat) * 111320.0

        logger.info(
            f"下载 {date_str} (ID: {wayback_id}) "
            f"[zoom={zoom}, buffer={buffer_size}m, "
            f"瓦片 {x_max-x_min+1}×{y_max-y_min+1}={expected_tile_count}, "
            f"地面覆盖 ~ {ew_m:.0f}m × {ns_m:.0f}m]"
        )

        # ---------- 0) 预筛：1 张中心瓦片 dHash 短路（避免整片区下载） ----------
        if probe_root:
            tile_dhash = self._fetch_center_tile_dhash(
                lat, lon, zoom, wayback_id, probe_root,
            )
            if tile_dhash is not None and self._probe_tile_dhashes:
                for known in self._probe_tile_dhashes.values():
                    if self._hamming(tile_dhash, known) <= self.DHASH_TILE_THRESHOLD:
                        logger.info(
                            f"[预筛-中心瓦片] {date_str} 与已收录版本视觉相同，"
                            f"跳过 (dHash 距离 {self._hamming(tile_dhash, known)})"
                        )
                        self._probe_tile_dhashes.setdefault(wayback_id, tile_dhash)
                        return {
                            'status': 'duplicate',
                            'date': date_str,
                            'tile_dhash': tile_dhash,
                            'reason': 'precheck-tile-dhash',
                        }
            if tile_dhash is not None:
                self._probe_tile_dhashes.setdefault(wayback_id, tile_dhash)

        temp_dir = f"temp_tiles_{date_str.replace('-', '')}"
        for _ in range(3):
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                break
            except PermissionError:
                time.sleep(0.5)
        os.makedirs(temp_dir, exist_ok=True)

        tile_coords = [(x, y) for x in range(x_min, x_max + 1)
                      for y in range(y_min, y_max + 1)]
        downloaded = self.download_tiles_batch(tile_coords, zoom, temp_dir, wayback_id)

        if downloaded == 0:
            logger.error(f"瓦片下载失败: {date_str}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        # 精确边界（基于瓦片四角）
        min_lon, min_lat, max_lon, max_lat = self._tile_bounds_wgs84(
            x_min, x_max, y_min, y_max, zoom
        )
        bounds = {
            'min_lon': min_lon,
            'max_lon': max_lon,
            'min_lat': min_lat,
            'max_lat': max_lat,
        }

        # 拼接（缺失瓦片会抛 IncompleteTilesError）
        temp_png_path = os.path.join(temp_dir, f"{date_str}.png")
        try:
            ok, actual_count = self.stitch_tiles(
                temp_dir, expected_tile_count, temp_png_path
            )
        except IncompleteTilesError as e:
            logger.error(f"{date_str}: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        if not ok:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        # ---------- 1) 整图 MD5 + 感知 dHash 双重去重 ----------
        img_md5 = self.compute_image_hash(temp_png_path)
        img_dhash = self.compute_dhash_int_from_path(temp_png_path)
        is_dup, _, _ = self._is_duplicate_image(
            (img_md5, img_dhash),
            byte_hashes=self._downloaded_hashes,
            dhashes=self._downloaded_dhashes,
        )
        if is_dup:
            logger.info(f"[整图去重] {date_str} 与之前版本视觉相同，跳过")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                'status': 'duplicate',
                'hash': img_md5,
                'dhash': img_dhash,
                'date': date_str,
            }

        # ---------- 2) 按用户 buffer 精确裁剪中心矩形（解决低 zoom 单瓦片过大的问题） ----------
        clip_rect = self._buffer_wgs84_rect(lat, lon, buffer_size)
        canvas_bounds = (min_lon, min_lat, max_lon, max_lat)
        try:
            new_bounds, px_box, did_crop = self._crop_png_to_wgs84_rect(
                temp_png_path,
                canvas_bounds,
                clip_rect,
            )
        except ValueError as e:
            logger.error(f"{date_str} 裁剪失败：{e}；回退为输出原始瓦片矩形")
            new_bounds = bounds
            did_crop = False
            px_box = (0, 0, 0, 0)

        # 裁剪后的实际输出范围（米），用于日志
        cos_lat2 = max(math.cos(math.radians(lat)), 1e-6)
        out_ew_m = (new_bounds['max_lon'] - new_bounds['min_lon']) * 111320.0 * cos_lat2
        out_ns_m = (new_bounds['max_lat'] - new_bounds['min_lat']) * 111320.0
        if did_crop:
            logger.info(
                f"[范围] 瓦片覆盖 {ew_m:.0f}×{ns_m:.0f}m → 裁剪后输出 "
                f"{out_ew_m:.0f}×{out_ns_m:.0f}m (px box {px_box})"
            )
        else:
            logger.info(
                f"[范围] 瓦片覆盖 {ew_m:.0f}×{ns_m:.0f}m → 直接输出 "
                f"{out_ew_m:.0f}×{out_ns_m:.0f}m"
            )
        bounds = new_bounds

        # 写入输出
        date_dir = os.path.join(output_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)
        png_path = os.path.join(date_dir, f"{date_str}.png")
        tif_path = os.path.join(date_dir, f"{date_str}.tif")

        if self.png_to_geotiff(temp_png_path, tif_path, bounds):
            # 复制 PNG 到输出目录
            with open(temp_png_path, 'rb') as src:
                with open(png_path, 'wb') as dst:
                    dst.write(src.read())
            if img_md5:
                self._downloaded_hashes.add(img_md5)
            if img_dhash is not None:
                self._downloaded_dhashes.add(img_dhash)
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(
                f"成功: {tif_path} "
                f"[最终覆盖 {out_ew_m:.0f}m(EW) × {out_ns_m:.0f}m(NS)]"
            )
            return {
                'status': 'success',
                'hash': img_md5,
                'dhash': img_dhash,
                'date': date_str,
                'path': tif_path
            }

        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    # ------------------------------------------------------------------
    # 批量入口
    # ------------------------------------------------------------------
    def fetch_all_historical(self, lat: float, lon: float, zoom: int = 18,
                             output_dir: str = 'data/output/historical',
                             buffer_size: int = 500,
                             date_range: Optional[Tuple[str, str]] = None) -> List[Dict]:
        logger.info("=" * 60)
        logger.info(f"获取坐标 ({lat:.6f}, {lon:.6f}) 的历史影像")
        logger.info("=" * 60)

        # 清空已下载哈希记录（双重：MD5 + dHash）
        self._downloaded_hashes.clear()
        self._downloaded_dhashes.clear()
        self._probe_tile_dhashes.clear()

        # 预筛临时目录：同一坐标点所有 release 共用（1 tile/release，非常小）
        probe_root = os.path.join(
            os.path.abspath(output_dir),
            f"_probe_{zoom}_{lat:.5f}_{lon:.5f}".replace('-', 'm').replace('.', 'p'),
        )
        try:
            os.makedirs(probe_root, exist_ok=True)
        except Exception:
            probe_root = None  # 建目录失败就放弃预筛，不影响主流程

        # ---------- 预填充：扫描已有 PNG 同时建 MD5 + dHash 两条索引 ----------
        if os.path.exists(output_dir):
            for date_dir in sorted(os.listdir(output_dir)):
                png_path = os.path.join(output_dir, date_dir, f'{date_dir}.png')
                if not os.path.exists(png_path):
                    continue
                img_md5 = self.compute_image_hash(png_path)
                img_dhash = self.compute_dhash_int_from_path(png_path)
                if img_md5:
                    self._downloaded_hashes.add(img_md5)
                if img_dhash is not None:
                    self._downloaded_dhashes.add(img_dhash)
                logger.info(f"已存在: {date_dir}")

        dates = self.get_available_dates(lat, lon, zoom)

        if date_range:
            dates = [d for d in dates if date_range[0] <= d['date'] <= date_range[1]]
            logger.info(f"日期筛选后剩余 {len(dates)} 个")

        results = []
        skipped_duplicates = 0
        skipped_existing = 0

        for i, date_info in enumerate(dates, 1):
            date_str = date_info['date']
            logger.info(f"[{i}/{len(dates)}] {date_str}...")

            date_dir = os.path.join(output_dir, date_str)
            png_path = os.path.join(date_dir, f'{date_str}.png')
            tif_path = os.path.join(date_dir, f'{date_str}.tif')

            # ---------- 已有文件：去重 or 直接跳过 ----------
            if os.path.exists(png_path):
                is_dup, img_md5, img_dhash = self._is_duplicate_image(
                    png_path,
                    byte_hashes=self._downloaded_hashes,
                    dhashes=self._downloaded_dhashes,
                )
                if is_dup:
                    logger.info(f"[感知去重] {date_str} 与已保存版本视觉相同，标记重复")
                    skipped_duplicates += 1
                    results.append({
                        'date': date_str,
                        'name': date_info.get('name', date_str),
                        'status': 'duplicate',
                        'file_path': tif_path if os.path.exists(tif_path) else None,
                    })
                    continue
                # 非重复：把当前文件的 hash 登记，避免新下的覆盖它
                if img_md5:
                    self._downloaded_hashes.add(img_md5)
                if img_dhash is not None:
                    self._downloaded_dhashes.add(img_dhash)
                skipped_existing += 1
                logger.info(f"已存在文件，跳过下载: {date_str}")
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'existing',
                    'file_path': tif_path if os.path.exists(tif_path) else None,
                })
                continue

            # ---------- 新下载：启用中心瓦片预筛 ----------
            result = self.download_image(
                lat, lon, zoom, date_info, output_dir, buffer_size,
                probe_root=probe_root,
            )

            if result is None:
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'failed',
                    'file_path': None,
                })
            elif result['status'] == 'duplicate':
                skipped_duplicates += 1
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'duplicate',
                    'file_path': None,
                })
            else:
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'success',
                    'file_path': result['path'],
                })
            time.sleep(0.3)

        # 清理：预筛目录用完即销毁（其内容对用户无意义）
        if probe_root and os.path.exists(probe_root):
            shutil.rmtree(probe_root, ignore_errors=True)

        success = sum(1 for r in results if r['status'] == 'success')
        failed = sum(1 for r in results if r['status'] == 'failed')

        logger.info(f"\n完成！成功 {success}/{len(results)} 个")
        if skipped_existing > 0:
            logger.info(f"跳过已有文件: {skipped_existing} 个")
        if skipped_duplicates > 0:
            logger.info(f"跳过重复图片: {skipped_duplicates} 个")
        if failed > 0:
            logger.info(f"下载失败: {failed} 个")

        return results

    # ------------------------------------------------------------------
    # 批量入口（多坐标）
    # ------------------------------------------------------------------
    def fetch_batch_historical(self, coords: List[Dict],
                               output_root: str,
                               zoom: int = 18,
                               buffer_size: int = 500,
                               date_range: Optional[Tuple[str, str]] = None,
                               coord_concurrency: int = 1) -> List[Dict]:
        """批量获取多坐标点的历史影像。

        Args:
            coords: 由 coordinate_loader.load_coordinates_file 返回的坐标列表，
                    每项必须含 lat, lon；name, id 可选。
            output_root: 批量输出根目录；每个坐标点一个独立子目录。
            zoom, buffer_size, date_range: 同 fetch_all_historical。
            coord_concurrency: 坐标级别并发数；默认 1（串行，避免 ESRI 限流）。

        Returns:
            每个坐标点的 (name, lat, lon, results, output_dir) 元信息列表。
        """
        if not coords:
            logger.warning("批量坐标列表为空")
            return []

        os.makedirs(output_root, exist_ok=True)

        # 入参校验（顶层），单个坐标抛错不影响其他坐标
        summary = []
        total = len(coords)

        for i, coord in enumerate(coords, start=1):
            lat = float(coord['lat'])
            lon = float(coord['lon'])
            raw_id = coord.get('id') or ''
            raw_name = coord.get('name') or ''
            sub = raw_id or raw_name or f"point_{i}_{lat:.6f}_{lon:.6f}"
            # 子目录名清洗（Windows 合法）
            sub = re.sub(r'[\\/:\*\?"<>\|\x00-\x1f]', '_', str(sub))
            sub = sub.replace(' ', '_').strip('._') or f"point_{i}"
            if len(sub) > 64:
                sub = sub[:64].rstrip('._')

            coord_out = os.path.join(output_root, sub)
            os.makedirs(coord_out, exist_ok=True)

            logger.info("=" * 60)
            logger.info(f"[{i}/{total}] 坐标点 {sub} ({lat:.6f}, {lon:.6f})")
            logger.info("=" * 60)

            try:
                results = self.fetch_all_historical(
                    lat=lat,
                    lon=lon,
                    zoom=zoom,
                    output_dir=coord_out,
                    buffer_size=buffer_size,
                    date_range=date_range,
                )
            except ValueError as e:
                logger.error(f"[{i}/{total}] {sub} 坐标越界: {e}")
                results = []

            success_n = sum(1 for r in results if r['status'] == 'success')
            failed_n = sum(1 for r in results if r['status'] == 'failed')
            summary.append({
                'index': i,
                'name': sub,
                'lat': lat,
                'lon': lon,
                'output_dir': coord_out,
                'total_dates': len(results),
                'success': success_n,
                'failed': failed_n,
                'results': results,
            })

        total_success = sum(s['success'] for s in summary)
        total_failed = sum(s['failed'] for s in summary)
        logger.info("=" * 60)
        logger.info(f"批量完成！共 {total} 个坐标点")
        logger.info(f"  成功日期版本: {total_success}")
        logger.info(f"  失败日期版本: {total_failed}")
        logger.info("=" * 60)
        return summary

    # ------------------------------------------------------------------
    # 启动时清理残余临时瓦片
    # ------------------------------------------------------------------
    def _cleanup_residual_temp_tiles(self, root_dir: Optional[str] = None):
        """清理根目录下所有 temp_tiles_* 残留目录。供 __init__ 自动调用。

        Args:
            root_dir: 扫描根目录；默认 BASE_DIR。
        Returns:
            被清理的目录路径列表。
        """
        if root_dir is None:
            try:
                root_dir = os.path.dirname(os.path.abspath(__file__))
            except Exception:
                root_dir = os.getcwd()

        removed = []
        try:
            entries = os.listdir(root_dir)
        except OSError:
            return removed

        for entry in entries:
            full = os.path.join(root_dir, entry)
            if not (os.path.isdir(full) and entry.startswith('temp_tiles_')):
                continue
            try:
                shutil.rmtree(full, ignore_errors=True)
                removed.append(full)
            except Exception:
                pass
        if removed:
            logger.info(f"启动清理临时瓦片: {len(removed)} 个目录")
        return removed
