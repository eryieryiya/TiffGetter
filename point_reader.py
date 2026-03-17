# 点数据读取模块 - 处理KML和SHP文件中的点数据

import sys
from osgeo import ogr, osr


def read_kml_points(input_path):
    """读取KML文件中的点数据"""
    points = []
    feature_count = 0
    
    print("开始读取KML文件...")
    print(f"KML文件路径: {input_path}")
    
    import re
    
    try:
        # 读取KML文件内容
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 使用正则表达式提取Placemark块
        placemark_pattern = re.compile(r'<Placemark[^>]*>(.*?)</Placemark>', re.DOTALL)
        placemarks = placemark_pattern.findall(content)
        
        print(f"KML文件包含 {len(placemarks)} 个Placemark")
        
        # 遍历每个Placemark
        for placemark_content in placemarks:
            feature_count += 1
            
            # 使用正则表达式提取coordinates标签中的内容
            coords_pattern = re.compile(r'<coordinates[^>]*>(.*?)</coordinates>', re.DOTALL)
            coords_match = coords_pattern.search(placemark_content)
            
            if not coords_match:
                print(f"  要素 {feature_count}：没有coordinates元素，跳过")
                continue
            
            coords_text = coords_match.group(1).strip()
            print(f"  要素 {feature_count}：coordinates文本: {coords_text}")
            
            # 解析坐标
            coords = coords_text.split(',')
            
            if len(coords) >= 2:
                try:
                    lon = float(coords[0])
                    lat = float(coords[1])
                    # 保持与read_shp_points函数一致的返回格式：(feature_id, lon, lat)
                    points.append((feature_count, lon, lat))
                    print(f"  要素 {feature_count}：找到点坐标 {lon}, {lat}")
                except ValueError as e:
                    print(f"  要素 {feature_count}：坐标格式错误，跳过 - {e}")
            else:
                print(f"  要素 {feature_count}：坐标数据不足，跳过")
        
        print(f"共处理 {feature_count} 个要素，找到 {len(points)} 个点")
        return points
        
    except Exception as e:
        print(f"错误：读取KML文件时发生异常 - {e}")
        import traceback
        traceback.print_exc()
        return []


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
    
    # 创建WGS84坐标系，设置坐标轴顺序为经度在前
    wgs84_srs = osr.SpatialReference()
    wgs84_srs.ImportFromEPSG(4326)
    wgs84_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
    # 如果源坐标系存在，也设置坐标轴顺序
    if src_srs:
        src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    
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