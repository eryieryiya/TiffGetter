# 配置模块 - 包含全局配置和常量
import os

# 尝试导入yaml，如失败则使用默认配置
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# 默认配置值
DEFAULT_CONFIG = {
    'processing': {
        'thread_pool_size': 50,
        'request_timeout': 30,
        'retry_count': 3
    },
    'user_agents': [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/114.0.18235.88",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
    ],
    'satellite_services': [
        {
            'name': 'ESRI World Imagery',
            'url_template': 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            'max_zoom': 18,
            'headers': {
                'Referer': 'https://www.arcgis.com/',
                'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
        },
        {
            'name': 'Google Earth',
            'url_template': 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
            'max_zoom': 20,
            'headers': {
                'Referer': 'https://www.google.com/',
                'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
        },
        {
            'name': 'Bing Maps',
            'url_template': 'https://t0.ssl.ak.dynamic.tiles.virtualearth.net/comp/ch/{z}/{y}/{x}?mkt=en-US&it=G,L&og=191&n=z',
            'max_zoom': 19,
            'headers': {
                'Referer': 'https://www.bing.com/',
                'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
        },
        {
            'name': 'OpenStreetMap',
            'url_template': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            'max_zoom': 19,
            'headers': {
                'Referer': 'https://www.openstreetmap.org/',
                'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
        }
    ],
    'coordinate_systems': {
        'wgs84': {
            'wkt': """GEOGCS["WGS 84",
    DATUM["WGS_1984",
        SPHEROID["WGS 84",6378137,298.257223563,
            AUTHORITY["EPSG","7030"]],
        AUTHORITY["EPSG","6326"]],
    PRIMEM["Greenwich",0,
        AUTHORITY["EPSG","8901"]],
    UNIT["degree",0.0174532925199433,
        AUTHORITY["EPSG","9122"]],
    AUTHORITY["EPSG","4326"]]"""
        }
    }
}

# 加载配置文件
def load_config(config_path=None):
    """加载配置文件"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    
    config = DEFAULT_CONFIG.copy()
    
    if YAML_AVAILABLE and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f)
        
        # 合并配置
        if yaml_config:
            for key, value in yaml_config.items():
                if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value
    
    return config

# 全局配置对象
CONFIG = load_config()

# 向后兼容的常量定义
THREAD_POOL_SIZE = CONFIG['processing']['thread_pool_size']
REQUEST_TIMEOUT = CONFIG['processing']['request_timeout']
RETRY_COUNT = CONFIG['processing']['retry_count']
USER_AGENTS = CONFIG['user_agents']
SATELLITE_SERVICES = CONFIG['satellite_services']
WGS84_WKT = CONFIG['coordinate_systems']['wgs84']['wkt']

# 新增配置项
PATHS = CONFIG.get('paths', {})
PROCESSING = CONFIG.get('processing', {})
WAYBACK_SERVICES = CONFIG.get('wayback_services', {})
