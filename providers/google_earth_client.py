# Google Earth 历史影像API客户端 - 通过Flatfile API获取历史卫星影像

import os
import struct
import zlib
import requests
import threading
from datetime import datetime
from typing import List, Dict, Tuple, Optional


PACKET_MAGIC = 0x7468dead
PACKET_MAGIC_SWAP = 0xadde6874
MIN_VALID_DATE = 545

KNOWN_GOOD_EPOCHS = [365, 361, 360, 358, 357, 356, 354, 352, 321, 296, 273]

GE_HEADERS = {
    'User-Agent': 'GoogleEarth/7.3.6.10441(Windows;Microsoft Windows 10;en;kml:2.2;client:Pro;type:default)',
    'Accept': 'application/vnd.google-earth.kml+xml, application/vnd.google-earth.kmz, image/*, */*',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,*',
    'Connection': 'Keep-Alive'
}

DB_ROOT_URL = 'https://khmdb.google.com/dbRoot.v5?db=tm&hl=en&gl=us&output=proto'
TM_BASE_URL = 'https://khmdb.google.com/flatfile?db=tm'
DEFAULT_BASE_URL = 'https://kh.google.com/flatfile'


def encode_ge_date(year: int, month: int, day: int) -> int:
    """将年月日编码为Google Earth打包日期格式
    
    Args:
        year: 年份
        month: 月份 (1-12)
        day: 日 (1-31)
    
    Returns:
        打包后的整数值
    """
    return ((year & 0x7FF) << 9) | ((month & 0xF) << 5) | (day & 0x1F)


def decode_ge_date(packed: int) -> Tuple[int, int, int]:
    """将Google Earth打包日期解码为年月日
    
    Args:
        packed: 打包的日期整数
    
    Returns:
        (year, month, day) 元组
    """
    year = packed >> 9
    month = (packed >> 5) & 0xF
    day = packed & 0x1F
    return year, month, day


def date_to_hex(year: int, month: int, day: int) -> str:
    """将日期转换为URL中使用的十六进制字符串
    
    Args:
        year: 年份
        month: 月份
        day: 日
    
    Returns:
        十六进制日期字符串
    """
    return format(encode_ge_date(year, month, day), 'x')


def xyz_to_quadtree_path(x: int, y: int, z: int) -> str:
    """将XYZ瓦片坐标转换为Google Earth四叉树路径
    
    Args:
        x: X坐标
        y: Y坐标 (Web Mercator, 从上到下)
        z: 缩放级别
    
    Returns:
        四叉树路径字符串
    """
    num_tiles = 1 << z
    row = num_tiles - 1 - y
    col = x
    
    path = '0'
    for i in range(z - 1, -1, -1):
        row_bit = (row >> i) & 1
        col_bit = (col >> i) & 1
        quad = (row_bit << 1) | (row_bit ^ col_bit)
        path += str(quad)
    return path


def quadtree_path_to_xyz(path: str) -> Tuple[int, int, int]:
    """将四叉树路径转换为XYZ瓦片坐标
    
    Args:
        path: 四叉树路径字符串
    
    Returns:
        (x, y, z) 元组
    """
    z = len(path) - 1
    row = 0
    col = 0
    
    for i in range(1, len(path)):
        quad = int(path[i])
        row_bit = (quad >> 1) & 1
        col_bit = (quad >> 1) ^ (quad & 1)
        row = (row << 1) | row_bit
        col = (col << 1) | col_bit
    
    num_tiles = 1 << z
    y = num_tiles - 1 - row
    x = col
    return x, y, z


def xor_decrypt(key: bytes, data: bytes) -> bytes:
    """使用XOR算法解密Google Earth数据
    
    Args:
        key: 加密密钥
        data: 加密数据
    
    Returns:
        解密后的数据
    """
    result = bytearray(data)
    off = 16
    for j in range(len(result)):
        result[j] ^= key[off]
        off += 1
        if off & 7 == 0:
            off += 16
        if off >= len(key):
            off = (off + 8) % 24
    return bytes(result)


def decompress_packet(data: bytes) -> bytes:
    """解压Google Earth数据包
    
    Args:
        data: 压缩数据
    
    Returns:
        解压后的数据
    """
    if len(data) < 8:
        return data
    
    magic = struct.unpack('<I', data[:4])[0]
    
    if magic == PACKET_MAGIC:
        decomp_size = struct.unpack('<I', data[4:8])[0]
    elif magic == PACKET_MAGIC_SWAP:
        decomp_size = struct.unpack('>I', data[4:8])[0]
    else:
        return data
    
    try:
        decompressed = zlib.decompress(data[8:])
        return decompressed
    except zlib.error:
        return data


def get_sub_index(path: str) -> int:
    """计算四叉树路径的子索引
    
    Args:
        path: 四叉树路径
    
    Returns:
        子索引值
    """
    if len(path) <= 4:
        return 0
    
    sub_path = path[-4:]
    index = 0
    for c in sub_path:
        index = index * 4 + (ord(c) - ord('0'))
    return index


def get_traversal_paths(path: str) -> List[str]:
    """获取四叉树遍历路径列表
    
    Args:
        path: 完整的四叉树路径
    
    Returns:
        遍历路径列表
    """
    paths = []
    current = path[:5] if len(path) >= 5 else path
    paths.append(current)
    
    for i in range(9, len(path) + 1, 4):
        if i <= len(path):
            paths.append(path[:i])
    
    if paths[-1] != path:
        paths.append(path)
    
    return paths


class ProtobufParser:
    """简化的Protobuf解析器，支持GROUP wire type"""

    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
    
    def has_more(self) -> bool:
        return self.offset < len(self.data)
    
    def read_varint(self) -> int:
        result = 0
        shift = 0
        while self.offset < len(self.data):
            b = self.data[self.offset]
            self.offset += 1
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return result
    
    def read_tag(self) -> Tuple[int, int]:
        tag = self.read_varint()
        field_num = tag >> 3
        wire_type = tag & 0x07
        return field_num, wire_type
    
    def read_bytes(self) -> bytes:
        length = self.read_varint()
        data = self.data[self.offset:self.offset + length]
        self.offset += length
        return data
    
    def read_uint32(self) -> int:
        return self.read_varint()
    
    def read_int32(self) -> int:
        return self.read_varint()
    
    def skip_field(self, wire_type: int):
        if wire_type == 0:
            self.read_varint()
        elif wire_type == 1:
            self.offset += 8
        elif wire_type == 2:
            length = self.read_varint()
            self.offset += length
        elif wire_type == 5:
            self.offset += 4
    
    def read_group(self, end_field_num: int) -> bytes:
        start = self.offset
        while self.has_more():
            field_num, wire_type = self.read_tag()
            if wire_type == 4 and field_num == end_field_num:
                break
            self.skip_field(wire_type)
        return self.data[start:self.offset]


class QuadtreeNode:
    """四叉树节点"""

    def __init__(self):
        self.flags = 0
        self.cache_node_epoch = 0
        self.layers = []
        self.channels = []


class QuadtreeLayer:
    """四叉树图层"""

    LAYER_TYPE_IMAGERY = 0
    LAYER_TYPE_TERRAIN = 1
    LAYER_TYPE_VECTOR = 2
    LAYER_TYPE_IMAGERY_HISTORY = 3

    def __init__(self):
        self.type = 0
        self.layer_epoch = 0
        self.provider = 0
        self.dated_tiles = []
        self.shared_tile_date = 0
        self.coarse_tile_dates = []


class DatedTile:
    """历史影像日期瓦片"""

    def __init__(self):
        self.date = 0
        self.dated_tile_epoch = 0
        self.provider = 0
        self.year = 0
        self.month = 0
        self.day = 0
        self.hex_date = ''


def parse_quadtree_packet(data: bytes) -> Tuple[int, List[QuadtreeNode]]:
    """解析四叉树数据包
    
    Args:
        data: 解密解压后的protobuf数据
    
    Returns:
        (packet_epoch, nodes) 元组
    """
    parser = ProtobufParser(data)
    packet_epoch = 0
    nodes = []
    
    while parser.has_more():
        field_num, wire_type = parser.read_tag()
        
        if field_num == 1 and wire_type == 0:
            packet_epoch = parser.read_varint()
        elif field_num == 2 and wire_type == 2:
            node_data = parser.read_bytes()
            node = _parse_sparse_node(node_data)
            if node:
                nodes.append(node)
        else:
            parser.skip_field(wire_type)
    
    return packet_epoch, nodes


def _parse_sparse_node(data: bytes) -> Optional[QuadtreeNode]:
    """解析稀疏四叉树节点
    
    Args:
        data: 节点数据
    
    Returns:
        QuadtreeNode 或 None
    """
    parser = ProtobufParser(data)
    node = QuadtreeNode()
    index = 0
    node_data = None
    
    while parser.has_more():
        field_num, wire_type = parser.read_tag()
        
        if field_num == 3 and wire_type == 0:
            index = parser.read_varint()
        elif field_num == 4 and wire_type == 2:
            node_data = parser.read_bytes()
        else:
            parser.skip_field(wire_type)
    
    if node_data:
        node = _parse_node(node_data)
        return node
    
    return None


def _parse_node(data: bytes) -> QuadtreeNode:
    """解析四叉树节点
    
    Args:
        data: 节点数据
    
    Returns:
        QuadtreeNode
    """
    parser = ProtobufParser(data)
    node = QuadtreeNode()
    
    while parser.has_more():
        field_num, wire_type = parser.read_tag()
        
        if field_num == 1 and wire_type == 0:
            node.flags = parser.read_varint()
        elif field_num == 2 and wire_type == 0:
            node.cache_node_epoch = parser.read_varint()
        elif field_num == 3 and wire_type == 2:
            layer_data = parser.read_bytes()
            layer = _parse_layer(layer_data)
            node.layers.append(layer)
        elif field_num == 4 and wire_type == 2:
            parser.read_bytes()
        else:
            parser.skip_field(wire_type)
    
    return node


def _parse_layer(data: bytes) -> QuadtreeLayer:
    """解析四叉树图层
    
    Args:
        data: 图层数据
    
    Returns:
        QuadtreeLayer
    """
    parser = ProtobufParser(data)
    layer = QuadtreeLayer()
    
    while parser.has_more():
        field_num, wire_type = parser.read_tag()
        
        if field_num == 1 and wire_type == 0:
            layer.type = parser.read_varint()
        elif field_num == 2 and wire_type == 0:
            layer.layer_epoch = parser.read_varint()
        elif field_num == 3 and wire_type == 0:
            layer.provider = parser.read_varint()
        elif field_num == 4 and wire_type == 2:
            dates_data = parser.read_bytes()
            _parse_dates_layer(dates_data, layer)
        else:
            parser.skip_field(wire_type)
    
    return layer


def _parse_dates_layer(data: bytes, layer: QuadtreeLayer):
    """解析历史影像日期图层
    
    Args:
        data: 日期图层数据
        layer: 父图层对象
    """
    parser = ProtobufParser(data)
    
    while parser.has_more():
        field_num, wire_type = parser.read_tag()
        
        if field_num == 1 and wire_type == 2:
            dated_tile_data = parser.read_bytes()
            dt = _parse_dated_tile(dated_tile_data)
            if dt and dt.date > MIN_VALID_DATE:
                year, month, day = decode_ge_date(dt.date)
                if 1 <= month <= 12 and 1 <= day <= 31 and year > 2000:
                    dt.year = year
                    dt.month = month
                    dt.day = day
                    dt.hex_date = format(dt.date, 'x')
                    layer.dated_tiles.append(dt)
        elif field_num == 2 and wire_type == 0:
            layer.shared_tile_date = parser.read_varint()
        elif field_num == 3 and wire_type == 0:
            val = parser.read_varint()
            layer.coarse_tile_dates.append(val)
        else:
            parser.skip_field(wire_type)


def _parse_dated_tile(data: bytes) -> Optional[DatedTile]:
    """解析历史影像日期瓦片
    
    Args:
        data: 日期瓦片数据
    
    Returns:
        DatedTile 或 None
    """
    parser = ProtobufParser(data)
    dt = DatedTile()
    
    while parser.has_more():
        field_num, wire_type = parser.read_tag()
        
        if field_num == 1 and wire_type == 0:
            dt.date = parser.read_varint()
        elif field_num == 2 and wire_type == 0:
            dt.dated_tile_epoch = parser.read_varint()
        elif field_num == 3 and wire_type == 0:
            dt.provider = parser.read_varint()
        else:
            parser.skip_field(wire_type)
    
    return dt


class GoogleEarthClient:
    """Google Earth历史影像API客户端"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(GE_HEADERS)
        
        self._encryption_key = None
        self._db_version = 0
        self._initialized = False
        self._lock = threading.Lock()
    
    def initialize(self) -> bool:
        """初始化Google Earth客户端，获取加密密钥和数据库版本
        
        Returns:
            是否初始化成功
        """
        with self._lock:
            if self._initialized:
                return True
            
            try:
                print("正在初始化Google Earth TimeMachine数据库...")
                resp = self.session.get(DB_ROOT_URL, timeout=self.timeout)
                
                if resp.status_code != 200:
                    print(f"获取dbRoot失败: HTTP {resp.status_code}")
                    return False
                
                encrypted_data = resp.content
                
                if len(encrypted_data) < 100:
                    print("dbRoot数据过短")
                    return False
                
                encryption_data = self._extract_encryption_key(encrypted_data)
                if encryption_data is None:
                    print("无法提取加密密钥")
                    return False
                
                self._encryption_key = encryption_data
                
                db_root_data = self._extract_db_root(encrypted_data)
                if db_root_data:
                    self._db_version = self._extract_db_version(db_root_data)
                    print(f"Google Earth数据库版本: {self._db_version}")
                else:
                    self._db_version = 1031
                    print(f"使用默认数据库版本: {self._db_version}")
                
                self._initialized = True
                print("Google Earth客户端初始化成功")
                return True
                
            except Exception as e:
                print(f"初始化Google Earth客户端失败: {e}")
                return False
    
    def _extract_encryption_key(self, data: bytes) -> Optional[bytes]:
        """从加密的dbRoot数据中提取加密密钥
        
        Args:
            data: 加密的dbRoot响应数据
        
        Returns:
            加密密钥字节或None
        """
        try:
            parser = ProtobufParser(data)
            
            while parser.has_more():
                field_num, wire_type = parser.read_tag()
                
                if field_num == 2 and wire_type == 2:
                    key_data = parser.read_bytes()
                    if len(key_data) > 100:
                        return key_data
                else:
                    parser.skip_field(wire_type)
            
            return None
        except Exception:
            return None
    
    def _extract_db_root(self, data: bytes) -> Optional[bytes]:
        """从加密的dbRoot数据中提取并解压数据库根数据
        
        Args:
            data: 加密的dbRoot响应数据
        
        Returns:
            解密后的dbRoot数据或None
        """
        try:
            parser = ProtobufParser(data)
            
            while parser.has_more():
                field_num, wire_type = parser.read_tag()
                
                if field_num == 3 and wire_type == 2:
                    encrypted_root = parser.read_bytes()
                    if self._encryption_key:
                        decrypted = xor_decrypt(self._encryption_key, encrypted_root)
                        decompressed = decompress_packet(decrypted)
                        return decompressed
                else:
                    parser.skip_field(wire_type)
            
            return None
        except Exception:
            return None
    
    def _extract_db_version(self, data: bytes) -> int:
        """从dbRoot数据中提取数据库版本号
        
        Args:
            data: 解密后的dbRoot数据
        
        Returns:
            数据库版本号
        """
        try:
            parser = ProtobufParser(data)
            
            while parser.has_more():
                field_num, wire_type = parser.read_tag()
                
                if field_num == 13 and wire_type == 2:
                    version_data = parser.read_bytes()
                    version_parser = ProtobufParser(version_data)
                    while version_parser.has_more():
                        v_field, v_wire = version_parser.read_tag()
                        if v_field == 1 and v_wire == 0:
                            return version_parser.read_varint()
                        else:
                            version_parser.skip_field(v_wire)
                else:
                    parser.skip_field(wire_type)
            
            return 1031
        except Exception:
            return 1031
    
    def get_available_dates(self, x: int, y: int, z: int) -> List[Dict]:
        """获取指定瓦片位置可用的历史影像日期列表
        
        Args:
            x: 瓦片X坐标
            y: 瓦片Y坐标
            z: 缩放级别
        
        Returns:
            可用日期字典列表，每个包含 date, year, month, day, epoch, hex_date
        """
        if not self._initialized:
            if not self.initialize():
                return []
        
        quadtree_path = xyz_to_quadtree_path(x, y, z)
        return self._query_dates_for_path(quadtree_path)
    
    def _query_dates_for_path(self, target_path: str) -> List[Dict]:
        """查询指定四叉树路径的可用历史影像日期
        
        Args:
            target_path: 四叉树路径
        
        Returns:
            可用日期字典列表
        """
        all_dates = {}
        epoch = self._db_version
        
        traversal_paths = get_traversal_paths(target_path)
        
        for path in traversal_paths:
            packet_data = self._fetch_quadtree_packet(path, epoch)
            if packet_data is None:
                continue
            
            packet_epoch, nodes = parse_quadtree_packet(packet_data)
            
            if not nodes:
                continue
            
            for node in nodes:
                if node.cache_node_epoch != 0:
                    epoch = node.cache_node_epoch
                
                for layer in node.layers:
                    if layer.type == QuadtreeLayer.LAYER_TYPE_IMAGERY_HISTORY:
                        for dt in layer.dated_tiles:
                            date_key = f"{dt.year}-{dt.month:02d}-{dt.day:02d}"
                            if date_key not in all_dates:
                                all_dates[date_key] = {
                                    'date': date_key,
                                    'year': dt.year,
                                    'month': dt.month,
                                    'day': dt.day,
                                    'epoch': dt.dated_tile_epoch if dt.dated_tile_epoch != 0 else layer.layer_epoch,
                                    'hex_date': dt.hex_date,
                                    'packed_date': dt.date
                                }
        
        dates_list = list(all_dates.values())
        dates_list.sort(key=lambda d: d['date'], reverse=True)
        return dates_list
    
    def _fetch_quadtree_packet(self, path: str, epoch: int) -> Optional[bytes]:
        """获取四叉树数据包
        
        Args:
            path: 四叉树路径
            epoch: 版本号
        
        Returns:
            解密解压后的数据或None
        """
        url = f"{TM_BASE_URL}&qp-{path}-q.{epoch}"
        
        try:
            resp = self.session.get(url, timeout=self.timeout)
            
            if resp.status_code != 200:
                return None
            
            encrypted_data = resp.content
            
            if self._encryption_key:
                decrypted = xor_decrypt(self._encryption_key, encrypted_data)
                decompressed = decompress_packet(decrypted)
                return decompressed
            
            return None
        except Exception:
            return None
    
    def download_historical_tile(self, x: int, y: int, z: int,
                                 hex_date: str, epoch: int,
                                 save_path: str) -> bool:
        """下载历史影像瓦片
        
        Args:
            x: 瓦片X坐标
            y: 瓦片Y坐标
            z: 缩放级别
            hex_date: 十六进制日期字符串
            epoch: 瓦片版本号
            save_path: 保存路径
        
        Returns:
            是否下载成功
        """
        if not self._initialized:
            if not self.initialize():
                return False
        
        quadtree_path = xyz_to_quadtree_path(x, y, z)
        
        url = f"{TM_BASE_URL}&f1-{quadtree_path}-i.{epoch}-{hex_date}"
        
        return self._download_tile_with_fallback(url, save_path, quadtree_path, hex_date, epoch)
    
    def _download_tile_with_fallback(self, primary_url: str, save_path: str,
                                      quadtree_path: str, hex_date: str,
                                      primary_epoch: int) -> bool:
        """使用回退策略下载瓦片
        
        Args:
            primary_url: 主要URL
            save_path: 保存路径
            quadtree_path: 四叉树路径
            hex_date: 十六进制日期
            primary_epoch: 主要epoch
        
        Returns:
            是否下载成功
        """
        urls_to_try = [primary_url]
        
        for fallback_epoch in KNOWN_GOOD_EPOCHS:
            if fallback_epoch != primary_epoch:
                fallback_url = f"{TM_BASE_URL}&f1-{quadtree_path}-i.{fallback_epoch}-{hex_date}"
                urls_to_try.append(fallback_url)
        
        for url in urls_to_try:
            try:
                resp = self.session.get(url, timeout=self.timeout)
                
                if resp.status_code == 200:
                    content_type = resp.headers.get('Content-Type', '')
                    content = resp.content
                    
                    if 'protobuf' in content_type or len(content) < 500:
                        continue
                    
                    if self._encryption_key:
                        try:
                            decrypted = xor_decrypt(self._encryption_key, content)
                            if self._is_valid_image(decrypted):
                                with open(save_path, 'wb') as f:
                                    f.write(decrypted)
                                return True
                        except Exception:
                            pass
                    
                    if self._is_valid_image(content):
                        with open(save_path, 'wb') as f:
                            f.write(content)
                        return True
                
                elif resp.status_code == 404:
                    continue
            except Exception:
                continue
        
        return False
    
    def _is_valid_image(self, data: bytes) -> bool:
        """检查数据是否为有效的图像
        
        Args:
            data: 图像数据
        
        Returns:
            是否为有效图像
        """
        if len(data) < 4:
            return False
        
        if data[:2] == b'\xff\xd8':
            return True
        
        if data[:4] == b'\x89PNG':
            return True
        
        if data[:2] == b'BM':
            return True
        
        return False
    
    def download_current_tile(self, x: int, y: int, z: int,
                              save_path: str) -> bool:
        """下载当前影像瓦片
        
        Args:
            x: 瓦片X坐标
            y: 瓦片Y坐标
            z: 缩放级别
            save_path: 保存路径
        
        Returns:
            是否下载成功
        """
        quadtree_path = xyz_to_quadtree_path(x, y, z)
        epoch = self._db_version if self._initialized else 1031
        
        url = f"{DEFAULT_BASE_URL}/f1-{quadtree_path}-i.{epoch}"
        
        try:
            resp = self.session.get(url, timeout=self.timeout)
            
            if resp.status_code == 200:
                content = resp.content
                
                if self._encryption_key:
                    try:
                        decrypted = xor_decrypt(self._encryption_key, content)
                        if self._is_valid_image(decrypted):
                            with open(save_path, 'wb') as f:
                                f.write(decrypted)
                            return True
                    except Exception:
                        pass
                
                if self._is_valid_image(content):
                    with open(save_path, 'wb') as f:
                        f.write(content)
                    return True
            
            return False
        except Exception:
            return False
    
    def get_dates_for_area(self, center_x: int, center_y: int, z: int) -> List[Dict]:
        """获取指定区域中心瓦片的可用历史影像日期
        
        Args:
            center_x: 中心瓦片X坐标
            center_y: 中心瓦片Y坐标
            z: 缩放级别
        
        Returns:
            可用日期字典列表
        """
        dates = self.get_available_dates(center_x, center_y, z)
        
        if not dates:
            print("未找到历史影像日期，尝试使用较低缩放级别...")
            if z > 5:
                low_z = min(z - 3, 8)
                scale = 1 << (z - low_z)
                low_x = center_x // scale
                low_y = center_y // scale
                dates = self.get_available_dates(low_x, low_y, low_z)
        
        return dates
