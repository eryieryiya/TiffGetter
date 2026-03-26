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
from datetime import datetime
from PIL import Image
from typing import List, Dict, Tuple, Optional
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from xml.etree import ElementTree as ET

from config import (
    THREAD_POOL_SIZE, REQUEST_TIMEOUT, RETRY_COUNT, 
    USER_AGENTS, SATELLITE_SERVICES, WGS84_WKT,
    PATHS, WAYBACK_SERVICES
)


class SatelliteToTiffConverter:
    def __init__(self, debug=False):
        """初始化卫星图像转换器
        
        Args:
            debug: 是否开启调试模式
        """
        # 卫星影像服务配置
        self.services = SATELLITE_SERVICES
        
        # Wayback历史影像服务配置
        self.wayback_config = WAYBACK_SERVICES
        self.wayback_enabled = self.wayback_config.get('enabled', False)
        self.wayback_api_url = self.wayback_config.get('api_url', '')
        self.wayback_base_url = self.wayback_config.get('wayback_base_url', 'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile')
        
        # 会话池配置
        self.session = requests.Session()
        
        # 动态线程池大小 - 减少并发连接数以避免网络错误
        self.thread_pool_size = min(self.get_optimal_thread_pool_size(), 20)  # 限制最大线程数为20
        self.debug = debug
        
        if self.debug:
            print(f"[调试模式] 使用动态线程池大小: {self.thread_pool_size}")
        else:
            print(f"使用动态线程池大小: {self.thread_pool_size}")
        
        # 配置更保守的HTTP适配器
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=min(self.thread_pool_size, 10),  # 减少连接池大小
            pool_maxsize=min(self.thread_pool_size * 2, 20),  # 减少最大连接数
            max_retries=3,  # 减少重试次数以避免连接堆积
            pool_block=False
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        self.lock = threading.Lock()
        self.downloaded_count = 0
        
        # 缓存Wayback日期列表
        self._wayback_dates = None
        
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
            # 获取CPU核心数
            cpu_count = os.cpu_count() or 4
            
            # 获取可用内存（MB）
            available_memory = psutil.virtual_memory().available / (1024 * 1024)
            
            # 基础线程数 = CPU核心数 * 1.5
            base_threads = int(cpu_count * 1.5)
            
            # 根据内存调整
            # 假设每个线程需要约100MB内存
            memory_based_threads = int(available_memory / 100)
            
            # 取两者的最小值
            optimal_threads = min(base_threads, memory_based_threads)
            
            # 确保线程数在合理范围内
            optimal_threads = max(4, min(optimal_threads, 100))
            
            # 从配置中获取线程池大小，如果配置了则使用配置值
            config_threads = PROCESSING.get('thread_pool_size')
            if config_threads:
                optimal_threads = min(config_threads, optimal_threads)
            
            return optimal_threads
        except ImportError:
            # 如果没有psutil库，使用默认值
            return min(THREAD_POOL_SIZE, 50)
        except Exception:
            # 出错时使用默认值
            return min(THREAD_POOL_SIZE, 50)
    
    def _build_current_date_dict(self, service_config: Optional[Dict] = None) -> Dict:
        """构建当前影像日期字典
        
        Args:
            service_config: 服务配置，如果为None则使用默认配置
        
        Returns:
            当前影像日期字典
        """
        current_time = datetime.now()
        
        # 使用配置或默认值
        if service_config:
            name = service_config.get('name', 'ESRI World Imagery (Current)')
            description = service_config.get('description', '最新的全球卫星影像')
            url_template = service_config.get('url_template', 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}')
        else:
            name = 'ESRI World Imagery (Current)'
            description = '最新的全球卫星影像'
            url_template = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
        
        return {
            'id': 1,
            'timestamp': int(current_time.timestamp() * 1000),
            'date': current_time.strftime('%Y-%m-%d'),
            'name': name,
            'description': description,
            'url_template': url_template
        }
    
    def _build_historical_date_dict(self, year: int, service_config: Optional[Dict] = None) -> Dict:
        """构建指定年份的历史影像日期字典
        
        Args:
            year: 历史年份
            service_config: 服务配置，如果为None则使用默认配置
        
        Returns:
            历史影像日期字典
        """
        history_time = datetime.now().replace(year=year)
        history_timestamp = int(history_time.timestamp() * 1000)
        
        # 使用配置或默认值
        if service_config:
            url_template = service_config.get('url_template', 'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}')
        else:
            url_template = 'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}'
        
        return {
            'id': year - datetime.now().year + 100,  # 使用年份差作为ID基础
            'timestamp': history_timestamp,
            'date': history_time.strftime('%Y-%m-%d'),
            'name': f"ESRI World Imagery ({year})",
            'description': f"{year}年的历史全球影像服务",
            'url_template': url_template,
            'time': history_timestamp
        }
    
    def _fetch_wayback_api_data(self) -> Optional[Dict]:
        """获取Wayback API数据
        
        Returns:
            API返回的JSON数据，如果请求失败则返回None
        """
        try:
            # 从配置中读取API信息
            api_config = self.wayback_config.get('api', {})
            base_url = api_config.get('base_url', 'https://wayback.arcgis.com/arcgis/rest/services')
            time_service = api_config.get('time_service', 'World_Imagery/MapServer')
            
            # 构建时间轴API请求URL
            time_api_url = f"{base_url}/{time_service}?f=json"
            
            if self.debug:
                print(f"[调试] 正在查询ESRI World Imagery Wayback服务时间轴: {time_api_url}")
            else:
                print(f"正在查询ESRI World Imagery Wayback服务时间轴: {time_api_url}")
            
            # 发送请求获取时间轴信息
            headers = {
                'User-Agent': self.get_random_user_agent(),
                'Accept': 'application/json',
                'Referer': 'https://www.arcgis.com/'
            }
            
            if self.debug:
                print(f"[调试] 请求头: {headers}")
            
            response = self.session.get(time_api_url, headers=headers, timeout=REQUEST_TIMEOUT)
            
            if self.debug:
                print(f"[调试] 响应状态码: {response.status_code}")
                print(f"[调试] 响应头: {dict(response.headers)}")
            
            response.raise_for_status()
            
            data = response.json()
            
            if self.debug:
                print(f"[调试] API响应数据: {data}")
            
            return data
        except requests.exceptions.RequestException as e:
            self.error_stats['api_errors'] += 1
            error_msg = f"ESRI World Imagery Wayback服务请求失败 - {e}"
            if self.debug:
                print(f"[调试] 错误: {error_msg}")
                import traceback
                traceback.print_exc()
            else:
                print(f"错误: {error_msg}")
                print("提示: 请检查网络连接和服务URL配置")
            return None
        except ValueError as e:
            self.error_stats['api_errors'] += 1
            error_msg = f"解析Wayback API响应失败 - {e}"
            if self.debug:
                print(f"[调试] 错误: {error_msg}")
                import traceback
                traceback.print_exc()
            else:
                print(f"错误: {error_msg}")
            return None
        except Exception as e:
            self.error_stats['other_errors'] += 1
            error_msg = f"获取Wayback API数据时发生未知错误 - {e}"
            if self.debug:
                print(f"[调试] 错误: {error_msg}")
                import traceback
                traceback.print_exc()
            else:
                print(f"错误: {error_msg}")
            return None
    
    def _log_time_info(self, data: Dict) -> None:
        """记录时间维度信息
        
        Args:
            data: API返回的JSON数据
        """
        if 'timeInfo' in data:
            time_info = data['timeInfo']
            print(f"服务包含时间维度信息: {time_info.get('name', 'Unknown')}")
            
            if 'timeExtent' in time_info:
                time_extent = time_info['timeExtent']
                print(f"时间范围: {time_extent}")
            
            if 'timeInterval' in time_info:
                time_interval = time_info['timeInterval']
                print(f"时间间隔: {time_interval}")
        else:
            print("警告: 服务未返回时间维度信息，使用默认时间点")
    
    def _build_fallback_dates(self, count: int = 1) -> List[Dict]:
        """构建降级日期列表
        
        Args:
            count: 需要返回的日期数量，默认为1（仅当前影像）
        
        Returns:
            降级日期列表
        """
        dates = []
        
        # 添加当前影像
        dates.append(self._build_current_date_dict())
        
        # 如果需要多个日期，添加历史影像
        if count > 1:
            for i in range(1, min(count, 6)):  # 最多添加5个历史影像
                dates.append(self._build_historical_date_dict(datetime.now().year - i))
        
        return dates
    
    def get_wayback_dates(self) -> List[Dict]:
        """获取可用的历史影像日期列表

        尝试从多个来源获取历史影像日期：
        1. ESRI World Imagery Wayback服务API
        2. 配置文件中的历史日期
        3. 硬编码的历史日期列表
        4. 基于当前年份的降级方案
        """
        if self._wayback_dates is not None:
            return self._wayback_dates

        if not self.wayback_enabled:
            print("错误: Wayback服务未启用，请在配置文件中启用")
            return []

        try:
            # 构建日期列表
            dates = []
            services_config = self.wayback_config.get('services', {})

            # 处理当前影像服务
            current_service = services_config.get('current', {})
            if current_service:
                dates.append(self._build_current_date_dict(current_service))
            else:
                print("警告: 未配置当前影像服务，使用默认配置")
                dates.append(self._build_current_date_dict())

            # 尝试从ESRI Wayback API获取历史日期
            api_data = self._fetch_wayback_api_data()
            if api_data:
                print("成功从ESRI Wayback API获取时间信息")
                self._log_time_info(api_data)
                
                # 从API数据中提取时间点
                historical_service = services_config.get('historical', {})
                if historical_service:
                    # 使用API数据构建历史日期
                    for i in range(1, 6):
                        dates.append(self._build_historical_date_dict(datetime.now().year - i, historical_service))
                else:
                    print("警告: 未配置历史影像服务，使用默认配置")
                    for i in range(1, 6):
                        dates.append(self._build_historical_date_dict(datetime.now().year - i))
            else:
                # API失败，使用备用方案
                print("ESRI Wayback API请求失败，使用备用历史日期方案")
                
                # 从配置文件读取历史日期
                config_history_dates = self.wayback_config.get('historical_dates', [])
                if config_history_dates:
                    print(f"从配置文件获取 {len(config_history_dates)} 个历史日期")
                    for date_config in config_history_dates:
                        history_date = datetime.strptime(date_config['date'], '%Y-%m-%d')
                        history_timestamp = int(history_date.timestamp() * 1000)
                        
                        # 为每个历史日期添加ESRI和Google Earth两种选项
                        # ESRI历史影像
                        historical_service = services_config.get('historical', {})
                        if historical_service:
                            esri_url_template = historical_service.get('url_template', 'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}')
                        else:
                            esri_url_template = 'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}'
                        
                        dates.append({
                            'id': date_config.get('id', len(dates) + 100),
                            'timestamp': history_timestamp,
                            'date': date_config['date'],
                            'name': f"{date_config.get('name', '历史影像')} (ESRI)",
                            'description': f"{date_config.get('description', f'{date_config['date']} 的历史影像')} (ESRI)",
                            'url_template': esri_url_template,
                            'time': history_timestamp,
                            'source': 'esri'
                        })
                        
                        # Google Earth历史影像
                        google_service = services_config.get('google_earth', {})
                        if google_service:
                            google_url_template = google_service.get('url_template', 'https://mt1.google.com/vt/lyrs=s@1899000000&x={x}&y={y}&z={z}')
                        else:
                            google_url_template = 'https://mt1.google.com/vt/lyrs=s@1899000000&x={x}&y={y}&z={z}'
                        
                        dates.append({
                            'id': date_config.get('id', len(dates) + 100) + 1000,
                            'timestamp': history_timestamp,
                            'date': date_config['date'],
                            'name': f"{date_config.get('name', '历史影像')} (Google Earth)",
                            'description': f"{date_config.get('description', f'{date_config['date']} 的历史影像')} (Google Earth)",
                            'url_template': google_url_template,
                            'source': 'google'
                        })
                else:
                    # 使用硬编码的历史日期
                    print("使用硬编码的历史日期")
                    hardcoded_dates = [
                        {'date': '2023-01-01', 'name': '2023年影像', 'description': '2023年1月的历史影像'},
                        {'date': '2022-01-01', 'name': '2022年影像', 'description': '2022年1月的历史影像'},
                        {'date': '2021-01-01', 'name': '2021年影像', 'description': '2021年1月的历史影像'},
                        {'date': '2020-01-01', 'name': '2020年影像', 'description': '2020年1月的历史影像'},
                        {'date': '2019-01-01', 'name': '2019年影像', 'description': '2019年1月的历史影像'}
                    ]
                    
                    for i, date_info in enumerate(hardcoded_dates):
                        history_date = datetime.strptime(date_info['date'], '%Y-%m-%d')
                        history_timestamp = int(history_date.timestamp() * 1000)
                        
                        # ESRI历史影像
                        historical_service = services_config.get('historical', {})
                        if historical_service:
                            esri_url_template = historical_service.get('url_template', 'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}')
                        else:
                            esri_url_template = 'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}'
                        
                        dates.append({
                            'id': i + 100,
                            'timestamp': history_timestamp,
                            'date': date_info['date'],
                            'name': f"{date_info['name']} (ESRI)",
                            'description': f"{date_info['description']} (ESRI)",
                            'url_template': esri_url_template,
                            'time': history_timestamp,
                            'source': 'esri'
                        })
                        
                        # Google Earth历史影像
                        google_service = services_config.get('google_earth', {})
                        if google_service:
                            google_url_template = google_service.get('url_template', 'https://mt1.google.com/vt/lyrs=s@1899000000&x={x}&y={y}&z={z}')
                        else:
                            google_url_template = 'https://mt1.google.com/vt/lyrs=s@1899000000&x={x}&y={y}&z={z}'
                        
                        dates.append({
                            'id': i + 1100,
                            'timestamp': history_timestamp,
                            'date': date_info['date'],
                            'name': f"{date_info['name']} (Google Earth)",
                            'description': f"{date_info['description']} (Google Earth)",
                            'url_template': google_url_template,
                            'source': 'google'
                        })

            # 按时间戳排序（最新的在前）
            dates.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

            self._wayback_dates = dates
            print(f"成功获取 {len(dates)} 个影像服务版本")
            for date_info in dates:
                print(f"  - {date_info['name']}: {date_info['date']} - {date_info['description']}")

            return dates

        except requests.exceptions.RequestException as e:
            print(f"错误: ESRI World Imagery Wayback服务请求失败 - {e}")
            print("提示: 请检查网络连接和服务URL配置")
            return self._build_fallback_dates(count=6)
        except Exception as e:
            print(f"错误: 获取Wayback日期列表时发生未知错误 - {e}")
            return self._build_fallback_dates(count=6)
    
    def get_current_and_previous_dates(self) -> Tuple[Optional[Dict], Optional[Dict]]:
        """获取当前影像和前一个时刻的影像日期信息"""
        dates = self.get_wayback_dates()

        if not dates:
            return None, None

        # 最新的日期作为当前影像（列表第一个，因为已经按时间倒序排列）
        current_date = dates[0] if dates else None

        # 第二个日期作为前一个时刻影像
        previous_date = dates[1] if len(dates) >= 2 else None

        return current_date, previous_date
    
    def print_error_stats(self):
        """打印错误统计信息"""
        print("\n=== 错误统计 ===")
        print(f"网络错误: {self.error_stats['network_errors']}")
        print(f"瓦片错误: {self.error_stats['tile_errors']}")
        print(f"API错误: {self.error_stats['api_errors']}")
        print(f"其他错误: {self.error_stats['other_errors']}")
        total_errors = sum(self.error_stats.values())
        print(f"总计错误: {total_errors}")
        print("================")
    
    def download_tile_worker_with_url(self, url: str, save_path: str, headers: Dict) -> bool:
        """使用指定URL下载单个瓦片
        
        支持断点续传和瓦片缓存
        """
        # 检查瓦片是否已存在且有效
        if os.path.exists(save_path):
            file_size = os.path.getsize(save_path)
            if file_size > 100:
                if self.debug:
                    print(f"[调试] 瓦片已存在且有效，跳过下载: {save_path}")
                return True
            else:
                # 文件存在但大小异常，删除后重新下载
                if self.debug:
                    print(f"[调试] 瓦片文件大小异常，删除后重新下载: {save_path}")
                try:
                    os.remove(save_path)
                except:
                    pass
        
        # 增加初始延迟，避免同时发起太多连接
        time.sleep(0.1)
        
        for attempt in range(RETRY_COUNT + 1):
            try:
                # 记录下载尝试
                if attempt > 0:
                    if self.debug:
                        print(f"[调试] 重试下载瓦片 ({attempt+1}/{RETRY_COUNT+1}): {url}")
                    else:
                        print(f"  重试下载瓦片 ({attempt+1}/{RETRY_COUNT+1}): {url}")
                elif self.debug:
                    print(f"[调试] 开始下载瓦片: {url}")
                
                # 检查是否支持断点续传
                headers_copy = headers.copy()
                if os.path.exists(save_path):
                    # 文件部分下载，尝试断点续传
                    file_size = os.path.getsize(save_path)
                    headers_copy['Range'] = f"bytes={file_size}-"
                    if self.debug:
                        print(f"[调试] 尝试断点续传，已下载 {file_size} 字节")
                
                # 增加超时时间，使用更保守的网络设置
                response = self.session.get(
                    url,
                    headers=headers_copy,
                    timeout=60,  # 增加超时时间到60秒
                    stream=True,
                    verify=True,
                    allow_redirects=True
                )
                
                # 检查响应状态
                if response.status_code == 206:
                    # 断点续传成功
                    if self.debug:
                        print(f"[调试] 断点续传成功，响应状态码: {response.status_code}")
                    mode = 'ab'  # 追加模式
                else:
                    # 正常下载
                    response.raise_for_status()
                    mode = 'wb'  # 写入模式
                
                # 检查响应内容类型
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    error_msg = f"瓦片下载失败: 响应不是图像类型 ({content_type})"
                    if self.debug:
                        print(f"[调试] {error_msg}")
                        print(f"[调试] 响应内容: {response.text[:200]}...")
                    else:
                        print(f"  {error_msg}")
                    if attempt < RETRY_COUNT:
                        time.sleep(1.0 * (2 ** attempt))  # 增加重试延迟
                        continue
                    self.error_stats['tile_errors'] += 1
                    return False
                
                # 确保保存目录存在
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                
                # 写入文件
                with open(save_path, mode) as f:
                    for chunk in response.iter_content(chunk_size=4096):  # 减小块大小以减少内存使用
                        if chunk:
                            f.write(chunk)
                            # 增加小延迟以避免网络拥塞
                            time.sleep(0.001)
                
                # 验证文件大小
                file_size = os.path.getsize(save_path)
                if file_size < 100:  # 小于100字节的文件可能是错误响应
                    error_msg = f"瓦片下载失败: 文件大小异常 ({file_size} 字节)"
                    if self.debug:
                        print(f"[调试] {error_msg}")
                    else:
                        print(f"  {error_msg}")
                    os.remove(save_path)
                    if attempt < RETRY_COUNT:
                        time.sleep(1.0 * (2 ** attempt))  # 增加重试延迟
                        continue
                    self.error_stats['tile_errors'] += 1
                    return False
                
                with self.lock:
                    self.downloaded_count += 1
                
                if self.debug:
                    print(f"[调试] 瓦片下载成功: {url} (大小: {file_size} 字节)")
                return True
                
            except requests.exceptions.RequestException as e:
                self.error_stats['network_errors'] += 1
                error_msg = f"网络请求失败 ({attempt+1}/{RETRY_COUNT+1}): {e}"
                if self.debug:
                    print(f"[调试] {error_msg}")
                    import traceback
                    traceback.print_exc()
                else:
                    print(f"  {error_msg}")
                if attempt < RETRY_COUNT:
                    time.sleep(1.0 * (2 ** attempt))  # 增加重试延迟
                    continue
                return False
            except Exception as e:
                self.error_stats['other_errors'] += 1
                error_msg = f"下载瓦片失败 ({attempt+1}/{RETRY_COUNT+1}): {e}"
                if self.debug:
                    print(f"[调试] {error_msg}")
                    import traceback
                    traceback.print_exc()
                else:
                    print(f"  {error_msg}")
                if attempt < RETRY_COUNT:
                    time.sleep(1.0 * (2 ** attempt))  # 增加重试延迟
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
            image_date_info: 影像日期信息，包含id和url_template
            data_source_name: 数据源名称，如不指定则使用第一个服务
        """
        self.downloaded_count = 0
        total_tiles = len(tile_coords)
        failed_tiles = 0
        skipped_tiles = 0

        print(f"开始处理 {total_tiles} 个瓦片的历史影像下载")
        print(f"缩放级别: {zoom}")
        print(f"临时目录: {temp_dir}")

        # 准备下载配置
        download_configs = []
        
        if image_date_info and image_date_info.get('url_template'):
            # 使用指定历史影像的URL模板
            version_id = image_date_info.get('id', 'unknown')
            date_str = image_date_info.get('date', 'unknown')
            name = image_date_info.get('name', 'Historical Imagery')
            time_param = image_date_info.get('time', '')
            print(f"下载历史影像（版本ID: {version_id}, 日期: {date_str}, 名称: {name}")
            
            # 主要URL模板
            primary_url_template = image_date_info['url_template']
            print(f"使用主要URL模板: {primary_url_template}")
            print(f"时间参数: {time_param}")
            
            # 备用URL模板列表
            backup_url_templates = [
                'https://wayback.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?time={time}',
                'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/{z}/{y}/{x}?time={time}',
                'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
            ]
            
            # 从wayback配置中获取headers
            headers = self.wayback_config.get('headers', {}).copy()
            # 确保包含必要的headers
            if 'User-Agent' not in headers:
                headers['User-Agent'] = self.get_random_user_agent()
            if 'Accept' not in headers:
                headers['Accept'] = 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            if 'Referer' not in headers:
                headers['Referer'] = 'https://www.arcgis.com/'
        else:
            # 使用标准服务（当前最新影像）
            if data_source_name:
                service = self.get_service_by_name(data_source_name)
                if not service:
                    print(f"警告: 未找到数据源 '{data_source_name}'，使用默认数据源")
                    service = self.services[0]
            else:
                service = self.services[0]
            
            primary_url_template = service['url_template']
            print(f"下载当前最新影像 (数据源: {service['name']})")
            print(f"使用主要URL模板: {primary_url_template}")
            
            # 备用URL模板列表
            backup_url_templates = [
                'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'
            ]
            
            # 从标准服务中获取headers
            headers = service.get('headers', {}).copy()
            if 'User-Agent' not in headers:
                headers['User-Agent'] = self.get_random_user_agent()

        # 添加通用headers
        headers['Accept-Encoding'] = 'gzip, deflate, br'
        headers['Connection'] = 'keep-alive'
        headers['Cache-Control'] = 'no-cache'
        headers['Pragma'] = 'no-cache'

        print(f"使用Headers: User-Agent={headers.get('User-Agent', 'N/A')}")

        tasks = []
        for x, y in tile_coords:
            tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
            
            # 检查瓦片是否已存在
            if os.path.exists(tile_path) and os.path.getsize(tile_path) > 100:
                print(f"  瓦片 {x},{y} 已存在，跳过下载")
                skipped_tiles += 1
                with self.lock:
                    self.downloaded_count += 1
                continue
            
            # 构建URL列表（主要URL + 多个备用URL）
            urls = []
            
            try:
                # 构建主要URL
                if image_date_info:
                    # 检查是否是Google Earth历史影像
                    if image_date_info.get('source') == 'google' or 'google.com' in primary_url_template:
                        # Google Earth历史影像URL，不需要time参数
                        primary_url = primary_url_template.format(z=zoom, x=x, y=y)
                    elif image_date_info.get('time'):
                        # ESRI World Imagery Wayback服务URL格式
                        primary_url = primary_url_template.format(z=zoom, x=x, y=y, time=image_date_info.get('time', ''))
                    else:
                        # 其他历史影像服务
                        primary_url = primary_url_template.format(z=zoom, x=x, y=y)
                else:
                    # 处理不同数据源的URL模板
                    if '{s}' in primary_url_template:
                        # OpenStreetMap需要随机子域名
                        subdomain = random.choice(self.osm_subdomains)
                        primary_url = primary_url_template.format(z=zoom, x=x, y=y, s=subdomain)
                    elif '{q}' in primary_url_template:
                        # Bing Maps需要quadkey
                        quadkey = self.tile_to_quadkey(x, y, zoom)
                        primary_url = primary_url_template.format(q=quadkey, z=zoom, x=x, y=y)
                    else:
                        # 标准格式
                        primary_url = primary_url_template.format(z=zoom, x=x, y=y)
                urls.append(primary_url)
                
                # 构建备用URL
                for backup_template in backup_url_templates:
                    try:
                        if image_date_info:
                            # 检查是否是Google Earth历史影像
                            if image_date_info.get('source') == 'google' or 'google.com' in primary_url_template:
                                # Google Earth历史影像URL，不需要time参数
                                backup_url = backup_template.format(z=zoom, x=x, y=y)
                            elif image_date_info.get('time'):
                                backup_url = backup_template.format(z=zoom, x=x, y=y, time=image_date_info.get('time', ''))
                            else:
                                backup_url = backup_template.format(z=zoom, x=x, y=y)
                        else:
                            if '{s}' in backup_template:
                                subdomain = random.choice(self.osm_subdomains)
                                backup_url = backup_template.format(z=zoom, x=x, y=y, s=subdomain)
                            elif '{q}' in backup_template:
                                quadkey = self.tile_to_quadkey(x, y, zoom)
                                backup_url = backup_template.format(q=quadkey, z=zoom, x=x, y=y)
                            else:
                                backup_url = backup_template.format(z=zoom, x=x, y=y)
                        urls.append(backup_url)
                    except Exception as e:
                        print(f"  构建备用URL时出错: {e}")
                        continue
                
                print(f"  瓦片 {x},{y}: 准备 {len(urls)} 个URL")
                tasks.append((x, y, tile_path, urls, headers))
                
            except KeyError as e:
                print(f"  URL模板格式化错误: {e}")
                print(f"  模板: {primary_url_template}")
                # 添加基本备用URL
                basic_backup_urls = [
                    f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}",
                    f"https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={zoom}"
                ]
                print(f"  使用基本备用URL: {basic_backup_urls[0]}")
                tasks.append((x, y, tile_path, basic_backup_urls, headers))
            except Exception as e:
                print(f"  生成瓦片URL时出错: {e}")
                # 使用默认备用URL
                default_backup_urls = [
                    f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}"
                ]
                print(f"  使用默认备用URL: {default_backup_urls[0]}")
                tasks.append((x, y, tile_path, default_backup_urls, headers))

        actual_tiles_to_download = len(tasks)
        print(f"跳过 {skipped_tiles} 个已存在的瓦片，实际需要下载 {actual_tiles_to_download} 个瓦片")

        if actual_tiles_to_download == 0:
            print("所有瓦片都已存在，无需下载")
            return self.downloaded_count

        print(f"开始下载 {actual_tiles_to_download} 个瓦片...")
        print(f"使用线程池大小: {self.thread_pool_size}")

        # 定义下载函数，支持多URL重试
        def download_with_fallback(x, y, tile_path, urls, headers):
            """使用多个URL尝试下载瓦片"""
            for url_index, url in enumerate(urls):
                print(f"  瓦片 {x},{y}: 尝试下载 ({url_index + 1}/{len(urls)}): {url}")
                try:
                    # 尝试使用当前URL下载
                    success = self.download_tile_worker_with_url(url, tile_path, headers)
                    if success:
                        print(f"  瓦片 {x},{y}: 下载成功")
                        return True
                    else:
                        print(f"  瓦片 {x},{y}: URL {url_index + 1} 下载失败，尝试下一个URL")
                except Exception as e:
                    print(f"  瓦片 {x},{y}: URL {url_index + 1} 下载异常: {e}")
                    # 继续尝试下一个URL
                    continue
            # 所有URL都失败
            print(f"  瓦片 {x},{y}: 所有URL都下载失败")
            return False

        # 使用动态线程池大小
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_pool_size) as executor:
            future_to_tile = {
                executor.submit(download_with_fallback, x, y, path, urls, hdr): (x, y)
                for x, y, path, urls, hdr in tasks
            }
            
            # 跟踪下载进度
            completed = 0
            for future in concurrent.futures.as_completed(future_to_tile):
                tile_coord = future_to_tile[future]
                completed += 1
                try:
                    result = future.result()
                    if not result:
                        failed_tiles += 1
                        print(f"  瓦片 {tile_coord} 最终下载失败")
                    # 成功的瓦片已经在download_tile_worker_with_url中计数
                except Exception as e:
                    failed_tiles += 1
                    print(f"  瓦片 {tile_coord} 下载异常: {e}")
                
                # 显示进度
                if completed % 10 == 0 or completed == actual_tiles_to_download:
                    progress = (completed / actual_tiles_to_download) * 100
                    print(f"  进度: {completed}/{actual_tiles_to_download} ({progress:.1f}%)")

        success_rate = (self.downloaded_count / total_tiles) * 100 if total_tiles > 0 else 0
        actual_success_rate = (self.downloaded_count - skipped_tiles) / actual_tiles_to_download * 100 if actual_tiles_to_download > 0 else 0
        
        print("\n=== 下载完成 ===")
        print(f"总瓦片数: {total_tiles}")
        print(f"跳过的瓦片: {skipped_tiles}")
        print(f"实际下载: {actual_tiles_to_download}")
        print(f"成功下载: {self.downloaded_count - skipped_tiles}")
        print(f"失败下载: {failed_tiles}")
        print(f"总体成功率: {success_rate:.1f}%")
        print(f"实际下载成功率: {actual_success_rate:.1f}%")
        print("================")
        
        # 打印错误统计
        self.print_error_stats()
        
        return self.downloaded_count
    
    def parse_kml_file(self, kml_file_path: str) -> List[Dict]:
        """解析KML文件，提取矩形边界坐标"""
        buffers = []
        
        try:
            tree = ET.parse(kml_file_path)
            root = tree.getroot()
            
            # 提取命名空间
            namespace = ''
            if '}' in root.tag:
                namespace = root.tag.split('}')[0].strip('{')
            
            # 构建命名空间映射
            ns = {}
            if namespace:
                ns['kml'] = namespace
            
            # 查找所有Placemark元素
            placemarks = []
            if namespace:
                placemarks = root.findall('.//kml:Placemark', namespaces=ns)
            else:
                placemarks = root.findall('.//Placemark')
            
            for placemark in placemarks:
                buffer_info = {}
                
                # 提取ID
                buffer_id = placemark.get('id', '')
                buffer_info['id'] = buffer_id
                
                # 提取扩展数据
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
                
                # 提取坐标
                coordinates_elem = None
                if namespace:
                    coordinates_elem = placemark.find('.//kml:coordinates', namespaces=ns)
                else:
                    coordinates_elem = placemark.find('.//coordinates')
                if coordinates_elem is not None and coordinates_elem.text:
                    coords_text = coordinates_elem.text.strip()
                    coords_list = re.findall(r'[-+]?[0-9]*\.?[0-9]+,[-+]?[0-9]*\.?[0-9]+', coords_text)
                    
                    if len(coords_list) >= 4:  # 至少4个点，形成矩形
                        lons = []
                        lats = []
                        for coord in coords_list:
                            lon, lat = map(float, coord.split(','))
                            lons.append(lon)
                            lats.append(lat)
                        
                        # 计算边界坐标
                        buffer_info['min_lon'] = min(lons)
                        buffer_info['max_lon'] = max(lons)
                        buffer_info['min_lat'] = min(lats)
                        buffer_info['max_lat'] = max(lats)
                        buffer_info['center_lon'] = (buffer_info['min_lon'] + buffer_info['max_lon']) / 2
                        buffer_info['center_lat'] = (buffer_info['min_lat'] + buffer_info['max_lat']) / 2
                        
                        buffers.append(buffer_info)
            
            print(f"成功解析 {len(buffers)} 个矩形边界")
            return buffers
            
        except Exception as e:
            print(f"解析KML文件时出错: {e}")
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
        
        # 从配置中获取默认缩放级别和范围
        default_zoom = PROCESSING.get('default_zoom', 15)
        max_zoom = PROCESSING.get('max_zoom', 19)
        min_zoom = PROCESSING.get('min_zoom', 1)
        
        # 确保默认缩放级别在有效范围内
        default_zoom = max(min_zoom, min(default_zoom, max_zoom))
        
        # 先尝试默认缩放级别
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
        
        # 如果默认级别不合适，向上尝试更高的级别
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
        
        # 如果更高的级别也不合适，向下尝试更低的级别
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
        
        # 如果都不合适，返回默认值
        return default_zoom
    
    def download_tile_worker(self, service: Dict, x: int, y: int, zoom: int, save_path: str) -> bool:
        """下载单个瓦片"""
        url_template = service['url_template']
        
        # 根据服务类型处理不同的URL模板
        if '{quadkey}' in url_template:
            # Bing Maps格式，需要quadkey
            quadkey = self.tile_to_quadkey(x, y, zoom)
            url = url_template.format(quadkey=quadkey)
        elif '{q}' in url_template:
            # Bing Maps格式，需要quadkey
            quadkey = self.tile_to_quadkey(x, y, zoom)
            url = url_template.format(q=quadkey, z=zoom, x=x, y=y)
        elif '{s}' in url_template:
            # OpenStreetMap格式，需要随机子域名
            subdomain = random.choice(self.osm_subdomains)
            url = url_template.format(s=subdomain, z=zoom, x=x, y=y)
        else:
            # 标准格式
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
                print(f"下载瓦片 {x}_{y}_{zoom} 失败（尝试{attempt+1}次）: {e}")
                return False
    
    def download_tiles_batch(self, service: Dict, tile_coords: List[Tuple[int, int]], zoom: int, temp_dir: str) -> int:
        """批量下载瓦片"""
        self.downloaded_count = 0
        total_tiles = len(tile_coords)
        failed_tiles = 0
        
        print(f"开始批量下载瓦片: 共{total_tiles}个瓦片，使用服务: {service.get('name', 'Unknown')}")
        
        tasks = []
        for x, y in tile_coords:
            tile_path = os.path.join(temp_dir, f"tile_{x}_{y}_{zoom}.png")
            tasks.append((x, y, tile_path))
        
        # 使用动态线程池大小
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
                        print(f"  瓦片 {tile_coord} 下载失败")
                except Exception as e:
                    failed_tiles += 1
                    print(f"  瓦片 {tile_coord} 下载异常: {e}")
        
        success_rate = (self.downloaded_count / total_tiles) * 100 if total_tiles > 0 else 0
        print(f"瓦片下载完成: 成功 {self.downloaded_count}/{total_tiles} ({success_rate:.1f}%)，失败 {failed_tiles} 个")
        return self.downloaded_count
    
    def stitch_tiles(self, temp_dir: str, tile_count: int, save_path: str, kml_bounds: Optional[Dict] = None) -> bool:
        """拼接瓦片生成完整图像"""
        try:
            # 查找所有瓦片文件
            tile_files = []
            for filename in os.listdir(temp_dir):
                if filename.startswith('tile_') and filename.endswith('.png'):
                    tile_files.append(os.path.join(temp_dir, filename))
            
            if not tile_files:
                print("未找到瓦片文件")
                return False
            
            # 解析瓦片信息
            tiles_info = []
            for tile_file in tile_files:
                filename = os.path.basename(tile_file)
                parts = filename.replace('tile_', '').replace('.png', '').split('_')
                if len(parts) == 3:
                    x, y, z = int(parts[0]), int(parts[1]), int(parts[2])
                    tiles_info.append({'x': x, 'y': y, 'z': z, 'file': tile_file})
            
            if not tiles_info:
                print("无法解析瓦片坐标信息")
                return False
            
            # 排序瓦片
            tiles_info.sort(key=lambda t: (t['y'], t['x']))
            
            # 获取瓦片尺寸
            first_tile = Image.open(tiles_info[0]['file'])
            tile_width, tile_height = first_tile.size
            first_tile.close()
            
            # 计算拼接后图像尺寸
            result_width = tile_width * tile_count
            result_height = tile_height * tile_count
            result_image = Image.new('RGB', (result_width, result_height))
            
            # 计算瓦片坐标范围
            x_coords = [t['x'] for t in tiles_info]
            y_coords = [t['y'] for t in tiles_info]
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            
            # 粘贴瓦片
            for tile_info in tiles_info:
                x, y = tile_info['x'], tile_info['y']
                pos_x = (x - min_x) * tile_width
                pos_y = (y - min_y) * tile_height
                
                tile_image = Image.open(tile_info['file'])
                result_image.paste(tile_image, (pos_x, pos_y))
                tile_image.close()
            
            # 根据KML边界裁剪图像
            if kml_bounds:
                zoom = tiles_info[0]['z']
                result_image = self.crop_to_kml_bounds(result_image, kml_bounds, min_x, min_y, zoom, tile_width, tile_height)
            
            # 保存图像
            result_image.save(save_path, 'PNG')
            result_image.close()
            
            print(f"成功拼接 {len(tiles_info)} 个瓦片，生成 {result_width}x{result_height} 像素影像")
            return True
            
        except Exception as e:
            print(f"拼接瓦片时出错: {e}")
            return False
    
    def crop_to_kml_bounds(self, image: Image.Image, kml_bounds: Dict, min_tile_x: int, min_tile_y: int, zoom: int, tile_width: int, tile_height: int) -> Image.Image:
        """根据KML边界裁剪图像"""
        try:
            min_lon, max_lon = kml_bounds['min_lon'], kml_bounds['max_lon']
            min_lat, max_lat = kml_bounds['min_lat'], kml_bounds['max_lat']
            
            print(f"KML边界: 经度({min_lon:.6f} - {max_lon:.6f}), 纬度({min_lat:.6f} - {max_lat:.6f})")
            
            # Web墨卡托投影转换
            total_pixels = 256 * (2 ** zoom)
            
            def lon_to_pixel_x(lon, zoom):
                return int((lon + 180.0) / 360.0 * total_pixels)
            
            def lat_to_pixel_y(lat, zoom):
                lat_rad = math.radians(lat)
                return int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * total_pixels)
            
            # 计算全局像素坐标
            left_pixel = lon_to_pixel_x(min_lon, zoom)
            right_pixel = lon_to_pixel_x(max_lon, zoom)
            top_pixel = lat_to_pixel_y(max_lat, zoom)
            bottom_pixel = lat_to_pixel_y(min_lat, zoom)
            
            # 计算相对像素位置
            min_tile_left_pixel = min_tile_x * tile_width
            min_tile_top_pixel = min_tile_y * tile_height
            
            left = left_pixel - min_tile_left_pixel
            top = top_pixel - min_tile_top_pixel
            right = right_pixel - min_tile_left_pixel
            bottom = bottom_pixel - min_tile_top_pixel
            
            # 边界检查
            width, height = image.size
            left = max(0, min(left, width - 1))
            top = max(0, min(top, height - 1))
            right = max(left + 1, min(right, width))
            bottom = max(top + 1, min(bottom, height))
            
            if right <= left or bottom <= top:
                print("裁剪区域无效，返回原图")
                return image
            
            # 裁剪图像
            cropped_image = image.crop((left, top, right, bottom))
            
            print(f"精确裁剪图像: 位置({left}, {top}, {right}, {bottom}), 尺寸({right-left}x{bottom-top})")
            return cropped_image
            
        except Exception as e:
            print(f"裁剪图像时出错: {e}")
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
            # 选择服务
            if service_name:
                service = self.get_service_by_name(service_name)
                if not service:
                    print(f"警告: 未找到服务 '{service_name}'，使用默认服务")
                    service = self.services[0]
            else:
                # 使用默认服务
                service = self.services[0]

            # 检查缩放级别
            max_zoom = service['max_zoom']
            if zoom > max_zoom:
                print(f"缩放级别 {zoom} 超过服务最大限制 {max_zoom}")
                zoom = max_zoom

            # 计算瓦片范围
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
                        print(f"瓦片数量过大({tile_count_x}x{tile_count_y})，降低缩放级别到{zoom}")

                if original_zoom != zoom:
                    print(f"缩放级别从{original_zoom}调整到{zoom}")

                print(f"根据KML边界计算瓦片范围: X({x_min}-{x_max}), Y({y_min}-{y_max}), 共{tile_count_x}x{tile_count_y}瓦片")
            else:
                center_x, center_y = self.latlon_to_tile(center_lat, center_lon, zoom)
                x_min = center_x - tile_count // 2
                x_max = center_x + tile_count // 2
                y_min = center_y - tile_count // 2
                y_max = center_y + tile_count // 2
                tile_count_x = tile_count
                tile_count_y = tile_count

            # 根据影像类型选择下载方式
            is_historical = (image_type == 'previous')
            if is_historical and image_date_info:
                date_str = image_date_info.get('date', 'unknown')
                name = image_date_info.get('name', 'Historical Imagery')
                print(f"下载历史影像（日期: {date_str}, 名称: {name}）: 中心({center_lat:.6f}, {center_lon:.6f}), "
                      f"缩放级别{zoom}, {tile_count_x}x{tile_count_y}瓦片")
            else:
                print(f"下载 {service['name']} 当前影像: 中心({center_lat:.6f}, {center_lon:.6f}), "
                      f"缩放级别{zoom}, {tile_count_x}x{tile_count_y}瓦片")

            # 创建临时目录
            temp_dir = PATHS.get('temp_tiles_dir', 'temp_tiles')
            os.makedirs(temp_dir, exist_ok=True)
            print(f"使用临时目录: {temp_dir}")

            # 生成瓦片坐标
            tile_coords = [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]
            print(f"生成 {len(tile_coords)} 个瓦片坐标")

            # 批量下载瓦片
            if is_historical and self.wayback_enabled and image_date_info:
                print("开始下载历史影像瓦片...")
                tiles_downloaded = self.download_historical_tiles_batch(tile_coords, zoom, temp_dir, image_date_info, service_name)
            else:
                print("开始下载当前影像瓦片...")
                tiles_downloaded = self.download_tiles_batch(service, tile_coords, zoom, temp_dir)

            print(f"瓦片下载完成: {tiles_downloaded}/{len(tile_coords)} 成功")

            # 检查下载是否成功
            if tiles_downloaded == 0:
                print(f"错误: 所有瓦片下载失败，无法生成影像")
                print("提示: 请检查网络连接、服务URL配置和影像日期信息")
                # 清理临时目录
                shutil.rmtree(temp_dir)
                print("临时目录已清理")
                return False

            # 拼接瓦片
            if tiles_downloaded > 0 and save_path:
                try:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    print(f"开始拼接瓦片，保存到: {save_path}")

                    if self.stitch_tiles(temp_dir, max(tile_count_x, tile_count_y), save_path, kml_bounds):
                        print(f"影像已成功保存到: {save_path}")

                        # 清理临时目录
                        shutil.rmtree(temp_dir)
                        print("临时目录已清理")
                        return True
                    else:
                        print("错误: 瓦片拼接失败")
                        print("提示: 请检查临时目录权限和磁盘空间")
                except Exception as e:
                    print(f"错误: 拼接瓦片时发生异常 - {e}")
                    import traceback
                    traceback.print_exc()

            # 清理临时目录
            try:
                shutil.rmtree(temp_dir)
                print("临时目录已清理")
            except Exception as e:
                print(f"错误: 清理临时目录时发生异常 - {e}")
            return False
        except Exception as e:
            print(f"错误: 下载卫星影像时发生异常 - {e}")
            # 清理临时目录
            try:
                temp_dir = PATHS.get('temp_tiles_dir', 'temp_tiles')
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    print("临时目录已清理")
            except:
                pass
            return False
    
    def png_to_geotiff(self, png_path: str, tiff_path: str, bounds: Dict) -> bool:
        """将PNG图像转换为带有地理参考的TIFF图像"""
        try:
            # 打开PNG图像
            with Image.open(png_path) as img:
                # 确保图像为RGB模式
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 获取图像尺寸
                width, height = img.size
                
                # 转换为numpy数组
                img_array = np.array(img)
            
            # 计算地理变换
            min_lon = bounds['min_lon']
            max_lon = bounds['max_lon']
            min_lat = bounds['min_lat']
            max_lat = bounds['max_lat']
            
            # 从边界创建变换
            transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)
            
            # 设置坐标参考系统 (WGS84)
            crs = rasterio.CRS.from_wkt(WGS84_WKT)
            
            # 创建TIFF文件
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
                # 写入三个波段
                dst.write(img_array[:, :, 0], 1)  # Red
                dst.write(img_array[:, :, 1], 2)  # Green
                dst.write(img_array[:, :, 2], 3)  # Blue
            
            print(f"成功生成带地理参考的TIFF: {tiff_path}")
            return True
            
        except Exception as e:
            print(f"转换PNG到TIFF时出错: {e}")
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
            print(f"KML文件不存在: {kml_file_path}")
            return False

        # 设置输出目录
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(kml_file_path), 'tiff_output')

        kml_filename = os.path.splitext(os.path.basename(kml_file_path))[0]
        kml_output_dir = os.path.join(output_dir, kml_filename)

        # 创建png和tif子文件夹
        png_output_dir = os.path.join(kml_output_dir, 'png')
        tiff_output_dir = os.path.join(kml_output_dir, 'tif')

        # 如果下载历史影像，创建对应的子目录
        if download_mode in ['previous', 'both']:
            png_previous_dir = os.path.join(kml_output_dir, 'png_previous')
            tiff_previous_dir = os.path.join(kml_output_dir, 'tif_previous')
            os.makedirs(png_previous_dir, exist_ok=True)
            os.makedirs(tiff_previous_dir, exist_ok=True)

        os.makedirs(png_output_dir, exist_ok=True)
        os.makedirs(tiff_output_dir, exist_ok=True)

        print(f"KML文件输出目录: {kml_output_dir}")
        print(f"PNG文件保存目录: {png_output_dir}")
        print(f"TIFF文件保存目录: {tiff_output_dir}")
        if download_mode in ['previous', 'both']:
            print(f"历史PNG文件保存目录: {png_previous_dir}")
            print(f"历史TIFF文件保存目录: {tiff_previous_dir}")

        # 解析KML文件
        buffers = self.parse_kml_file(kml_file_path)
        if not buffers:
            print("未找到有效的缓冲区数据")
            return False

        # 获取Wayback日期信息（用于当前和历史影像）
        current_date, previous_date = self.get_current_and_previous_dates()

        # 获取当前影像的日期作为文件名时间戳（从Wayback获取的最新影像日期）
        if current_date and current_date.get('date'):
            current_timestamp = current_date['date'].replace('-', '')  # YYYYMMDD格式
            print(f"当前影像时间戳: {current_timestamp} (来自Wayback API)")
        else:
            current_timestamp = datetime.now().strftime('%Y%m%d')
            print(f"当前影像时间戳: {current_timestamp} (使用当前系统时间)")

        # 获取历史影像的日期作为文件名时间戳
        if previous_date and previous_date.get('date'):
            previous_timestamp = previous_date['date'].replace('-', '')  # YYYYMMDD格式
            print(f"历史影像时间戳: {previous_timestamp} (来自Wayback API)")
        else:
            previous_timestamp = current_timestamp
            print(f"历史影像时间戳: {previous_timestamp} (使用当前影像时间戳)")

        success_count = 0
        previous_success_count = 0

        for i, buffer_info in enumerate(buffers):
            print(f"\n处理缓冲区 {i+1}/{len(buffers)}: {buffer_info.get('id', 'Unknown')}")

            # 计算缩放级别
            zoom = self.calculate_zoom_level(
                buffer_info['min_lat'], buffer_info['max_lat'],
                buffer_info['min_lon'], buffer_info['max_lon']
            )

            buffer_id = buffer_info.get('id', f'buffer_{i+1}')

            # 下载当前影像（使用Wayback的最新影像）
            if download_mode in ['current', 'both']:
                # 使用影像日期作为文件名前缀
                png_filename = f"{current_timestamp}_{buffer_id}.png"
                png_path = os.path.join(png_output_dir, png_filename)
                tiff_filename = f"{current_timestamp}_{buffer_id}.tif"
                tiff_path = os.path.join(tiff_output_dir, tiff_filename)

                print(f"\n[当前影像] 下载缓冲区 {buffer_id} 的当前影像...")
                print(f"  保存路径: {png_path}")
                print(f"  使用影像信息: {current_date.get('name', 'Unknown')} (日期: {current_date.get('date', 'unknown')})")
                
                if self.download_satellite_image(
                    buffer_info['center_lat'], buffer_info['center_lon'],
                    zoom, png_path, tile_count=3, kml_bounds=buffer_info,
                    image_type='current', image_date_info=current_date,
                    service_name=service_name
                ):
                    if self.png_to_geotiff(png_path, tiff_path, buffer_info):
                        success_count += 1
                        print(f"[当前影像] 成功生成: {tiff_path}")
                    else:
                        print(f"[当前影像] TIFF转换失败")
                else:
                    print(f"[当前影像] 影像下载失败")

                time.sleep(1)

            # 下载前一个时刻的影像
            if download_mode in ['previous', 'both']:
                # 使用历史影像日期作为文件名前缀
                png_filename = f"{previous_timestamp}_{buffer_id}.png"
                png_path = os.path.join(png_previous_dir, png_filename)
                tiff_filename = f"{previous_timestamp}_{buffer_id}.tif"
                tiff_path = os.path.join(tiff_previous_dir, tiff_filename)

                print(f"\n[历史影像] 下载缓冲区 {buffer_id} 的历史影像...")
                print(f"  保存路径: {png_path}")
                print(f"  使用影像信息: {previous_date.get('name', 'Unknown')} (日期: {previous_date.get('date', 'unknown')})")
                
                if self.download_satellite_image(
                    buffer_info['center_lat'], buffer_info['center_lon'],
                    zoom, png_path, tile_count=3, kml_bounds=buffer_info,
                    image_type='previous', image_date_info=previous_date,
                    service_name=service_name
                ):
                    if self.png_to_geotiff(png_path, tiff_path, buffer_info):
                        previous_success_count += 1
                        print(f"[历史影像] 成功生成: {tiff_path}")
                    else:
                        print(f"[历史影像] TIFF转换失败")
                else:
                    print(f"[历史影像] 影像下载失败")

                time.sleep(1)

        print(f"\n处理完成:")
        if download_mode in ['current', 'both']:
            print(f"  当前影像: {success_count}/{len(buffers)} 个缓冲区成功生成TIFF图像")
        if download_mode in ['previous', 'both']:
            print(f"  历史影像: {previous_success_count}/{len(buffers)} 个缓冲区成功生成TIFF图像")

        return success_count > 0 or previous_success_count > 0