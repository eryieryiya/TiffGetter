#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的重构验证测试
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from satellite_processor import SatelliteToTiffConverter
    from datetime import datetime
    
    print("开始重构验证测试...")
    
    # 创建转换器实例
    converter = SatelliteToTiffConverter()
    print(f"Wayback服务状态: {converter.wayback_enabled}")
    
    # 测试日期构建方法
    print("\n=== 测试日期构建方法 ===")
    
    # 测试当前影像日期构建
    current = converter._build_current_date_dict()
    print(f"当前影像: {current['name']} ({current['date']})")
    
    # 测试历史影像日期构建
    historical = converter._build_historical_date_dict(datetime.now().year - 1)
    print(f"历史影像: {historical['name']} ({historical['date']})")
    
    # 测试降级日期构建
    fallback = converter._build_fallback_dates(2)
    print(f"降级日期数量: {len(fallback)}")
    for i, date_info in enumerate(fallback):
        print(f"  {i+1}. {date_info['name']}: {date_info['date']}")
    
    # 测试完整的get_wayback_dates方法
    print("\n=== 测试完整的get_wayback_dates方法 ===")
    
    # 清空缓存
    converter._wayback_dates = None
    
    print("正在获取Wayback日期列表...")
    wayback_dates = converter.get_wayback_dates()
    
    if wayback_dates:
        print(f"成功获取 {len(wayback_dates)} 个影像服务版本")
        for i, date_info in enumerate(wayback_dates[:3]):  # 只显示前3个
            print(f"  {i+1}. {date_info['name']}: {date_info['date']}")
    else:
        print("未获取到任何Wayback日期")
    
    print("\n✅ 重构验证测试完成！")
    
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)