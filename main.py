#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESRI Wayback 历史影像获取工具"""
import sys
import logging

# 让 logger 走 stdout，GUI 端的日志面板能实时看到进度
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

sys.stdout.reconfigure(line_buffering=True)

import argparse
from satellite_processor import WaybackImageFetcher


def main():
    parser = argparse.ArgumentParser(description='获取单个坐标点的所有历史卫星影像 (ESRI Wayback)')
    parser.add_argument('--lat', type=float, required=True, help='纬度')
    parser.add_argument('--lon', type=float, required=True, help='经度')
    parser.add_argument('--zoom', type=int, default=18, help='缩放级别 (默认: 18)')
    parser.add_argument('--output', type=str, default='data/output/historical', help='输出目录')
    parser.add_argument('--buffer', type=int, default=500, help='缓冲区大小，米 (默认: 500)')
    parser.add_argument('--date-range', nargs=2, metavar=('START', 'END'), help='日期范围，如: 2020-01-01 2024-12-31')

    args = parser.parse_args()

    date_range = tuple(args.date_range) if args.date_range else None

    print("=" * 60)
    print("ESRI Wayback 历史影像获取工具")
    print("=" * 60)
    print(f"坐标: ({args.lat}, {args.lon})")
    print(f"缩放级别: {args.zoom}")
    print(f"输出目录: {args.output}")
    print(f"缓冲区: {args.buffer} 米")
    if date_range:
        print(f"日期范围: {date_range[0]} ~ {date_range[1]}")
    print("=" * 60)

    # 入参校验
    if not (-90.0 <= args.lat <= 90.0):
        print(f"错误：lat 越界 {args.lat}，需 ∈ [-90, 90]", file=sys.stderr)
        sys.exit(2)
    if not (-180.0 <= args.lon <= 180.0):
        print(f"错误：lon 越界 {args.lon}，需 ∈ [-180, 180]", file=sys.stderr)
        sys.exit(2)
    if not (1 <= args.zoom <= 20):
        print(f"错误：zoom 越界 {args.zoom}，需 ∈ [1, 20]", file=sys.stderr)
        sys.exit(2)
    if args.buffer < 50 or args.buffer > 5000:
        print(f"错误：buffer 越界 {args.buffer}，需 ∈ [50, 5000]", file=sys.stderr)
        sys.exit(2)

    fetcher = WaybackImageFetcher()
    results = fetcher.fetch_all_historical(
        lat=args.lat,
        lon=args.lon,
        zoom=args.zoom,
        output_dir=args.output,
        buffer_size=args.buffer,
        date_range=date_range
    )

    if results:
        print("\n下载结果:")
        for r in results:
            status = "[OK]" if r['status'] == 'success' else "[FAIL]"
            print(f"  {status} {r['date']}")

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)

    success = sum(1 for r in results if r['status'] == 'success')
    if results and success == 0:
        # 全部失败 → 非零退出码
        sys.exit(1)


if __name__ == "__main__":
    main()
