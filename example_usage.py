#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块化版本使用示例
展示如何使用point_kml2tif包进行完整的点到TIFF处理流程
"""

import sys
import os

# 直接导入模块
from point_reader import read_points
from buffer_generator import generate_buffers
from satellite_processor import SatelliteToTiffConverter
from config import *


def example_simple():
    """简单示例：完整流程"""
    print("="*50)
    print("模块化版本 - 简单使用示例")
    print("="*50)
    
    # 配置参数
    input_file = 'test_shp_point_data/tw.shp'
    buffer_size = 100 # 0.1,0.2公里缓冲区
    output_prefix = 'example_buffers'
    tiff_output_dir = 'example_output'
    
    # 1. 读取点数据
    print("\n1. 读取点数据...")
    points = read_points(input_file)
    print(f"找到 {len(points)} 个点")
    
    # 2. 生成缓冲区
    print(f"\n2. 生成 {buffer_size} 米缓冲区...")
    shapefile_path, kml_path = generate_buffers(points, buffer_size, output_prefix)
    print(f"生成的Shapefile: {shapefile_path}")
    print(f"生成的KML: {kml_path}")
    
    # 3. 生成TIFF影像
    print("\n3. 生成TIFF影像...")
    converter = SatelliteToTiffConverter()
    converter.process_kml_to_tiff(kml_path, tiff_output_dir)
    
    print("\n示例完成！")


def example_custom_config():
    """自定义配置示例"""
    print("\n" + "="*50)
    print("模块化版本 - 自定义配置示例")
    print("="*50)
    
    # 可以修改全局配置
    print(f"默认线程池大小: {config.THREAD_POOL_SIZE}")
    print(f"默认请求超时: {config.REQUEST_TIMEOUT}秒")
    print(f"默认重试次数: {config.RETRY_COUNT}次")
    
    # 修改配置（仅在当前运行时有效）
    config.THREAD_POOL_SIZE = 20
    config.REQUEST_TIMEOUT = 10
    print(f"修改后的线程池大小: {config.THREAD_POOL_SIZE}")
    print(f"修改后的请求超时: {config.REQUEST_TIMEOUT}秒")


if __name__ == "__main__":
    example_simple()
    example_custom_config()