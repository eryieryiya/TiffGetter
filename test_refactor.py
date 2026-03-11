#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试重构后的get_wayback_dates方法
"""

import sys
import os
from datetime import datetime

# 直接导入模块
from satellite_processor import SatelliteToTiffConverter


def test_refactored_methods():
    """测试重构后的辅助方法"""
    print("="*60)
    print("测试重构后的get_wayback_dates方法")
    print("="*60)
    
    try:
        # 创建卫星影像处理器实例
        converter = SatelliteToTiffConverter()
        
        # 测试日期构建方法
        print("\n1. 测试日期构建方法...")
        
        # 测试当前影像日期构建
        current_date = converter._build_current_date_dict()
        print(f"当前影像日期: {current_date['name']} ({current_date['date']})")
        
        # 测试历史影像日期构建
        historical_date = converter._build_historical_date_dict(datetime.now().year - 1)
        print(f"历史影像日期: {historical_date['name']} ({historical_date['date']})")
        
        # 测试降级日期构建
        fallback_dates = converter._build_fallback_dates(count=2)
        print(f"降级日期列表: {len(fallback_dates)} 个日期")
        for date_info in fallback_dates:
            print(f"  - {date_info['name']}: {date_info['date']}")
        
        # 测试完整的get_wayback_dates方法
        print("\n2. 测试完整的get_wayback_dates方法...")
        
        # 清空缓存以强制重新获取
        converter._wayback_dates = None
        
        wayback_dates = converter.get_wayback_dates()
        
        if not wayback_dates:
            print("错误: 未获取到任何Wayback日期")
            return False
        
        print(f"成功获取 {len(wayback_dates)} 个影像服务版本")
        for date_info in wayback_dates:
            print(f"  - {date_info['name']}: {date_info['date']}")
        
        # 测试缓存功能
        print("\n3. 测试缓存功能...")
        cached_dates = converter.get_wayback_dates()
        if cached_dates is wayback_dates:
            print("缓存功能正常")
        else:
            print("缓存功能异常")
        
        print("\n重构测试完成！")
        return True
        
    except Exception as e:
        print(f"错误: 测试过程中发生异常 - {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_refactored_methods()
    if success:
        print("\n✅ 重构测试成功！")
    else:
        print("\n❌ 重构测试失败！")
        sys.exit(1)