#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构验证测试 - 输出到文件
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from satellite_processor import SatelliteToTiffConverter
    from datetime import datetime
    
    # 创建转换器实例
    converter = SatelliteToTiffConverter()
    
    # 打开输出文件
    with open('test_output.txt', 'w', encoding='utf-8') as f:
        f.write("重构验证测试输出\n")
        f.write("="*50 + "\n")
        f.write(f"Wayback服务状态: {converter.wayback_enabled}\n")
        
        # 测试日期构建方法
        f.write("\n=== 测试日期构建方法 ===\n")
        
        # 测试当前影像日期构建
        current = converter._build_current_date_dict()
        f.write(f"当前影像: {current['name']} ({current['date']})\n")
        f.write(f"当前影像URL: {current['url_template']}\n")
        
        # 测试历史影像日期构建
        historical = converter._build_historical_date_dict(datetime.now().year - 1)
        f.write(f"历史影像: {historical['name']} ({historical['date']})\n")
        f.write(f"历史影像URL: {historical['url_template']}\n")
        
        # 测试降级日期构建
        fallback = converter._build_fallback_dates(2)
        f.write(f"降级日期数量: {len(fallback)}\n")
        for i, date_info in enumerate(fallback):
            f.write(f"  {i+1}. {date_info['name']}: {date_info['date']}\n")
        
        # 测试完整的get_wayback_dates方法
        f.write("\n=== 测试完整的get_wayback_dates方法 ===\n")
        
        # 清空缓存
        converter._wayback_dates = None
        
        f.write("正在获取Wayback日期列表...\n")
        wayback_dates = converter.get_wayback_dates()
        
        if wayback_dates:
            f.write(f"成功获取 {len(wayback_dates)} 个影像服务版本\n")
            for i, date_info in enumerate(wayback_dates):
                f.write(f"  {i+1}. {date_info['name']}: {date_info['date']}\n")
        else:
            f.write("未获取到任何Wayback日期\n")
        
        # 测试缓存功能
        f.write("\n=== 测试缓存功能 ===\n")
        cached_dates = converter.get_wayback_dates()
        if cached_dates is wayback_dates:
            f.write("缓存功能正常\n")
        else:
            f.write("缓存功能异常\n")
        
        f.write("\n✅ 重构验证测试完成！\n")
    
    print("测试完成，输出已保存到 test_output.txt")
    
except Exception as e:
    with open('test_error.txt', 'w', encoding='utf-8') as f:
        f.write(f"测试失败: {e}\n")
        import traceback
        f.write(traceback.format_exc())
    print("测试失败，错误信息已保存到 test_error.txt")