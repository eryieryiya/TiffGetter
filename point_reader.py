# 点数据读取模块 - 处理KML和SHP文件中的点数据

import sys
from osgeo import ogr, osr


def read_kml_points(input_path):
    """读取KML文件中的点数据"""
    points = []
    feature_count = 0
    
    # 打开KML文件
    driver = ogr.GetDriverByName('KML')
    if not driver:
        print("错误：GDAL未找到KML驱动")
        sys.exit(1)
    
    data_source = driver.Open(input_path, 0)  # 0表示只读
    if not data_source:
        print(f"错误：无法打开文件 {input_path}")
        sys.exit(1)
    
    # 遍历所有图层（KML中的Folder对应图层）
    layer_count = data_source.GetLayerCount()
    print(f"KML文件包含 {layer_count} 个图层")
    
    for layer_idx in range(layer_count):
        layer = data_source.GetLayer(layer_idx)
        if not layer:
            continue
        
        layer_name = layer.GetName()
        print(f"正在读取图层：{layer_name}")
        
        # 遍历图层中的所有要素
        layer.ResetReading()
        for feature in layer:
            feature_count += 1
            geom = feature.GetGeometryRef()
            
            if not geom:
                continue
            
            # 直接尝试获取坐标，不依赖几何类型判断
            try:
                # 尝试直接获取X,Y坐标
                lon = geom.GetX()
                lat = geom.GetY()
                points.append((feature_count, lon, lat))
                print(f"  要素 {feature_count}：找到点坐标 {lon}, {lat}")
            except:
                # 如果直接获取坐标失败，尝试其他方法
                try:
                    # 获取几何边界框的中心点
                    envelope = geom.GetEnvelope()
                    if envelope:
                        min_x, max_x, min_y, max_y = envelope
                        lon = (min_x + max_x) / 2
                        lat = (min_y + max_y) / 2
                        points.append((feature_count, lon, lat))
                        print(f"  要素 {feature_count}：从边界框找到点坐标 {lon}, {lat}")
                except:
                    print(f"  要素 {feature_count}：无法提取坐标，跳过")
    
    data_source = None  # 关闭数据源
    print(f"共处理 {feature_count} 个要素，找到 {len(points)} 个点")
    return points


def read_shp_points(input_path):
    """读取SHP文件中的点数据"""
    points = []
    
    # 打开SHP文件
    driver = ogr.GetDriverByName('ESRI Shapefile')
    if not driver:
        print("错误：GDAL未找到ESRI Shapefile驱动")
        sys.exit(1)
    
    data_source = driver.Open(input_path, 0)  # 0表示只读
    if not data_source:
        print(f"错误：无法打开文件 {input_path}")
        sys.exit(1)
    
    # 获取图层
    layer = data_source.GetLayer(0)
    if not layer:
        print("错误：SHP文件中没有图层")
        sys.exit(1)
    
    # 检查图层是否为点类型
    if layer.GetGeomType() != ogr.wkbPoint:
        print("错误：SHP文件不是点图层")
        sys.exit(1)
    
    # 获取图层坐标系
    src_srs = layer.GetSpatialRef()
    
    # 创建WGS84坐标系
    wgs84_srs = osr.SpatialReference()
    wgs84_srs.ImportFromEPSG(4326)
    
    # 创建坐标转换器
    transform = None
    if src_srs and src_srs.ExportToWkt() != wgs84_srs.ExportToWkt():
        transform = osr.CoordinateTransformation(src_srs, wgs84_srs)
    
    # 遍历要素
    for feature_id, feature in enumerate(layer, 1):
        geom = feature.GetGeometryRef()
        if geom:
            # 转换坐标到WGS84
            if transform:
                geom.Transform(transform)
            
            lon = geom.GetX()
            lat = geom.GetY()
            points.append((feature_id, lon, lat))
    
    data_source = None  # 关闭数据源
    return points


def read_points(input_file):
    """统一的点数据读取接口，根据文件扩展名自动选择读取方式"""
    from os.path import splitext, exists
    
    if not exists(input_file):
        print(f"错误：输入文件不存在 {input_file}")
        sys.exit(1)
    
    input_ext = splitext(input_file)[1].lower()
    if input_ext == '.kml':
        print(f"读取KML文件：{input_file}")
        return read_kml_points(input_file)
    elif input_ext == '.shp':
        print(f"读取SHP文件：{input_file}")
        return read_shp_points(input_file)
    else:
        print("错误：仅支持KML和SHP格式的输入文件")
        sys.exit(1)