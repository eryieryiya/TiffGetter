#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
# 设置无缓冲输出
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
"""
点数据到TIFF影像的完整处理流程
整合了点读取、缓冲区生成和卫星影像处理功能
支持获取当前影像和前一个时刻的历史影像
"""

import sys
import os
import argparse

# 导入自定义模块
from point_reader import read_points
from buffer_generator import generate_buffers
from satellite_processor import SatelliteToTiffConverter
from config import PATHS, PROCESSING


def main():
    """主函数，协调完整工作流程"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='点数据到TIFF影像处理工具')
    parser.add_argument('--mode', type=str, default='current',
                        choices=['current', 'previous', 'both'],
                        help='影像下载模式：current(当前影像), previous(前一个时刻影像), both(两者都下载)')
    args = parser.parse_args()

    download_mode = args.mode

    # 从配置文件读取路径
    input_file = PATHS.get('input_file', 'test_shp_point_data/tw.shp')  # 输入点文件路径
    output_prefix = PATHS.get('output_prefix', 'square_buffers')  # 输出文件路径前缀
    tiff_output_dir = PATHS.get('tiff_output_dir', 'tiff_output')  # TIFF输出目录

    # 从配置文件读取缓冲区尺寸
    buffer_sizes = PROCESSING.get('buffer_sizes', [1000, 2000])  # 默认缓冲区尺寸（米）

    print("="*60)
    print("开始处理：从点数据到带地理参考的TIFF影像")
    print("="*60)

    print(f"配置信息：")
    print(f"  输入文件：{input_file}")
    print(f"  缓冲区尺寸：{buffer_sizes} 米")
    print(f"  输出前缀：{output_prefix}")
    print(f"  TIFF输出目录：{tiff_output_dir}")
    print(f"  下载模式：{download_mode}")
    print("="*60)

    # 1. 读取点数据
    print(f"\n1. 读取点数据")
    points = read_points(input_file)

    if not points:
        print("错误：文件中没有找到点要素")
        sys.exit(1)

    print(f"找到 {len(points)} 个点")

    # 2. 生成缓冲区并处理每个尺寸
    for buffer_size in buffer_sizes:
        print(f"\n2. 生成 {buffer_size} 米的正方形缓冲区...")

        # 生成缓冲区
        shapefile_path, kml_path = generate_buffers(points, buffer_size, output_prefix)

        # 3. 处理KML生成TIFF
        print(f"\n3. 处理KML生成TIFF影像...")
        converter = SatelliteToTiffConverter()
        converter.process_kml_to_tiff(kml_path, tiff_output_dir, download_mode=download_mode)

    print("\n" + "="*60)
    print("所有处理完成！")
    print("="*60)


if __name__ == "__main__":
    main()