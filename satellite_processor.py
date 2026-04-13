# 卫星影像处理模块 - 处理卫星影像下载和地理参考TIFF生成

import os
import re
import time
import requests
import concurrent.futures
import threading
import random
import math
import shutil
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from PIL import Image
from typing import List, Dict, Tuple, Optional
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from xml.etree import ElementTree as ET

# 配置日志
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)

# 创建日志记录器
logger = logging.getLogger('TiffGetter')
logger.setLevel(logging.DEBUG)

# 创建文件处理器，设置日志文件大小限制和轮转
log_file = os.path.join(log_dir, 'tiff_getter.log')
file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
file_handler.setLevel(logging.DEBUG)

# 创建控制台处理器，只显示INFO及以上级别的日志
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 设置日志格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 添加处理器到记录器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

from config import (
    THREAD_POOL_SIZE, REQUEST_TIMEOUT, RETRY_COUNT, 
    USER_AGENTS, SATELLITE_SERVICES, WGS84_WKT,
    PATHS, GOOGLE_EARTH_API, WAYBACK_SERVICES
)
from google_earth_client import GoogleEarthClient


class SatelliteToTiffConverter:
    def __init__(self, debug=False):
        """初始化卫星图像转换器
        
        Args:
            debug: 是否开启调试模式
        """
        # 卫星影像服务配置
        self.services = SATELLITE_SERVICES
        
        # ESRI Wayback 历史影像服务
        self.wayback_services = WAYBACK_SERVICES
        
        # Google Earth API客户端
        ge_timeout = GOOGLE_EARTH_API.get('timeout', REQUEST_TIMEOUT)
        self.ge_client = GoogleEarthClient(timeout=ge_timeout)
        
        # 会话池配置
        self.session = requests.Session()
        
        # 动态线程池大小 - 减少并发连接数以避免网络错误
        self.thread_pool_size = min(self.get_optimal_thread_pool_size(), 20)
        self.debug = debug
        
        # 根据debug参数设置控制台日志级别
        if self.debug:
            console_handler.setLevel(logging.DEBUG)
            logger.debug(f"[调试模式] 使用动态线程池大小: {self.thread_pool_size}")
        else:
            console_handler.setLevel(logging.INFO)
            logger.info(f"使用动态线程池大小: {self.thread_pool_size}")
        
        # 配置更保守的HTTP适配器
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=min(self.thread_pool_size, 10),
            pool_maxsize=min(self.thread_pool_size * 2, 20),
            max_retries=3,
            pool_block=False
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        self.lock = threading.Lock()
        self.downloaded_count = 0
        
        # 缓存历史日期列表
        self._service_dates_cache = {}
        
        # OpenStreetMap子域名
        self.osm_subdomains = ['a', 'b', 'c']
        
        # 任务优先级队列
        self.priority_queue = []
        
        # 错误统计
        self.error_stats = {
            'network_errors': 0,
            'tile_errors': 0,
            'api_errors': 0,
            'other_errors': 0
        }
    
    def get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        return random.choice(USER_AGENTS)
    
    def tile_to_quadkey(self, x: int, y: int, zoom: int) -> str:
        """将瓦片坐标转换为Bing Maps quadkey"""
        quadkey = []
        for i in range(zoom, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if (x & mask) != 0:
                digit += 1
            if (y & mask) != 0:
                digit += 2
            quadkey.append(str(digit))
        return ''.join(quadkey)
    
    def get_service_by_name(self, name: str) -> Optional[Dict]:
        """根据服务名称获取服务配置"""
        for service in self.services:
            if service.get('name') == name:
                return service
        return None
    
    def get_optimal_thread_pool_size(self) -> int:
        """根据系统资源动态计算最优线程池大小"""
        import os
        import psutil
        
        try:
            cpu_count = os.cpu_count() or 4
            available_memory = psutil.virtual_memory().available / (1024 * 1024)
            base_threads = int(cpu_count * 1.5)
            memory_based_threads = int(available_memory / 100)
            optimal_threads = min(base_threads, memory_based_threads)
            optimal_threads = max(4, min(optimal_threads, 100))
            config_threads = PROCESSING.get('thread_pool_size')
            if config_threads:
                optimal_threads = min(config_threads, optimal_threads)
            return optimal_threads
        except ImportError:
            return min(THREAD_POOL_SIZE, 50)
        except Exception:
            return min(THREAD_POOL_SIZE, 50)
    
    def _build_current_date_dict(self, service_config: Optional[Dict] = None) -> Dict:
        """构建当前影像日期字典
        
        Args:
            service_config: 服务配置，如果为None则使用默认配置
        
        Returns:
            当前影像日期字典
        """
        if service_config:
            name = service_config.get('name', 'Google Earth (Current)')
            description = service_config.get('description', '最新的全球卫星影像')
            url_template = service_config.get('url_template', 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}')
        else:
            name = 'Google Earth (Current)'
            description = '最新的全球卫星影像'
            url_template = 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}'
        
        return {
            'id': 1,
            'timestamp': 1735689600000,  # 固定时间戳 2025-01-01
            'date': '2025-01-01',  # 固定日期，不使用当前系统时间
            'name': name,
            'description': description,
            'url_template': url_template,
            'source': 'current_service'
        }
    
    def get_historical_dates_for_service(self, service_name: str,
                                           center_lat: float = None, center_lon: float = None, zoom: int = None) -> List[Dict]:
        """根据数据源类型获取可用的历史影像日期列表
        
        Args:
            service_name: 数据源名称
            center_lat: 中心纬度
            center_lon: 中心经度
            zoom: 缩放级别
        
        Returns:
            可用日期字典列表
        """
        cache_key = f"{service_name}_{center_lat}_{center_lon}_{zoom}"
        if cache_key in self._service_dates_cache:
            return self._service_dates_cache[cache_key]
        
        service = self.get_service_by_name(service_name)
        historical_support = service.get('historical_support', 'none') if service else 'none'
        
        dates = []
        dates.append(self._build_current_date_dict(service))
        
        wayback_success = False
        google_earth_success = False
        
        # 尝试使用 ESRI Wayback 服务
        if historical_support in ['wayback', 'both']:
            logger.info("正在使用 ESRI Wayback 历史影像服务...")
            
            if center_lat is not None and center_lon is not None and zoom is not None:
                try:
                    logger.info("查询区域可用的历史版本...")
                    wayback_api_url = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer"
                    
                    n = 1 << zoom
                    tile_x = int((center_lon + 180.0) / 360.0 * n)
                    tile_y = int((1.0 - math.log(math.tan(math.radians(center_lat)) + 1.0 / math.cos(math.radians(center_lat))) / math.pi) / 2.0 * n)
                    tile_x = max(0, min(tile_x, n - 1))
                    tile_y = max(0, min(tile_y, n - 1))
                    
                    query_url = f"https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/getWaybackItemsWithLocalChanges"
                    params = {
                        'f': 'json',
                        'x': tile_x,
                        'y': tile_y,
                        'level': zoom
                    }
                    
                    headers = {
                        'User-Agent': self.get_random_user_agent(),
                        'Accept': 'application/json',
                        'Referer': 'https://www.arcgis.com/'
                    }
                    
                    response = requests.get(query_url, params=params, headers=headers, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    
                    available_items = data.get('waybackItems', [])
                    logger.info(f"找到 {len(available_items)} 个可用的历史版本")
                    
                    for item in available_items:
                        release_num = item.get('releaseNum')
                        release_date = item.get('releaseDateLabel', '')
                        item_url = item.get('itemURL', '')
                        
                        if item_url:
                            item_url = item_url.replace('{level}', '{z}').replace('{row}', '{y}').replace('{col}', '{x}')
                        
                        if release_num and release_date:
                            dates.append({
                                'id': release_num,
                                'timestamp': int(datetime.strptime(release_date, '%Y-%m-%d').timestamp() * 1000) if release_date else 0,
                                'date': release_date,
                                'name': f"Wayback {release_date}",
                                'description': item.get('itemTitle', f"ESRI Wayback {release_date}"),
                                'url_template': item_url if item_url else f"https://wayback-a.maptiles.arcgis.com/arcgis/rest/services/world_imagery/wmts/1.0.0/default028mm/mapserver/tile/{release_num}/{{z}}/{{y}}/{{x}}",
                                'source': 'wayback'
                            })
                    
                    wayback_success = len(available_items) > 0
                    
                except Exception as e:
                    logger.error(f"查询 ESRI Wayback 可用版本时出错: {e}")
                    logger.info("使用配置文件中的版本列表作为备用...")
                    for wb_service in self.wayback_services:
                        date_str = wb_service['date']
                        dates.append({
                            'id': wb_service.get('id', len(dates) + 100),
                            'timestamp': int(datetime.strptime(date_str, '%Y-%m-%d').timestamp() * 1000),
                            'date': date_str,
                            'name': wb_service.get('name', date_str),
                            'description': wb_service.get('name', date_str),
                            'url_template': wb_service['url_template'],
                            'source': 'wayback'
                        })
                    wayback_success = len(self.wayback_services) > 0
            else:
                logger.info("未提供坐标信息，使用配置文件中的版本列表...")
                for wb_service in self.wayback_services:
                    date_str = wb_service['date']
                    dates.append({
                        'id': wb_service.get('id', len(dates) + 100),
                        'timestamp': int(datetime.strptime(date_str, '%Y-%m-%d').timestamp() * 1000),
                        'date': date_str,
                        'name': wb_service.get('name', date_str),
                        'description': wb_service.get('name', date_str),
                        'url_template': wb_service['url_template'],
                        'source': 'wayback'
                    })
                wayback_success = len(self.wayback_services) > 0
            
        # 尝试使用 Google Earth API 服务
        if (historical_support in ['google_earth_api', 'both']) or (not wayback_success and historical_support != 'none'):
            logger.info("正在使用 Google Earth API 历史影像服务...")
            if center_lat is not None and center_lon is not None and zoom is not None:
                try:
                    if not self.ge_client.initialize():
                        logger.warning("Google Earth客户端初始化失败，将只使用当前影像")
                    else:
                        n = 1 << zoom
                        tile_x = int((center_lon + 180.0) / 360.0 * n)
                        tile_y = int((1.0 - math.log(math.tan(math.radians(center_lat)) + 1.0 / math.cos(math.radians(center_lat))) / math.pi) / 2.0 * n)
                        tile_x = max(0, min(tile_x, n - 1))
                        tile_y = max(0, min(tile_y, n - 1))
                        
                        ge_dates = self.ge_client.get_dates_for_area(tile_x, tile_y, zoom)
                        
                        for ge_date in ge_dates:
                            date_str = ge_date['date']
                            dates.append({
                                'id': ge_date.get('packed_date', len(dates) + 100),
                                'timestamp': int(datetime.strptime(date_str, '%Y-%m-%d').timestamp() * 1000),
                                'date': date_str,
                                'name': f"{ge_date['year']}年{ge_date['month']}月影像 (Google Earth)",
                                'description': f"{date_str} 的历史影像 (Google Earth Flatfile API)",
                                'hex_date': ge_date['hex_date'],
                                'epoch': ge_date['epoch'],
                                'source': 'google_earth_api'
                            })
                        
                        google_earth_success = len(ge_dates) > 0
                except Exception as e:
                    logger.error(f"查询Google Earth历史影像日期时出错: {e}")
            else:
                logger.info("未提供坐标信息，无法查询Google Earth历史影像日期")
        
        elif historical_support == 'none':
            logger.info(f"数据源 '{service_name}' 不支持历史影像")
        
        # 按时间戳排序，确保最新的影像在前面
        dates.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        self._service_dates_cache[cache_key] = dates
        logger.info(f"成功获取 {len(dates)} 个影像服务版本")
        for date_info in dates:
            logger.debug(f"  - {date_info['name']}: {date_info['date']} - {date_info.get('description', '')}")
        
        return dates
    
    def get_current_and_previous_dates(self, service_name: str = None,
                                       center_lat: float = None, center_lon: float = None, zoom: int = None) -> Tuple[Optional[Dict], Optional[Dict]]:
        """获取当前影像和前一个时刻的影像日期信息
        
        Args:
            service_name: 数据源名称
            center_lat: 中心纬度
            center_lon: 中心经度
            zoom: 缩放级别
        
        Returns:
            (current_date, previous_date) 元组
        """
        if service_name is None:
            service_name = 'Google Earth'
        
        dates = self.get_historical_dates_for_service(service_name, center_lat, center_lon, zoom)
        if not dates:
            return None, None
        
        current_date = dates[0] if dates else None
        
        previous_date = None
        if len(dates) >= 2:
            for i in range(1, len(dates)):
                if dates[i].get('source') != 'current_service':
                    previous_date = dates[i]
                    logger.info(f"选择历史影像版本: {dates[i].get('date', 'unknown')} (ID: {dates[i].get('id', 'unknown')}, 来源: {dates[i].get('source', 'unknown')})")
                    break
        
        return current_date, previous_date
    
    def print_error_stats(self):
        """打印错误统计信息"""
        logger.info("\n=== 错误统计 ===")
        logger.info(f"网络错误: {self.error_stats['network_errors']}")
        logger.info(f"瓦片错误: {self.error_stats['tile_errors']}")
        logger.info(f"API错误: {self.error_stats['api_errors']}")
        logger.info(f"其他错误: {self.error_stats['other_errors']}")
        total_errors = sum(self.error_stats.values())
        logger.info(f"总计错误: {total_errors}")
        print("================")
    
    def download_tile_worker_with_url(self, url: str, save_path: str, headers: Dict) -> bool:
        """使用指定URL下载单个瓦片
        
        支持断点续传和瓦片缓存
        """
        if os.path.exists(save_path):
            file_size = os.path.getsize(save_path)
            if file_size > 100:
                if self.debug:
                    logger.debug(f"[调试] 瓦片已存在且有效，跳过下载: {save_path}")
                return True
            else:
                if self.debug:
                    logger.debug(f"[调试] 瓦片文件大小异常，删除后重新下载: {save_path}")
                try:
                    os.remove(save_path)
                except:
                    pass
        
        time.sleep(0.1)
        
        for attempt in range(RETRY_COUNT + 1):
            try:
                if attempt > 0:
                    if self.debug:
                        logger.debug(f"[调试] 重试下载瓦片 ({attempt+1}/{RETRY_COUNT+1}): {url}")
                    else:
                        logger.info(f"  重试下载瓦片 ({attempt+1}/{RETRY_COUNT+1}): {url}")
                elif self.debug:
                    logger.debug(f"[调试] 开始下载瓦片: {url}")
                
                headers_copy = headers.copy()
                if os.path.exists(save_path):
                    file_size = os.path.getsize(save_path)
                    headers_copy['Range'] = f"bytes={file_size}-"
                    if self.debug:
                        logger.debug(f"[调试] 尝试断点续传，已下载 {file_size} 字节")
                
                response = self.session.get(
                    url,
                    headers=headers_copy,
                    timeout=60,
                    stream=True,
                    verify=True,
                    allow_redirects=True
                )
                
                if response.status_code == 206:
                    if self.debug:
                        logger.debug(f"[调试] 断点续传成功，响应状态码: {response.status_code}")
                    mode = 'ab'
                else:
                    response.raise_for_status()
                    mode = 'wb'
                
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    error_msg = f"瓦片下载失败: 响应不是图像类型 ({content_type})"
                    if self.debug:
                        logger.debug(f"[调试] {error_msg}")
                        logger.debug(f"[调试] 响应内容: {response.text[:200]}...")
                    else:
                        logger.warning(f"  {error_msg}")
                    if attempt < RETRY_COUNT:
                        time.sleep(1.0 * (2 ** attempt))
                        continue
                    self.error_stats['tile_errors'] += 1
                    return False
                
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                
                with open(save_path, mode) as f:
                    for chunk in response.iter_content(chunk_size=4096):
                        if chunk:
                            f.write(chunk)
                            time.sleep(0.001)
                
                file_size = os.path.getsize(save_path)
                if file_size < 100:
                    error_msg = f"瓦片下载失败: 文件大小异常 ({file_size} 字节)"
                    if self.debug:
                        logger.debug(f"[调试] {error_msg}")
                    else:
                        logger.warning(f"  {error_msg}")
                    os.remove(save_path)
                    if attempt < RETRY_COUNT:
                        time.sleep(1.0 * (2 ** attempt))
                        continue
                    self.error_stats['tile_errors'] += 1
                    return False
                
                with self.lock:
                    self.downloaded_count += 1
                
                if self.debug:
                    logger.debug(f"[调试] 瓦片下载成功: {url} (大小: {file_size} 字节)")
                return True
                
            except requests.exceptions.RequestException as e:
                self.error_stats['network_errors'] += 1
                error_msg = f"网络请求失败 ({attempt+1}/{RETRY_COUNT+1}): {e}"
                if self.debug:
                    logger.debug(f"[调试] {error_msg}")
                    import traceback
                    logger.debug(traceback.format_exc())
                else:
                    logger.warning(f"  {error_msg}")
                if attempt < RETRY_COUNT:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                return False
            except Exception as e:
                self.error_stats['other_errors'] += 1
                error_msg = f"下载瓦片失败 ({attempt+1}/{RETRY_COUNT+1}): {e}"
                if self.debug:
                    logger.debug(f"[调试] {error_msg}")
                    import traceback
                    logger.debug(traceback.format_exc())
                else:
                    logger.warning(f"  {error_msg}")
                if attempt < RETRY_COUNT:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                return False
    
    def download_historical_tiles_batch(self, tile_coords: List[Tuple[int, int]], zoom: int,
                                        temp_dir: str, image_date_info: Optional[Dict] = None, 
                                        data_source_name: Optional[str] = None) -> int:
        """批量下载历史影像瓦片

        参数:
            tile_coords: 瓦片坐标列表
            zoom: 缩放级别
            temp_dir: 临时目录
            image_date_info: 影像日期信息，包含id和url_template或hex_date/epoch
            data_source_name: 数据源名称，如不指定则使用第一个服务
        """
        self.downloaded_count = 0
        total_tiles = len(tile_coords)
        failed_tiles = 0
        skipped_tiles = 0

        logger.info(f"开始处理 {total_tiles} 个瓦片的历史影像下载")
        logger.info(f"缩放级别: {zoom}")
        logger.info(f"临时目录: {temp_dir}")

        use_ge_api = (image_date_info and image_date_info.get('source') == 'google_earth_api')
        
        if use_ge_api:
            hex_date = image_date_info.get('hex_date', '')
            epoch = image_date_info.get('epoch', 0)
            date_str = image_date_info.get('date', 'unknown')
            name = image_date_info.get('name', 'Historical Imagery')
            logger.info("使用Google Earth Flatfile API下载历史影像")
            logger.info(f"  日期: {date_str}, 名称: {name}")
            logger.info(f"  hex_date: {hex_date}, epoch: {epoch}")
            
            if not self.ge_client.initialize():
                logger.error("Google Earth客户端初始化失败，无法下载历史影像")
                return 0
            
            tasks = []
            for x, y in tile_coords:
                tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
                
                if os.path.exists(tile_path) and os.path.getsize(tile_path) > 100:
                    logger.debug(f"  瓦片 {x},{y} 已存在，跳过下载")
                    skipped_tiles += 1
                    with self.lock:
                        self.downloaded_count += 1
                    continue
                
                tasks.append((x, y, tile_path, hex_date, epoch, zoom))
            
            actual_tiles_to_download = len(tasks)
            logger.info(f"跳过 {skipped_tiles} 个已存在的瓦片，实际需要下载 {actual_tiles_to_download} 个瓦片")
            
            if actual_tiles_to_download == 0:
                return self.downloaded_count
            
            logger.info(f"开始下载 {actual_tiles_to_download} 个瓦片 (Google Earth API)...")
            
            def ge_download_task(x, y, tile_path, h_date, ep, z):
                return self.ge_client.download_historical_tile(x, y, z, h_date, ep, tile_path)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.thread_pool_size, 5)) as executor:
                future_to_tile = {
                    executor.submit(ge_download_task, x, y, path, h_date, ep, z): (x, y)
                    for x, y, path, h_date, ep, z in tasks
                }
                
                completed = 0
                for future in concurrent.futures.as_completed(future_to_tile):
                    tile_coord = future_to_tile[future]
                    completed += 1
                    try:
                        result = future.result()
                        if result:
                            with self.lock:
                                self.downloaded_count += 1
                        else:
                            failed_tiles += 1
                            logger.warning(f"  瓦片 {tile_coord} 下载失败")
                    except Exception as e:
                        failed_tiles += 1
                        logger.error(f"  瓦片 {tile_coord} 下载异常: {e}")
                    
                    if completed % 10 == 0 or completed == actual_tiles_to_download:
                        progress = (completed / actual_tiles_to_download) * 100
                        logger.info(f"  进度: {completed}/{actual_tiles_to_download} ({progress:.1f}%)")
            
            success_rate = (self.downloaded_count / total_tiles) * 100 if total_tiles > 0 else 0
            logger.info("\n=== 下载完成 ===")
            logger.info(f"总瓦片数: {total_tiles}")
            logger.info(f"成功下载: {self.downloaded_count}")
            logger.info(f"失败下载: {failed_tiles}")
            logger.info(f"成功率: {success_rate:.1f}%")
            print("================")
            
            return self.downloaded_count

        download_configs = []
        
        if image_date_info and image_date_info.get('url_template'):
            version_id = image_date_info.get('id', 'unknown')
            date_str = image_date_info.get('date', 'unknown')
            name = image_date_info.get('name', 'Historical Imagery')
            source = image_date_info.get('source', 'unknown')
            logger.info(f"下载历史影像（版本ID: {version_id}, 日期: {date_str}, 名称: {name}, 来源: {source}")
            
            primary_url_template = image_date_info['url_template']
            logger.info(f"使用主要URL模板: {primary_url_template}")
            
            if source == 'wayback':
                backup_url_templates = []
                for wb_service in self.wayback_services:
                    if wb_service.get('id') != version_id:
                        backup_url_templates.append({
                            'url_template': wb_service['url_template'],
                            'date': wb_service['date'],
                            'id': wb_service['id']
                        })
                headers = {
                    'User-Agent': self.get_random_user_agent(),
                    'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Referer': 'https://www.arcgis.com/'
                }
            else:
                backup_url_templates = []
                headers = {
                    'User-Agent': self.get_random_user_agent(),
                    'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Referer': 'https://www.google.com/'
                }
        else:
            print("错误: 缺少影像日期信息，无法下载历史影像")
            return 0

        headers['Accept-Encoding'] = 'gzip, deflate, br'
        headers['Connection'] = 'keep-alive'
        headers['Cache-Control'] = 'no-cache'
        headers['Pragma'] = 'no-cache'

        logger.debug(f"使用Headers: User-Agent={headers.get('User-Agent', 'N/A')}")

        tasks = []
        for x, y in tile_coords:
            tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
            
            if os.path.exists(tile_path) and os.path.getsize(tile_path) > 100:
                    logger.debug(f"  瓦片 {x},{y} 已存在，跳过下载")
                    skipped_tiles += 1
                    with self.lock:
                        self.downloaded_count += 1
                    continue
            
            urls = []
            url_infos = []
            
            try:
                primary_url = primary_url_template.format(z=zoom, x=x, y=y)
                urls.append(primary_url)
                url_infos.append({'url': primary_url, 'date': date_str, 'id': version_id})
                
                for backup_info in backup_url_templates:
                    try:
                        backup_template = backup_info['url_template']
                        backup_url = backup_template.format(z=zoom, x=x, y=y)
                        urls.append(backup_url)
                        url_infos.append({'url': backup_url, 'date': backup_info['date'], 'id': backup_info['id']})
                    except Exception as e:
                        logger.error(f"  构建备用URL时出错: {e}")
                        continue
                
                logger.debug(f"  瓦片 {x},{y}: 准备 {len(urls)} 个URL")
                tasks.append((x, y, tile_path, urls, headers, url_infos))
                
            except KeyError as e:
                logger.error(f"  URL模板格式化错误: {e}")
                logger.error(f"  模板: {primary_url_template}")
                logger.error(f"  跳过瓦片 {x},{y} 下载")
                failed_tiles += 1
            except Exception as e:
                logger.error(f"  生成瓦片URL时出错: {e}")
                logger.error(f"  跳过瓦片 {x},{y} 下载")
                failed_tiles += 1

        actual_tiles_to_download = len(tasks)
        logger.info(f"跳过 {skipped_tiles} 个已存在的瓦片，实际需要下载 {actual_tiles_to_download} 个瓦片")

        if actual_tiles_to_download == 0:
            logger.info("所有瓦片都已存在，无需下载")
            return self.downloaded_count

        logger.info(f"开始下载 {actual_tiles_to_download} 个瓦片...")
        logger.info(f"使用线程池大小: {self.thread_pool_size}")

        def download_with_fallback(x, y, tile_path, urls, headers, url_infos):
            """使用多个URL尝试下载瓦片"""
            for url_index, url in enumerate(urls):
                info = url_infos[url_index] if url_index < len(url_infos) else {}
                date_info = info.get('date', 'unknown')
                id_info = info.get('id', 'unknown')
                logger.debug(f"  瓦片 {x},{y}: 尝试下载 ({url_index + 1}/{len(urls)}) - 日期: {date_info}, ID: {id_info}")
                logger.debug(f"    URL: {url}")
                try:
                    success = self.download_tile_worker_with_url(url, tile_path, headers)
                    if success:
                        logger.debug(f"  瓦片 {x},{y}: 下载成功 (使用日期: {date_info})")
                        return True, info
                    else:
                        logger.warning(f"  瓦片 {x},{y}: URL {url_index + 1} 下载失败，尝试下一个URL")
                except Exception as e:
                    logger.error(f"  瓦片 {x},{y}: URL {url_index + 1} 下载异常: {e}")
                    continue
            logger.warning(f"  瓦片 {x},{y}: 所有URL都下载失败")
            return False, {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_pool_size) as executor:
            future_to_tile = {
                executor.submit(download_with_fallback, x, y, path, urls, hdr, infos): (x, y)
                for x, y, path, urls, hdr, infos in tasks
            }
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_tile):
                tile_coord = future_to_tile[future]
                completed += 1
                try:
                    result, info = future.result()
                    if not result:
                        failed_tiles += 1
                        logger.warning(f"  瓦片 {tile_coord} 最终下载失败")
                    else:
                        with self.lock:
                            self.downloaded_count += 1
                except Exception as e:
                    failed_tiles += 1
                    logger.error(f"  瓦片 {tile_coord} 下载异常: {e}")
                
                if completed % 10 == 0 or completed == actual_tiles_to_download:
                    progress = (completed / actual_tiles_to_download) * 100
                    logger.info(f"  进度: {completed}/{actual_tiles_to_download} ({progress:.1f}%)")

        success_rate = (self.downloaded_count / total_tiles) * 100 if total_tiles > 0 else 0
        actual_success_rate = (self.downloaded_count - skipped_tiles) / actual_tiles_to_download * 100 if actual_tiles_to_download > 0 else 0
        
        logger.info("\n=== 下载完成 ===")
        logger.info(f"总瓦片数: {total_tiles}")
        logger.info(f"跳过的瓦片: {skipped_tiles}")
        logger.info(f"实际下载: {actual_tiles_to_download}")
        logger.info(f"成功下载: {self.downloaded_count - skipped_tiles}")
        logger.info(f"失败下载: {failed_tiles}")
        logger.info(f"总体成功率: {success_rate:.1f}%")
        logger.info(f"实际下载成功率: {actual_success_rate:.1f}%")
        print("================")
        
        self.print_error_stats()
        
        return self.downloaded_count
    
    def parse_kml_file(self, kml_file_path: str) -> List[Dict]:
        """解析KML文件，提取矩形边界坐标"""
        buffers = []
        
        try:
            tree = ET.parse(kml_file_path)
            root = tree.getroot()
            
            namespace = ''
            if '}' in root.tag:
                namespace = root.tag.split('}')[0].strip('{')
            
            ns = {}
            if namespace:
                ns['kml'] = namespace
            
            placemarks = []
            if namespace:
                placemarks = root.findall('.//kml:Placemark', namespaces=ns)
            else:
                placemarks = root.findall('.//Placemark')
            
            for placemark in placemarks:
                buffer_info = {}
                
                buffer_id = placemark.get('id', '')
                buffer_info['id'] = buffer_id
                
                extended_data = None
                if namespace:
                    extended_data = placemark.find('.//kml:ExtendedData', namespaces=ns)
                else:
                    extended_data = placemark.find('.//ExtendedData')
                
                if extended_data is not None:
                    schema_data = None
                    if namespace:
                        schema_data = extended_data.find('.//kml:SchemaData', namespaces=ns)
                    else:
                        schema_data = extended_data.find('.//SchemaData')
                    
                    if schema_data is not None:
                        simple_data_list = []
                        if namespace:
                            simple_data_list = schema_data.findall('.//kml:SimpleData', namespaces=ns)
                        else:
                            simple_data_list = schema_data.findall('.//SimpleData')
                        
                        for simple_data in simple_data_list:
                            name = simple_data.get('name')
                            value = simple_data.text
                            if name and value:
                                buffer_info[name] = value
                
                coordinates_elem = None
                if namespace:
                    coordinates_elem = placemark.find('.//kml:coordinates', namespaces=ns)
                else:
                    coordinates_elem = placemark.find('.//coordinates')
                if coordinates_elem is not None and coordinates_elem.text:
                    coords_text = coordinates_elem.text.strip()
                    coords_list = re.findall(r'[-+]?[0-9]*\.?[0-9]+,[-+]?[0-9]*\.?[0-9]+', coords_text)
                    
                    if len(coords_list) >= 4:
                        lons = []
                        lats = []
                        for coord in coords_list:
                            lon, lat = map(float, coord.split(','))
                            lons.append(lon)
                            lats.append(lat)
                        
                        buffer_info['min_lon'] = min(lons)
                        buffer_info['max_lon'] = max(lons)
                        buffer_info['min_lat'] = min(lats)
                        buffer_info['max_lat'] = max(lats)
                        buffer_info['center_lon'] = (buffer_info['min_lon'] + buffer_info['max_lon']) / 2
                        buffer_info['center_lat'] = (buffer_info['min_lat'] + buffer_info['max_lat']) / 2
                        
                        buffers.append(buffer_info)
            
            logger.info(f"成功解析 {len(buffers)} 个矩形边界")
            return buffers
        except Exception as e:
            logger.error(f"解析KML文件时出错: {e}")
            return []
    
    @staticmethod
    def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """将经纬度转换为瓦片坐标"""
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        xtile = int((lon + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return xtile, ytile
    
    def calculate_zoom_level(self, lat_min: float, lat_max: float, lon_min: float, lon_max: float, tile_size: int = 512) -> int:
        """计算合适的缩放级别"""
        from config import PROCESSING
        
        lat_span = abs(lat_max - lat_min)
        lon_span = abs(lon_max - lon_min)
        
        default_zoom = PROCESSING.get('default_zoom', 15)
        max_zoom = PROCESSING.get('max_zoom', 19)
        min_zoom = PROCESSING.get('min_zoom', 1)
        
        default_zoom = max(min_zoom, min(default_zoom, max_zoom))
        
        center_lat = (lat_min + lat_max) / 2
        center_lon = (lon_min + lon_max) / 2
        
        x1, y1 = self.latlon_to_tile(lat_min, lon_min, default_zoom)
        x2, y2 = self.latlon_to_tile(lat_max, lon_max, default_zoom)
        
        tiles_width = abs(x2 - x1) + 1
        tiles_height = abs(y2 - y1) + 1
        
        earth_circumference = 40075016.686
        meters_per_pixel = earth_circumference / (tile_size * (2 ** default_zoom))
        
        current_lat_span = tiles_height * tile_size * meters_per_pixel / 111320
        current_lon_span = tiles_width * tile_size * meters_per_pixel / (111320 * math.cos(math.radians(center_lat)))
        
        if current_lat_span >= lat_span and current_lon_span >= lon_span:
            return default_zoom
        
        for zoom in range(default_zoom + 1, max_zoom + 1):
            x1, y1 = self.latlon_to_tile(lat_min, lon_min, zoom)
            x2, y2 = self.latlon_to_tile(lat_max, lon_max, zoom)
            
            tiles_width = abs(x2 - x1) + 1
            tiles_height = abs(y2 - y1) + 1
            
            meters_per_pixel = earth_circumference / (tile_size * (2 ** zoom))
            
            current_lat_span = tiles_height * tile_size * meters_per_pixel / 111320
            current_lon_span = tiles_width * tile_size * meters_per_pixel / (111320 * math.cos(math.radians(center_lat)))
            
            if current_lat_span >= lat_span and current_lon_span >= lon_span:
                return zoom
        
        for zoom in range(default_zoom - 1, min_zoom - 1, -1):
            x1, y1 = self.latlon_to_tile(lat_min, lon_min, zoom)
            x2, y2 = self.latlon_to_tile(lat_max, lon_max, zoom)
            
            tiles_width = abs(x2 - x1) + 1
            tiles_height = abs(y2 - y1) + 1
            
            meters_per_pixel = earth_circumference / (tile_size * (2 ** zoom))
            
            current_lat_span = tiles_height * tile_size * meters_per_pixel / 111320
            current_lon_span = tiles_width * tile_size * meters_per_pixel / (111320 * math.cos(math.radians(center_lat)))
            
            if current_lat_span >= lat_span and current_lon_span >= lon_span:
                return zoom
        
        return default_zoom
    
    def download_tile_worker(self, service: Dict, x: int, y: int, zoom: int, save_path: str) -> bool:
        """下载单个瓦片"""
        url_template = service['url_template']
        
        if '{quadkey}' in url_template:
            quadkey = self.tile_to_quadkey(x, y, zoom)
            url = url_template.format(quadkey=quadkey)
        elif '{q}' in url_template:
            quadkey = self.tile_to_quadkey(x, y, zoom)
            url = url_template.format(q=quadkey, z=zoom, x=x, y=y)
        elif '{s}' in url_template:
            subdomain = random.choice(self.osm_subdomains)
            url = url_template.format(s=subdomain, z=zoom, x=x, y=y)
        else:
            url = url_template.format(z=zoom, x=x, y=y)
        
        headers = service.get('headers', {}).copy()
        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.get_random_user_agent()
        headers['Accept-Encoding'] = 'gzip, deflate, br'
        headers['Connection'] = 'keep-alive'
        
        for attempt in range(RETRY_COUNT + 1):
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    stream=True,
                    verify=True
                )
                response.raise_for_status()
                
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                with self.lock:
                    self.downloaded_count += 1
                return True
                
            except Exception as e:
                if attempt < RETRY_COUNT:
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                logger.error(f"下载瓦片 {x}_{y}_{zoom} 失败（尝试{attempt+1}次）: {e}")
                return False
    
    def download_tiles_batch(self, service: Dict, tile_coords: List[Tuple[int, int]], zoom: int, temp_dir: str) -> int:
        """批量下载瓦片"""
        self.downloaded_count = 0
        total_tiles = len(tile_coords)
        failed_tiles = 0
        
        logger.info(f"开始批量下载瓦片: 共{total_tiles}个瓦片，使用服务: {service.get('name', 'Unknown')}")
        
        tasks = []
        for x, y in tile_coords:
            tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
            tasks.append((x, y, tile_path))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_pool_size) as executor:
            future_to_tile = {
                executor.submit(self.download_tile_worker, service, x, y, zoom, path): (x, y)
                for x, y, path in tasks
            }
            for future in concurrent.futures.as_completed(future_to_tile):
                tile_coord = future_to_tile[future]
                try:
                    result = future.result()
                    if not result:
                        failed_tiles += 1
                        logger.warning(f"  瓦片 {tile_coord} 下载失败")
                except Exception as e:
                    failed_tiles += 1
                    logger.error(f"  瓦片 {tile_coord} 下载异常: {e}")
        
        success_rate = (self.downloaded_count / total_tiles) * 100 if total_tiles > 0 else 0
        logger.info(f"瓦片下载完成: 成功 {self.downloaded_count}/{total_tiles} ({success_rate:.1f}%)，失败 {failed_tiles} 个")
        return self.downloaded_count
    
    def stitch_tiles(self, temp_dir: str, tile_count: int, save_path: str, kml_bounds: Optional[Dict] = None) -> bool:
        """拼接瓦片生成完整图像"""
        try:
            tile_files = []
            for filename in os.listdir(temp_dir):
                if filename.startswith('tile_') and filename.endswith('.png'):
                    tile_files.append(os.path.join(temp_dir, filename))
            
            if not tile_files:
                logger.error("未找到瓦片文件")
                return False
            
            tiles_info = []
            for tile_file in tile_files:
                filename = os.path.basename(tile_file)
                parts = filename.replace('tile_', '').replace('.png', '').split('_')
                if len(parts) == 3:
                    x, y, z = int(parts[0]), int(parts[1]), int(parts[2])
                    tiles_info.append({'x': x, 'y': y, 'z': z, 'file': tile_file})
            
            if not tiles_info:
                logger.error("无法解析瓦片坐标信息")
                return False
            
            tiles_info.sort(key=lambda t: (t['y'], t['x']))
            
            first_tile = Image.open(tiles_info[0]['file'])
            tile_width, tile_height = first_tile.size
            first_tile.close()
            
            result_width = tile_width * tile_count
            result_height = tile_height * tile_count
            result_image = Image.new('RGB', (result_width, result_height))
            
            x_coords = [t['x'] for t in tiles_info]
            y_coords = [t['y'] for t in tiles_info]
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            
            for tile_info in tiles_info:
                x, y = tile_info['x'], tile_info['y']
                pos_x = (x - min_x) * tile_width
                pos_y = (y - min_y) * tile_height
                
                tile_image = Image.open(tile_info['file'])
                result_image.paste(tile_image, (pos_x, pos_y))
                tile_image.close()
            
            if kml_bounds:
                zoom = tiles_info[0]['z']
                result_image = self.crop_to_kml_bounds(result_image, kml_bounds, min_x, min_y, zoom, tile_width, tile_height)
            
            result_image.save(save_path, 'PNG')
            result_image.close()
            
            logger.info(f"成功拼接 {len(tiles_info)} 个瓦片，生成 {result_width}x{result_height} 像素影像")
            return True
            
        except Exception as e:
            logger.error(f"拼接瓦片时出错: {e}")
            return False
    
    def crop_to_kml_bounds(self, image: Image.Image, kml_bounds: Dict, min_tile_x: int, min_tile_y: int, zoom: int, tile_width: int, tile_height: int) -> Image.Image:
        """根据KML边界裁剪图像"""
        try:
            min_lon, max_lon = kml_bounds['min_lon'], kml_bounds['max_lon']
            min_lat, max_lat = kml_bounds['min_lat'], kml_bounds['max_lat']
            
            logger.info(f"KML边界: 经度({min_lon:.6f} - {max_lon:.6f}), 纬度({min_lat:.6f} - {max_lat:.6f})")
            
            total_pixels = 256 * (2 ** zoom)
            
            def lon_to_pixel_x(lon, zoom):
                return int((lon + 180.0) / 360.0 * total_pixels)
            
            def lat_to_pixel_y(lat, zoom):
                lat_rad = math.radians(lat)
                return int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * total_pixels)
            
            left_pixel = lon_to_pixel_x(min_lon, zoom)
            right_pixel = lon_to_pixel_x(max_lon, zoom)
            top_pixel = lat_to_pixel_y(max_lat, zoom)
            bottom_pixel = lat_to_pixel_y(min_lat, zoom)
            
            min_tile_left_pixel = min_tile_x * tile_width
            min_tile_top_pixel = min_tile_y * tile_height
            
            left = left_pixel - min_tile_left_pixel
            top = top_pixel - min_tile_top_pixel
            right = right_pixel - min_tile_left_pixel
            bottom = bottom_pixel - min_tile_top_pixel
            
            width, height = image.size
            left = max(0, min(left, width - 1))
            top = max(0, min(top, height - 1))
            right = max(left + 1, min(right, width))
            bottom = max(top + 1, min(bottom, height))
            
            if right <= left or bottom <= top:
                logger.warning("裁剪区域无效，返回原图")
                return image
            
            cropped_image = image.crop((left, top, right, bottom))
            
            logger.info(f"精确裁剪图像: 位置({left}, {top}, {right}, {bottom}), 尺寸({right-left}x{bottom-top})")
            return cropped_image
            
        except Exception as e:
            logger.error(f"裁剪图像时出错: {e}")
            return image
    
    def download_satellite_image(self, center_lat: float, center_lon: float, zoom: int,
                                save_path: Optional[str] = None, tile_count: int = 3, kml_bounds: Optional[Dict] = None,
                                image_type: str = 'current', image_date_info: Optional[Dict] = None, service_name: str = None) -> bool:
        """下载卫星影像

        参数:
            center_lat: 中心纬度
            center_lon: 中心经度
            zoom: 缩放级别
            save_path: 保存路径
            tile_count: 瓦片数量
            kml_bounds: KML边界
            image_type: 影像类型，'current'表示当前影像，'previous'表示前一个时刻的影像
            image_date_info: 影像日期信息，包含id和url_template
            service_name: 服务名称，None表示使用默认服务
        """
        try:
            if service_name:
                service = self.get_service_by_name(service_name)
                if not service:
                    logger.warning(f"警告: 未找到服务 '{service_name}'，使用默认服务")
                    service = self.services[0]
            else:
                service = self.services[0]

            max_zoom = service['max_zoom']
            if zoom > max_zoom:
                logger.warning(f"缩放级别 {zoom} 超过服务最大限制 {max_zoom}")
                zoom = max_zoom

            if kml_bounds:
                min_lon, max_lon = kml_bounds['min_lon'], kml_bounds['max_lon']
                min_lat, max_lat = kml_bounds['min_lat'], kml_bounds['max_lat']

                original_zoom = zoom
                while zoom > 1:
                    x_tl, y_tl = self.latlon_to_tile(max_lat, min_lon, zoom)
                    x_tr, y_tr = self.latlon_to_tile(max_lat, max_lon, zoom)
                    x_bl, y_bl = self.latlon_to_tile(min_lat, min_lon, zoom)
                    x_br, y_br = self.latlon_to_tile(min_lat, max_lon, zoom)

                    x_min = min(x_tl, x_tr, x_bl, x_br)
                    x_max = max(x_tl, x_tr, x_bl, x_br)
                    y_min = min(y_tl, y_tr, y_bl, y_br)
                    y_max = max(y_tl, y_tr, y_bl, y_br)

                    tile_count_x = x_max - x_min + 1
                    tile_count_y = y_max - y_min + 1

                    if tile_count_x <= 10000 and tile_count_y <= 10000:
                        break
                    else:
                        zoom -= 1
                        logger.warning(f"瓦片数量过大({tile_count_x}x{tile_count_y})，降低缩放级别到{zoom}")

                if original_zoom != zoom:
                    logger.info(f"缩放级别从{original_zoom}调整到{zoom}")

                logger.info(f"根据KML边界计算瓦片范围: X({x_min}-{x_max}), Y({y_min}-{y_max}), 共{tile_count_x}x{tile_count_y}瓦片")
            else:
                center_x, center_y = self.latlon_to_tile(center_lat, center_lon, zoom)
                x_min = center_x - tile_count // 2
                x_max = center_x + tile_count // 2
                y_min = center_y - tile_count // 2
                y_max = center_y + tile_count // 2
                tile_count_x = tile_count
                tile_count_y = tile_count

            is_historical = (image_type == 'previous')
            if is_historical and image_date_info:
                date_str = image_date_info.get('date', 'unknown')
                name = image_date_info.get('name', 'Historical Imagery')
                logger.info(f"下载历史影像（日期: {date_str}, 名称: {name}）: 中心({center_lat:.6f}, {center_lon:.6f}), "
                      f"缩放级别{zoom}, {tile_count_x}x{tile_count_y}瓦片")
            else:
                logger.info(f"下载 {service['name']} 当前影像: 中心({center_lat:.6f}, {center_lon:.6f}), "
                      f"缩放级别{zoom}, {tile_count_x}x{tile_count_y}瓦片")

            if is_historical:
                temp_dir = 'temp_tiles_previous'
            else:
                temp_dir = 'temp_tiles_current'
            
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            
            os.makedirs(temp_dir, exist_ok=True)
            logger.info(f"使用临时目录: {temp_dir}")

            tile_coords = [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]
            logger.info(f"生成 {len(tile_coords)} 个瓦片坐标")

            if image_date_info and image_date_info.get('url_template'):
                logger.info("开始下载影像瓦片（使用指定URL模板）...")
                tiles_downloaded = self.download_historical_tiles_batch(tile_coords, zoom, temp_dir, image_date_info, service_name)
            else:
                logger.info("开始下载当前影像瓦片...")
                tiles_downloaded = self.download_tiles_batch(service, tile_coords, zoom, temp_dir)

            logger.info(f"瓦片下载完成: {tiles_downloaded}/{len(tile_coords)} 成功")

            if tiles_downloaded == 0:
                logger.error(f"错误: 所有瓦片下载失败，无法生成影像")
                logger.error("提示: 请检查网络连接、服务URL配置和影像日期信息")
                shutil.rmtree(temp_dir)
                logger.info("临时目录已清理")
                return False

            if tiles_downloaded > 0 and save_path:
                try:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    logger.info(f"开始拼接瓦片，保存到: {save_path}")

                    if self.stitch_tiles(temp_dir, max(tile_count_x, tile_count_y), save_path, kml_bounds):
                        logger.info(f"影像已成功保存到: {save_path}")
                        shutil.rmtree(temp_dir)
                        logger.info("临时目录已清理")
                        return True
                    else:
                        logger.error("错误: 瓦片拼接失败")
                        logger.error("提示: 请检查临时目录权限和磁盘空间")
                except Exception as e:
                    logger.error(f"错误: 拼接瓦片时发生异常 - {e}")
                    import traceback
                    logger.error(traceback.format_exc())

            try:
                shutil.rmtree(temp_dir)
                logger.info("临时目录已清理")
            except Exception as e:
                logger.error(f"错误: 清理临时目录时发生异常 - {e}")
            return False
        except Exception as e:
            logger.error(f"错误: 下载卫星影像时发生异常 - {e}")
            try:
                temp_dir = PATHS.get('temp_tiles_dir', 'temp_tiles')
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info("临时目录已清理")
            except:
                pass
            return False
    
    def png_to_geotiff(self, png_path: str, tiff_path: str, bounds: Dict) -> bool:
        """将PNG图像转换为带有地理参考的TIFF图像"""
        try:
            with Image.open(png_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                width, height = img.size
                img_array = np.array(img)
            
            min_lon = bounds['min_lon']
            max_lon = bounds['max_lon']
            min_lat = bounds['min_lat']
            max_lat = bounds['max_lat']
            
            transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)
            
            crs = rasterio.CRS.from_wkt(WGS84_WKT)
            
            with rasterio.open(
                tiff_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=3,
                dtype=img_array.dtype,
                crs=crs,
                transform=transform,
                compress='lzw'
            ) as dst:
                dst.write(img_array[:, :, 0], 1)
                dst.write(img_array[:, :, 1], 2)
                dst.write(img_array[:, :, 2], 3)
            
            logger.info(f"成功生成带地理参考的TIFF: {tiff_path}")
            return True
            
        except Exception as e:
            logger.error(f"转换PNG到TIFF时出错: {e}")
            return False
    
    def process_kml_to_tiff(self, kml_file_path: str, output_dir: Optional[str] = None,
                             download_mode: str = 'current', service_name: str = None) -> bool:
        """处理KML文件生成TIFF图像

        参数:
            kml_file_path: KML文件路径
            output_dir: 输出目录
            download_mode: 下载模式，'current'表示仅当前影像，'previous'表示仅前一个时刻影像，
                          'both'表示同时下载当前和前一个时刻影像进行对比
            service_name: 服务名称，None表示使用默认服务
        """
        if not os.path.exists(kml_file_path):
            logger.error(f"KML文件不存在: {kml_file_path}")
            return False

        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(kml_file_path), 'tiff_output')

        kml_filename = os.path.splitext(os.path.basename(kml_file_path))[0]
        kml_output_dir = os.path.join(output_dir, kml_filename)

        png_output_dir = os.path.join(kml_output_dir, 'png')
        tiff_output_dir = os.path.join(kml_output_dir, 'tif')

        if download_mode in ['previous', 'both']:
            png_previous_dir = os.path.join(kml_output_dir, 'png_previous')
            tiff_previous_dir = os.path.join(kml_output_dir, 'tif_previous')
            os.makedirs(png_previous_dir, exist_ok=True)
            os.makedirs(tiff_previous_dir, exist_ok=True)

        os.makedirs(png_output_dir, exist_ok=True)
        os.makedirs(tiff_output_dir, exist_ok=True)

        logger.info(f"KML文件输出目录: {kml_output_dir}")
        logger.info(f"PNG文件保存目录: {png_output_dir}")
        logger.info(f"TIFF文件保存目录: {tiff_output_dir}")
        if download_mode in ['previous', 'both']:
            logger.info(f"历史PNG文件保存目录: {png_previous_dir}")
            logger.info(f"历史TIFF文件保存目录: {tiff_previous_dir}")

        buffers = self.parse_kml_file(kml_file_path)
        if not buffers:
            logger.error("未找到有效的缓冲区数据")
            return False

        current_date, previous_date = self.get_current_and_previous_dates(service_name)

        if not buffers:
            first_buffer = None
        else:
            first_buffer = buffers[0]
        
        if first_buffer:
            query_lat = first_buffer['center_lat']
            query_lon = first_buffer['center_lon']
            query_zoom = self.calculate_zoom_level(
                first_buffer['min_lat'], first_buffer['max_lat'],
                first_buffer['min_lon'], first_buffer['max_lon']
            )
            current_date, previous_date = self.get_current_and_previous_dates(service_name, query_lat, query_lon, query_zoom)

        if current_date and current_date.get('date'):
            current_timestamp = current_date['date'].replace('-', '')
            logger.info(f"当前影像时间戳: {current_timestamp}")
            if current_date.get('url_template'):
                logger.debug(f"当前影像URL模板: {current_date['url_template']}")
        else:
            # 使用固定的默认日期，不使用当前系统时间
            current_timestamp = '20251231'
            logger.info(f"当前影像时间戳: {current_timestamp} (使用默认日期)")

        if previous_date and previous_date.get('date'):
            previous_timestamp = previous_date['date'].replace('-', '')
            logger.info(f"历史影像时间戳: {previous_timestamp}")
            if previous_date.get('url_template'):
                logger.debug(f"历史影像URL模板: {previous_date['url_template']}")
            # 验证历史影像和当前影像的URL是否不同
            if current_date and current_date.get('url_template') and previous_date.get('url_template'):
                if current_date['url_template'] != previous_date['url_template']:
                    logger.info("[OK] 历史影像和当前影像使用不同的URL模板")
                else:
                    logger.error("[ERROR] 历史影像和当前影像使用相同的URL模板")
        else:
            # 使用固定的历史默认日期，不使用当前系统时间
            previous_timestamp = '20241231'
            logger.info(f"历史影像时间戳: {previous_timestamp} (使用默认历史日期)")

        success_count = 0
        previous_success_count = 0

        for i, buffer_info in enumerate(buffers):
            logger.info(f"\n处理缓冲区 {i+1}/{len(buffers)}: {buffer_info.get('id', 'Unknown')}")

            zoom = self.calculate_zoom_level(
                buffer_info['min_lat'], buffer_info['max_lat'],
                buffer_info['min_lon'], buffer_info['max_lon']
            )

            buffer_id = buffer_info.get('id', f'buffer_{i+1}')

            if download_mode in ['current', 'both']:
                png_filename = f"{current_timestamp}_{buffer_id}.png"
                png_path = os.path.join(png_output_dir, png_filename)
                tiff_filename = f"{current_timestamp}_{buffer_id}.tif"
                tiff_path = os.path.join(tiff_output_dir, tiff_filename)

                logger.info(f"\n[当前影像] 下载缓冲区 {buffer_id} 的当前影像...")
                logger.info(f"  保存路径: {png_path}")
                logger.info(f"  使用影像信息: {current_date.get('name', 'Unknown')} (日期: {current_date.get('date', 'unknown')})")
                
                if self.download_satellite_image(
                    buffer_info['center_lat'], buffer_info['center_lon'],
                    zoom, png_path, tile_count=3, kml_bounds=buffer_info,
                    image_type='current', image_date_info=current_date,
                    service_name=service_name
                ):
                    if self.png_to_geotiff(png_path, tiff_path, buffer_info):
                        success_count += 1
                        logger.info(f"[当前影像] 成功生成: {tiff_path}")
                    else:
                        logger.error(f"[当前影像] TIFF转换失败")
                else:
                    logger.error(f"[当前影像] 影像下载失败")

                time.sleep(1)

            if download_mode in ['previous', 'both'] and previous_date is not None:
                png_filename = f"{previous_timestamp}_{buffer_id}.png"
                png_path = os.path.join(png_previous_dir, png_filename)
                tiff_filename = f"{previous_timestamp}_{buffer_id}.tif"
                tiff_path = os.path.join(tiff_previous_dir, tiff_filename)

                logger.info(f"\n[历史影像] 下载缓冲区 {buffer_id} 的历史影像...")
                logger.info(f"  保存路径: {png_path}")
                logger.info(f"  使用影像信息: {previous_date.get('name', 'Unknown')} (日期: {previous_date.get('date', 'unknown')})")
                
                if self.download_satellite_image(
                    buffer_info['center_lat'], buffer_info['center_lon'],
                    zoom, png_path, tile_count=3, kml_bounds=buffer_info,
                    image_type='previous', image_date_info=previous_date,
                    service_name=service_name
                ):
                    if self.png_to_geotiff(png_path, tiff_path, buffer_info):
                        previous_success_count += 1
                        logger.info(f"[历史影像] 成功生成: {tiff_path}")
                    else:
                        logger.error(f"[历史影像] TIFF转换失败")
                else:
                    logger.error(f"[历史影像] 影像下载失败")

                time.sleep(1)
            elif download_mode in ['previous', 'both'] and previous_date is None:
                logger.warning(f"\n[历史影像] 跳过缓冲区 {buffer_id} 的历史影像下载：未找到可用的历史影像日期")

        logger.info(f"\n处理完成:")
        if download_mode in ['current', 'both']:
            logger.info(f"  当前影像: {success_count}/{len(buffers)} 个缓冲区成功生成TIFF图像")
        if download_mode in ['previous', 'both']:
            logger.info(f"  历史影像: {previous_success_count}/{len(buffers)} 个缓冲区成功生成TIFF图像")

        return success_count > 0 or previous_success_count > 0
