# 测试历史影像修复效果

import os
import sys
from satellite_processor import SatelliteToTiffConverter

# 测试配置
test_kml = os.path.join(os.path.dirname(__file__), 'data', 'input', 'test_buffers.kml')
test_output = os.path.join(os.path.dirname(__file__), 'data', 'output', 'test_historical_fix')

# 确保输出目录存在
os.makedirs(test_output, exist_ok=True)

def test_historical_imagery():
    """测试历史影像获取功能"""
    print("=== 测试历史影像修复效果 ===")
    
    # 初始化转换器
    converter = SatelliteToTiffConverter(debug=True)
    
    # 测试处理KML文件
    print(f"处理KML文件: {test_kml}")
    print(f"输出目录: {test_output}")
    
    # 使用 'both' 模式同时下载当前和历史影像
    success = converter.process_kml_to_tiff(
        kml_file_path=test_kml,
        output_dir=test_output,
        download_mode='both',
        service_name='Google Earth'
    )
    
    if success:
        print("\n=== 测试成功 ===")
        print("历史影像修复效果验证完成")
        print("请检查输出目录中的文件，确认历史影像与当前影像有明显区别")
        print(f"当前影像路径: {os.path.join(test_output, 'test_buffers', 'png')}")
        print(f"历史影像路径: {os.path.join(test_output, 'test_buffers', 'png_previous')}")
    else:
        print("\n=== 测试失败 ===")
        print("历史影像修复效果验证失败")

if __name__ == "__main__":
    test_historical_imagery()
