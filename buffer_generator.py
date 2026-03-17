# 缓冲区生成模块 - 将点数据转换为正方形缓冲区

import sys
import os
from osgeo import ogr, osr

# 导入配置
from config import PATHS


def create_square_buffer(longitude, latitude, buffer_size_m):
    """创建正方形缓冲区"""
    # 打印输入坐标
    print(f"  输入坐标: 经度={longitude}, 纬度={latitude}")
    
    # 检查坐标有效性
    if not (-90 <= latitude <= 90):
        print(f"  错误：纬度值无效: {latitude}")
        # 创建默认多边形
        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(0, 0)
        ring.AddPoint(0.001, 0)
        ring.AddPoint(0.001, 0.001)
        ring.AddPoint(0, 0.001)
        ring.AddPoint(0, 0)
        polygon = ogr.Geometry(ogr.wkbPolygon)
        polygon.AddGeometry(ring)
        return polygon, polygon
    
    # 使用简单的方法计算缓冲区边界
    # 近似计算：1度经度约等于111320米，1度纬度约等于111320米
    # 但纬度越高，经度距离越短，这里使用简化计算
    meters_per_degree = 111320
    half_size_deg = (buffer_size_m / 2) / meters_per_degree
    
    # 计算边界坐标
    min_lon = longitude - half_size_deg
    max_lon = longitude + half_size_deg
    min_lat = latitude - half_size_deg
    max_lat = latitude + half_size_deg
    
    print(f"  缓冲区边界: 最小经度={min_lon}, 最大经度={max_lon}, 最小纬度={min_lat}, 最大纬度={max_lat}")
    
    # 创建WGS84坐标的多边形
    ring_wgs84 = ogr.Geometry(ogr.wkbLinearRing)
    # 注意：AddPoint的参数顺序是 (x, y)，对应 (经度, 纬度)
    ring_wgs84.AddPoint(min_lon, min_lat)
    ring_wgs84.AddPoint(max_lon, min_lat)
    ring_wgs84.AddPoint(max_lon, max_lat)
    ring_wgs84.AddPoint(min_lon, max_lat)
    ring_wgs84.AddPoint(min_lon, min_lat)  # 闭合
    
    polygon_wgs84 = ogr.Geometry(ogr.wkbPolygon)
    polygon_wgs84.AddGeometry(ring_wgs84)
    
    # 创建Web Mercator坐标的多边形
    # 这里直接使用WGS84坐标，因为后续处理可能不依赖坐标系
    polygon_mercator = polygon_wgs84.Clone()
    
    return polygon_mercator, polygon_wgs84


def save_to_shapefile(buffers, output_path, buffer_size):
    """保存缓冲区到Shapefile"""
    # 创建shp子文件夹
    shp_subdir = PATHS.get('shp_output_subdir', 'shp')
    output_dir = os.path.join(os.path.dirname(output_path), shp_subdir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 构建完整的输出路径
    shp_filename = f"{os.path.basename(output_path)}_{buffer_size}m.shp"
    shp_path = os.path.join(output_dir, shp_filename)
    
    # 创建驱动
    driver = ogr.GetDriverByName('ESRI Shapefile')
    
    # 删除已存在的文件
    if os.path.exists(shp_path):
        driver.DeleteDataSource(shp_path)
    
    # 创建数据源
    data_source = driver.CreateDataSource(shp_path)
    if not data_source:
        print(f"错误：无法创建Shapefile {shp_path}")
        sys.exit(1)
    
    # 创建WGS84坐标系，设置坐标轴顺序为经度在前
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
    # 创建图层
    layer = data_source.CreateLayer('buffers', srs, ogr.wkbPolygon)
    if not layer:
        print(f"错误：无法在 {shp_path} 中创建图层")
        sys.exit(1)
    
    # 添加属性字段
    buffer_id_field = ogr.FieldDefn('buffer_id', ogr.OFTInteger)
    layer.CreateField(buffer_id_field)
    
    source_id_field = ogr.FieldDefn('source_id', ogr.OFTInteger)
    layer.CreateField(source_id_field)
    
    buffer_size_field = ogr.FieldDefn('buf_size', ogr.OFTReal)
    layer.CreateField(buffer_size_field)
    
    # 添加要素
    for buffer_id, source_id, polygon in buffers:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField('buffer_id', buffer_id)
        feature.SetField('source_id', source_id)
        feature.SetField('buf_size', buffer_size)
        feature.SetGeometry(polygon)
        layer.CreateFeature(feature)
        feature = None  # 释放资源
    
    data_source = None  # 关闭数据源
    print(f"成功保存Shapefile：{shp_path}")
    return shp_path


def save_to_kml(buffers, output_path, buffer_size):
    """保存缓冲区到KML"""
    # 创建kml子文件夹
    kml_subdir = PATHS.get('kml_output_subdir', 'kml')
    output_dir = os.path.join(os.path.dirname(output_path), kml_subdir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 构建完整的输出路径
    kml_filename = f"{os.path.basename(output_path)}_{buffer_size}m.kml"
    kml_path = os.path.join(output_dir, kml_filename)
    
    # 创建驱动
    driver = ogr.GetDriverByName('KML')
    
    # 删除已存在的文件
    if os.path.exists(kml_path):
        driver.DeleteDataSource(kml_path)
    
    # 创建数据源
    data_source = driver.CreateDataSource(kml_path)
    if not data_source:
        print(f"错误：无法创建KML {kml_path}")
        sys.exit(1)
    
    # 创建WGS84坐标系，设置坐标轴顺序为经度在前
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
    # 创建图层
    layer = data_source.CreateLayer('buffers', srs, ogr.wkbPolygon)
    if not layer:
        print(f"错误：无法在 {kml_path} 中创建图层")
        sys.exit(1)
    
    # 添加属性字段
    buffer_id_field = ogr.FieldDefn('buffer_id', ogr.OFTInteger)
    layer.CreateField(buffer_id_field)
    
    source_id_field = ogr.FieldDefn('source_id', ogr.OFTInteger)
    layer.CreateField(source_id_field)
    
    buffer_size_field = ogr.FieldDefn('buf_size', ogr.OFTReal)
    layer.CreateField(buffer_size_field)
    
    # 添加要素
    for buffer_id, source_id, polygon in buffers:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField('buffer_id', buffer_id)
        feature.SetField('source_id', source_id)
        feature.SetField('buf_size', buffer_size)
        feature.SetGeometry(polygon)
        layer.CreateFeature(feature)
        feature = None  # 释放资源
    
    data_source = None  # 关闭数据源
    print(f"成功保存KML：{kml_path}")
    return kml_path


def generate_buffers(points, buffer_size, output_prefix):
    """生成缓冲区并保存为Shapefile和KML"""
    print(f"生成 {buffer_size} 米的正方形缓冲区...")
    buffers_mercator = []  # 米制坐标的缓冲区
    buffers_wgs84 = []     # WGS84坐标的缓冲区
    
    for buffer_id, (source_id, lon, lat) in enumerate(points, 1):
        polygon_mercator, polygon_wgs84 = create_square_buffer(lon, lat, buffer_size)
        buffers_mercator.append((buffer_id, source_id, polygon_mercator))
        buffers_wgs84.append((buffer_id, source_id, polygon_wgs84))
    
    # 保存为Shapefile（WGS84）
    shapefile_path = save_to_shapefile(buffers_wgs84, output_prefix, buffer_size)
    
    # 保存为KML（WGS84）
    kml_path = save_to_kml(buffers_wgs84, output_prefix, buffer_size)
    
    return shapefile_path, kml_path