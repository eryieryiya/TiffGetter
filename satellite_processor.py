# ESRI Wayback 历史影像获取模块
import os
import time
import requests
import concurrent.futures
import math
import shutil
import logging
import hashlib
from PIL import Image
from typing import List, Dict, Tuple, Optional
import numpy as np
import rasterio
from rasterio.transform import from_bounds
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger('TiffGetter')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

from config import WGS84_WKT

# ESRI Wayback 版本列表 (使用数字 ID，与 API URL 格式匹配)
KNOWN_WAYBACK_VERSIONS = [
    # 2026
    {"id": "20512", "date": "2026-05-28"},  # 实际测试可用
    # 2025
    {"id": "58924", "date": "2025-09-25"},
    {"id": "52304", "date": "2025-09-04"},
    {"id": "49999", "date": "2025-07-31"},
    {"id": "48925", "date": "2025-06-26"},
    {"id": "25285", "date": "2025-05-29"},
    {"id": "27982", "date": "2025-04-24"},
    {"id": "6543", "date": "2025-03-27"},
    {"id": "34007", "date": "2025-02-27"},
    {"id": "36557", "date": "2025-01-30"},
    # 2024
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
    # 2023
    {"id": "56102", "date": "2023-12-07"},
    {"id": "12457", "date": "2023-11-01"},
    {"id": "1034", "date": "2023-10-11"},  # 实际测试可用
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
    def __init__(self):
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=requests.packages.urllib3.util.retry.Retry(total=3, backoff_factor=0.5)
        )
        self.session = requests.Session()
        self.session.mount('https://', adapter)
        self.session.verify = False
        self.thread_pool_size = 10
        self._downloaded_hashes = set()  # 用于去重

    @staticmethod
    def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        xtile = int((lon + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
        return xtile, ytile

    def get_available_dates(self, lat: float, lon: float, zoom: int = 18) -> List[Dict]:
        logger.info(f"查询坐标 ({lat:.6f}, {lon:.6f}) 的可用历史影像...")
        result = [{'id': v['id'], 'date': v['date'], 'name': v['date'], 'source': 'wayback'} for v in KNOWN_WAYBACK_VERSIONS]
        logger.info(f"找到 {len(result)} 个版本")
        return result

    def get_tile_coords(self, lat: float, lon: float, zoom: int, buffer_size: int = 500) -> Tuple[int, int, int, int]:
        half_deg = (buffer_size / 2) / 111320
        # 计算四个角的瓦片坐标
        x1, y1 = self.latlon_to_tile(lat - half_deg, lon - half_deg, zoom)
        x2, y2 = self.latlon_to_tile(lat + half_deg, lon + half_deg, zoom)
        return min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)

    def download_tiles_batch(self, tile_coords: List[Tuple[int, int]], zoom: int,
                            temp_dir: str, wayback_id: str = None) -> int:
        downloaded = [0]
        headers = {'User-Agent': 'Mozilla/5.0'}

        def download_one(x, y, z, save_path):
            try:
                if wayback_id:
                    # 使用新的 ESRI Wayback API 格式
                    url = f"https://wayback-a.maptiles.arcgis.com/arcgis/rest/services/world_imagery/wmts/1.0.0/default028mm/mapserver/tile/{wayback_id}/{z}/{y}/{x}"
                else:
                    url = f"https://server.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                resp = self.session.get(url, headers=headers, timeout=60)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    with open(save_path, 'wb') as f:
                        f.write(resp.content)
                    downloaded[0] += 1
            except:
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

    def stitch_tiles(self, temp_dir: str, tile_count_x: int, tile_count_y: int, save_path: str) -> bool:
        try:
            tile_files = [f for f in os.listdir(temp_dir) if f.startswith('tile_') and f.endswith('.png')]
            if not tile_files:
                return False

            tiles_info = []
            for tf in tile_files:
                parts = tf.replace('tile_', '').replace('.png', '').split('_')
                if len(parts) == 3:
                    tiles_info.append({'x': int(parts[0]), 'y': int(parts[1]), 'file': os.path.join(temp_dir, tf)})

            # 读取所有瓦片到内存
            images = []
            for tile in tiles_info:
                tile_img = Image.open(tile['file'])
                images.append((tile['x'], tile['y'], tile_img.copy()))
                tile_img.close()

            first_tile = images[0][2]
            tw, th = first_tile.size

            result = Image.new('RGB', (tw * tile_count_x, th * tile_count_y))
            min_x = min(t['x'] for t in tiles_info)
            min_y = min(t['y'] for t in tiles_info)

            for x, y, tile_img in images:
                result.paste(tile_img, ((x - min_x) * tw, (y - min_y) * th))
                tile_img.close()

            result.save(save_path, 'PNG')
            result.close()
            return True
        except Exception as e:
            logger.error(f"拼接失败: {e}")
            return False

    def png_to_geotiff(self, png_path: str, tiff_path: str, bounds: Dict) -> bool:
        try:
            with Image.open(png_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                width, height = img.size
                img_array = np.array(img)

            transform = from_bounds(bounds['min_lon'], bounds['min_lat'],
                                   bounds['max_lon'], bounds['max_lat'], width, height)

            with rasterio.open(tiff_path, 'w', driver='GTiff',
                              height=height, width=width, count=3,
                              dtype=img_array.dtype, crs=rasterio.CRS.from_wkt(WGS84_WKT),
                              transform=transform, compress='lzw') as dst:
                dst.write(img_array[:, :, 0], 1)
                dst.write(img_array[:, :, 1], 2)
                dst.write(img_array[:, :, 2], 3)
            return True
        except Exception as e:
            logger.error(f"转换失败: {e}")
            return False

    def compute_image_hash(self, image_path: str) -> Optional[str]:
        """计算图片的 MD5 哈希值，用于检测重复"""
        try:
            with open(image_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None

    def download_image(self, lat: float, lon: float, zoom: int,
                      date_info: Dict, output_dir: str, buffer_size: int = 500) -> Optional[Dict]:
        date_str = date_info['date']
        wayback_id = date_info['id']
        logger.info(f"下载 {date_str} (ID: {wayback_id})...")

        x_min, x_max, y_min, y_max = self.get_tile_coords(lat, lon, zoom, buffer_size)
        tile_count_x = abs(x_max - x_min) + 1
        tile_count_y = abs(y_max - y_min) + 1

        temp_dir = f"temp_tiles_{date_str.replace('-', '')}"
        for _ in range(3):
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                break
            except PermissionError:
                time.sleep(0.5)
        os.makedirs(temp_dir, exist_ok=True)

        tile_coords = [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]
        downloaded = self.download_tiles_batch(tile_coords, zoom, temp_dir, wayback_id)

        if downloaded == 0:
            logger.error(f"瓦片下载失败: {date_str}")
            shutil.rmtree(temp_dir)
            return None

        bounds = {
            'min_lon': lon - buffer_size / 2 / 111320,
            'max_lon': lon + buffer_size / 2 / 111320,
            'min_lat': lat - buffer_size / 2 / 111320,
            'max_lat': lat + buffer_size / 2 / 111320
        }

        # 先拼接成临时 PNG
        temp_png_path = os.path.join(temp_dir, f"{date_str}.png")
        if not self.stitch_tiles(temp_dir, tile_count_x, tile_count_y, temp_png_path):
            shutil.rmtree(temp_dir)
            return None

        # 计算哈希并检查是否重复（在保存到输出目录之前）
        img_hash = self.compute_image_hash(temp_png_path)
        if img_hash in self._downloaded_hashes:
            logger.info(f"图片与之前版本重复，跳过: {date_str}")
            shutil.rmtree(temp_dir)
            return {'status': 'duplicate', 'hash': img_hash, 'date': date_str}

        # 不重复，保存到输出目录
        date_dir = os.path.join(output_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)
        png_path = os.path.join(date_dir, f"{date_str}.png")
        tif_path = os.path.join(date_dir, f"{date_str}.tif")

        if self.png_to_geotiff(temp_png_path, tif_path, bounds):
            # 复制 PNG 到输出目录（先关闭文件）
            with open(temp_png_path, 'rb') as src:
                with open(png_path, 'wb') as dst:
                    dst.write(src.read())
            self._downloaded_hashes.add(img_hash)
            shutil.rmtree(temp_dir)
            logger.info(f"成功: {tif_path}")
            return {'status': 'success', 'hash': img_hash, 'date': date_str, 'path': tif_path}

        shutil.rmtree(temp_dir)
        return None

    def fetch_all_historical(self, lat: float, lon: float, zoom: int = 18,
                           output_dir: str = 'data/output/historical',
                           buffer_size: int = 500,
                           date_range: Optional[Tuple[str, str]] = None) -> List[Dict]:
        logger.info("=" * 60)
        logger.info(f"获取坐标 ({lat:.6f}, {lon:.6f}) 的历史影像")
        logger.info("=" * 60)

        # 清空已下载哈希记录
        self._downloaded_hashes.clear()

        # 扫描已有文件，建立哈希记录
        if os.path.exists(output_dir):
            for date_dir in os.listdir(output_dir):
                tif_path = os.path.join(output_dir, date_dir, f'{date_dir}.tif')
                if os.path.exists(tif_path):
                    img_hash = self.compute_image_hash(tif_path)
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
            logger.info(f"[{i}/{len(dates)}] {date_info['date']}...")

            # 检查是否已存在（基于哈希）
            date_dir = os.path.join(output_dir, date_str)
            tif_path = os.path.join(date_dir, f'{date_str}.tif')

            if os.path.exists(tif_path):
                img_hash = self.compute_image_hash(tif_path)
                if img_hash and img_hash in self._downloaded_hashes:
                    logger.info(f"图片与之前版本重复，跳过: {date_str}")
                    skipped_duplicates += 1
                    results.append({
                        'date': date_info['date'],
                        'name': date_info['name'],
                        'status': 'duplicate',
                        'file_path': None
                    })
                    continue
                elif img_hash:
                    # 新图片，加入记录
                    self._downloaded_hashes.add(img_hash)
                    skipped_existing += 1
                    logger.info(f"已存在文件，跳过下载: {date_str}")
                    results.append({
                        'date': date_info['date'],
                        'name': date_info['name'],
                        'status': 'existing',
                        'file_path': tif_path
                    })
                    continue

            result = self.download_image(lat, lon, zoom, date_info, output_dir, buffer_size)

            if result is None:
                results.append({
                    'date': date_info['date'],
                    'name': date_info['name'],
                    'status': 'failed',
                    'file_path': None
                })
            elif result['status'] == 'duplicate':
                skipped_duplicates += 1
                results.append({
                    'date': date_info['date'],
                    'name': date_info['name'],
                    'status': 'duplicate',
                    'file_path': None
                })
            else:
                results.append({
                    'date': date_info['date'],
                    'name': date_info['name'],
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