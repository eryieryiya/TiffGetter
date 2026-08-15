# 配置模块 - ESRI Wayback 卫星影像工具配置
import os

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

DEFAULT_CONFIG = {
    'processing': {
        'thread_pool_size': 10,
        'request_timeout': 30,
        'retry_count': 3,
        'default_zoom': 18,
        'max_zoom': 20,
        'min_zoom': 1,
        'tile_size': 256,
        'buffer_sizes': [500, 1000, 2000]
    },
    'user_agents': [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0"
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


def load_config(config_path=None):
    """加载配置文件"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')

    config = DEFAULT_CONFIG.copy()

    if YAML_AVAILABLE and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f)

        if yaml_config:
            for key, value in yaml_config.items():
                if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value

    return config


CONFIG = load_config()

THREAD_POOL_SIZE = CONFIG['processing']['thread_pool_size']
REQUEST_TIMEOUT = CONFIG['processing']['request_timeout']
RETRY_COUNT = CONFIG['processing']['retry_count']
USER_AGENTS = CONFIG['user_agents']
WGS84_WKT = CONFIG['coordinate_systems']['wgs84']['wkt']

PATHS = CONFIG.get('paths', {})
PROCESSING = CONFIG.get('processing', {})