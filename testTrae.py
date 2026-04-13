#!/usr/bin/env python3
# 测试日志系统功能

import os
print(f"当前目录: {os.getcwd()}")
print(f"脚本所在目录: {os.path.dirname(__file__)}")
print(f"logs目录路径: {os.path.join(os.path.dirname(__file__), 'logs')}")
print(f"logs目录是否存在: {os.path.exists(os.path.join(os.path.dirname(__file__), 'logs'))}")

from satellite_processor import SatelliteToTiffConverter

# 测试日志系统
def test_logging_system():
    print("开始测试日志系统...")
    
    # 创建转换器实例，开启调试模式
    converter = SatelliteToTiffConverter(debug=True)
    
    # 测试不同级别的日志
    print("\n测试不同级别的日志输出...")
    print("这些信息应该同时出现在控制台和日志文件中")
    
    # 模拟一些操作来触发日志
    print("\n测试1: 获取历史影像日期")
    try:
        dates = converter.get_historical_dates_for_service('Google Earth', 39.9042, 116.4074, 15)
        print(f"获取到 {len(dates)} 个历史影像日期")
    except Exception as e:
        print(f"测试1失败: {e}")
    
    print("\n测试2: 解析KML文件")
    try:
        # 尝试解析一个不存在的KML文件，触发错误日志
        buffers = converter.parse_kml_file('non_existent.kml')
        print(f"解析到 {len(buffers)} 个缓冲区")
    except Exception as e:
        print(f"测试2失败: {e}")
    
    print("\n测试3: 测试下载功能")
    try:
        # 尝试下载一个小区域的影像
        success = converter.download_satellite_image(
            39.9042, 116.4074, 15,
            save_path='test_output.png',
            tile_count=1
        )
        print(f"下载结果: {'成功' if success else '失败'}")
    except Exception as e:
        print(f"测试3失败: {e}")
    
    print("\n测试完成，请检查logs目录下的日志文件")

if __name__ == "__main__":
    test_logging_system()