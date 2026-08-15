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
import rasterio
from rasterio.transform import from_bounds
import warnings
warnings.filterwarnings('ignore')

# 关闭 ESRI wayback 域名的 SSL 警告（其证书链有时触发告警）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger('TiffGetter')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

from config import WGS84_WKT, CONFIG, THREAD_POOL_SIZE

# 自定义异常：瓦片未下载完整
class IncompleteTilesError(Exception):
    pass


# ESRI Wayback 版本列表（fallback 用，仅当在线 endpoint 不可用时退而求其次）
# 这些 ID 在 2025-2026 年实测可用，但官方接口优先
KNOWN_WAYBACK_VERSIONS = [
    {"id": "20512", "date": "2026-05-28"},
    {"id": "58924", "date": "2025-09-25"},
    {"id": "52304", "date": "2025-09-04"},
    {"id": "49999", "date": "2025-07-31"},
    {"id": "48925", "date": "2025-06-26"},
    {"id": "25285", "date": "2025-05-29"},
    {"id": "27982", "date": "2025-04-24"},
    {"id": "6543", "date": "2025-03-27"},
    {"id": "34007", "date": "2025-02-27"},
    {"id": "36557", "date": "2025-01-30"},
    {"id": "16453", "date": "2024-12-12"},
    {"id": "49849", "date": "2024-11-18"},
    {"id": "56450", "date": "2024-10-10"},
    {"id": "20337", "date": "2024-09-19"},
    {"id": "32553", "date": "2024-08-15"},
    {"id": "39767", "date": "2024-06-27"},
    {"id": "12428", "date": "2024-06-06"},
    {"id": "52930", "date": "2024-05-09"},
    {"id": "13968", "date": "2024-03-28"},
    {"id": "60013", "date": "2024-03-07"},
    {"id": "37965", "date": "2024-02-08"},
    {"id": "41468", "date": "2024-01-18"},
    {"id": "56102", "date": "2023-12-07"},
    {"id": "12457", "date": "2023-11-01"},
    {"id": "1034", "date": "2023-10-11"},
    {"id": "64776", "date": "2023-08-31"},
    {"id": "17632", "date": "2023-08-10"},
    {"id": "47963", "date": "2023-06-29"},
    {"id": "25982", "date": "2023-06-13"},
    {"id": "46399", "date": "2023-05-03"},
    {"id": "37890", "date": "2023-04-05"},
    {"id": "321", "date": "2023-03-15"},
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
        self._downloaded_hashes = set()  # 用于 PNG 级别去重
        self._wayback_tile_url_template = self.WAYBACK_TILE_URL_TEMPLATE

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
        """
        # 经度方向按纬度做 cos 修正，保证东西向距离正确
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        half_lon_deg = (buffer_size / 2) / (111320.0 * cos_lat)
        half_lat_deg = (buffer_size / 2) / 111320.0

        # 四个角点
        sx_tile, sy_tile = self.latlon_to_tile(lat - half_lat_deg, lon - half_lon_deg, zoom)
        nx_tile, ny_tile = self.latlon_to_tile(lat + half_lat_deg, lon + half_lon_deg, zoom)

        x_min, x_max = min(sx_tile, nx_tile), max(sx_tile, nx_tile)
        # 在 Web Mercator 中，纬度越高 y 越小，因此 y_min = 较大纬度对应的瓦片
        y_min, y_max = min(sy_tile, ny_tile), max(sy_tile, ny_tile)
        return x_min, x_max, y_min, y_max

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
    # 哈希（流式分块）
    # ------------------------------------------------------------------
    def compute_image_hash(self, image_path: str,
                           chunk_size: int = 1 << 20) -> Optional[str]:
        """流式 MD5，避免一次读入大文件。"""
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

    # ------------------------------------------------------------------
    # 单日期版本下载主流程
    # ------------------------------------------------------------------
    def download_image(self, lat: float, lon: float, zoom: int,
                       date_info: Dict, output_dir: str,
                       buffer_size: int = 500) -> Optional[Dict]:
        date_str = date_info['date']
        wayback_id = date_info['id']
        logger.info(f"下载 {date_str} (ID: {wayback_id})...")

        x_min, x_max, y_min, y_max = self.get_tile_coords(lat, lon, zoom, buffer_size)
        expected_tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)

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

        # PNG 哈希：稳定、像素级
        img_hash = self.compute_image_hash(temp_png_path)
        if img_hash and img_hash in self._downloaded_hashes:
            logger.info(f"图片与之前版本重复，跳过: {date_str}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {'status': 'duplicate', 'hash': img_hash, 'date': date_str}

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
            if img_hash:
                self._downloaded_hashes.add(img_hash)
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"成功: {tif_path}")
            return {
                'status': 'success',
                'hash': img_hash,
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

        # 清空已下载哈希记录
        self._downloaded_hashes.clear()

        # 扫描已有 PNG 建立哈希记录（PNG 级哈希更稳定）
        if os.path.exists(output_dir):
            for date_dir in os.listdir(output_dir):
                png_path = os.path.join(output_dir, date_dir, f'{date_dir}.png')
                if os.path.exists(png_path):
                    img_hash = self.compute_image_hash(png_path)
                    if img_hash:
                        self._downloaded_hashes.add(img_hash)
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

            # 检查是否已存在（基于 PNG 哈希）
            date_dir = os.path.join(output_dir, date_str)
            png_path = os.path.join(date_dir, f'{date_str}.png')
            tif_path = os.path.join(date_dir, f'{date_str}.tif')

            if os.path.exists(png_path):
                img_hash = self.compute_image_hash(png_path)
                if img_hash and img_hash in self._downloaded_hashes:
                    logger.info(f"图片与之前版本重复，跳过: {date_str}")
                    skipped_duplicates += 1
                    results.append({
                        'date': date_str,
                        'name': date_info.get('name', date_str),
                        'status': 'duplicate',
                        'file_path': tif_path if os.path.exists(tif_path) else None
                    })
                    continue
                elif img_hash:
                    self._downloaded_hashes.add(img_hash)
                    skipped_existing += 1
                    logger.info(f"已存在文件，跳过下载: {date_str}")
                    results.append({
                        'date': date_str,
                        'name': date_info.get('name', date_str),
                        'status': 'existing',
                        'file_path': tif_path if os.path.exists(tif_path) else None
                    })
                    continue

            result = self.download_image(lat, lon, zoom, date_info, output_dir, buffer_size)

            if result is None:
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'failed',
                    'file_path': None
                })
            elif result['status'] == 'duplicate':
                skipped_duplicates += 1
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'duplicate',
                    'file_path': None
                })
            else:
                results.append({
                    'date': date_str,
                    'name': date_info.get('name', date_str),
                    'status': 'success',
                    'file_path': result['path']
                })
            time.sleep(0.3)

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
