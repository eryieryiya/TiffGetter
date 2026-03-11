#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试ESRI World Imagery Wayback历史影像下载功能
"""

import sys
import os

# 直接导入模块
from satellite_processor import SatelliteToTiffConverter


def test_wayback_dates():
    """测试获取ESRI World Imagery Wayback可用日期列表"""
    print("="*60)
    print("测试ESRI World Imagery Wayback服务")
    print("="*60)
    
    try:
        # 创建卫星影像处理器实例
        converter = SatelliteToTiffConverter()
        
        # 获取可用的历史影像日期列表
        print("\n1. 获取ESRI World Imagery Wayback可用日期列表...")
        wayback_dates = converter.get_wayback_dates()
        
        if not wayback_dates:
            print("错误: 未获取到任何Wayback日期")
            return False
        
        print(f"成功获取 {len(wayback_dates)} 个影像服务版本")
        for date_info in wayback_dates:
            print(f"  - {date_info['name']}: {date_info['date']} (ID: {date_info['id']})")
            print(f"    URL模板: {date_info.get('url_template', 'N/A')}")
            if date_info.get('time'):
                print(f"    时间参数: {date_info['time']}")
        
        # 获取当前和前一个时刻的影像日期信息
        print("\n2. 获取当前和前一个时刻的影像日期信息...")
        current_date, previous_date = converter.get_current_and_previous_dates()
        
        if current_date:
            print(f"当前影像: {current_date['name']} ({current_date['date']})")
        else:
            print("错误: 未获取到当前影像日期信息")
            return False
        
        if previous_date:
            print(f"历史影像: {previous_date['name']} ({previous_date['date']})")
        else:
            print("警告: 未获取到历史影像日期信息")
        
        print("\n测试完成！")
        return True
        
    except Exception as e:
        print(f"错误: 测试过程中发生异常 - {e}")
        return False


if __name__ == "__main__":
    success = test_wayback_dates()
    if success:
        print("\n✅ ESRI World Imagery Wayback服务测试成功！")
    else:
        print("\n❌ ESRI World Imagery Wayback服务测试失败！")
        sys.exit(1)
