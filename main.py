#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiffGetter 卫星影像获取工具 - CLI 入口

两种模式：
1) 单点模式（向后兼容）：--lat --lon
2) 批量模式：--coords-file <CSV | SHP>

参数：--source / --zoom / --buffer / --output / --date-range / --coord-concurrency
"""
import sys
import logging
import argparse

# 让 logger 走 stdout，GUI 端的日志面板能实时看到进度
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

sys.stdout.reconfigure(line_buffering=True)

from providers.registry import (
    DEFAULT_SOURCE, source_names, get_source, UnknownSourceError,
)
from satellite_processor import ImageFetcher
from coordinate_loader import load_coordinates_file, CoordinateLoadError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='获取坐标点的卫星影像（支持多数据源）',
    )
    # 单点 / 批量 二选一：
    # - 单点：--lat 与 --lon 都必须提供（不在 argparse 强制，由 main() 检查）
    # - 批量：--coords-file 单选
    # 这样保留向后兼容的 --lat/--lon 必填语义，同时支持 --coords-file 替代。
    parser.add_argument('--lat', type=float, help='纬度（单点模式；与 --lon 同时使用）')
    parser.add_argument('--lon', type=float, help='经度（单点模式；与 --lat 同时使用）')
    parser.add_argument(
        '--coords-file', type=str,
        help='批量坐标文件（.csv 或 .shp）；与 --lat/--lon 互斥',
    )

    parser.add_argument(
        '--source', type=str, choices=source_names(), default=DEFAULT_SOURCE,
        help=('数据源（可选: ' + ', '.join(source_names())
              + f'；默认: {DEFAULT_SOURCE}）'),
    )
    parser.add_argument('--zoom', type=int, default=18, help='缩放级别 (默认: 18)')
    parser.add_argument(
        '--output', type=str, default=None,
        help=('输出目录（默认随数据源变化：wayback → data/output/historical，'
              '其它 → data/output/<source>）'),
    )
    parser.add_argument('--buffer', type=int, default=500,
                        help='缓冲区大小，米 (默认: 500)')
    parser.add_argument('--date-range', nargs=2, metavar=('START', 'END'),
                        help='日期范围，如: 2020-01-01 2024-12-31（仅支持历史的数据源可用）')
    parser.add_argument('--coord-concurrency', type=int, default=1,
                        help='批量模式下坐标并发数（默认: 1）')

    return parser


def _validate_common(args):
    if not (1 <= args.zoom <= 20):
        print(f"错误：zoom 越界 {args.zoom}，需 ∈ [1, 20]", file=sys.stderr)
        sys.exit(2)
    if args.buffer < 50 or args.buffer > 5000:
        print(f"错误：buffer 越界 {args.buffer}，需 ∈ [50, 5000]", file=sys.stderr)
        sys.exit(2)
    if args.coord_concurrency < 1 or args.coord_concurrency > 16:
        print(f"错误：coord-concurrency 越界 {args.coord_concurrency}，需 ∈ [1, 16]",
              file=sys.stderr)
        sys.exit(2)


def _resolve_output_dir(args) -> str:
    if args.output is not None:
        return args.output
    if args.source == 'wayback':
        return 'data/output/historical'
    return f'data/output/{args.source}'


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 数据源解析（argparse choices 通常已拦截，这里保留防御）
    try:
        info = get_source(args.source).info
    except UnknownSourceError as e:
        print(f"错误：{e}", file=sys.stderr)
        print(f"可选数据源: {', '.join(source_names())}", file=sys.stderr)
        sys.exit(2)

    # 非历史数据源不允许日期范围
    if args.date_range is not None and not info.supports_history:
        print(
            f"错误：数据源 {info.display_name} 不支持历史日期，--date-range 不可用",
            file=sys.stderr,
        )
        sys.exit(2)

    # 互斥组：必须给出 (--lat + --lon) 或 --coords-file 之一
    if args.coords_file is None and (args.lat is None or args.lon is None):
        parser.error("必须提供 --lat/--lon（单点模式）或 --coords-file（批量模式）")
    if args.coords_file is not None and (args.lat is not None or args.lon is not None):
        parser.error("--coords-file 与 --lat/--lon 不能同时使用")

    date_range = tuple(args.date_range) if args.date_range else None

    _validate_common(args)

    # 按数据源缩放范围截断
    if args.zoom > info.max_zoom:
        logging.warning(
            f"缩放级别 {args.zoom} 超过 {info.display_name} 上限 "
            f"{info.max_zoom}，已截断为 {info.max_zoom}"
        )
        args.zoom = info.max_zoom
    elif args.zoom < info.min_zoom:
        logging.warning(
            f"缩放级别 {args.zoom} 低于 {info.display_name} 下限 "
            f"{info.min_zoom}，已截断为 {info.min_zoom}"
        )
        args.zoom = info.min_zoom

    output_dir = _resolve_output_dir(args)

    print("=" * 60)
    print("TiffGetter 卫星影像获取工具")
    print("=" * 60)
    print(f"数据源: {info.display_name} (source={info.name})")
    print(f"版权: {info.attribution}")
    if info.experimental:
        print("实验性数据源，接口可能随时失效")
    if args.coords_file:
        print(f"模式: 批量")
        print(f"坐标文件: {args.coords_file}")
        print(f"并发: {args.coord_concurrency}")
    else:
        print(f"模式: 单点")
        print(f"坐标: ({args.lat}, {args.lon})")
    print(f"缩放级别: {args.zoom}")
    print(f"输出目录: {output_dir}")
    print(f"缓冲区: {args.buffer} 米")
    if date_range:
        print(f"日期范围: {date_range[0]} ~ {date_range[1]}")
    print("=" * 60)

    # 单点坐标校验
    if args.coords_file is None:
        if not (-90.0 <= args.lat <= 90.0):
            print(f"错误：lat 越界 {args.lat}，需 ∈ [-90, 90]", file=sys.stderr)
            sys.exit(2)
        if not (-180.0 <= args.lon <= 180.0):
            print(f"错误：lon 越界 {args.lon}，需 ∈ [-180, 180]", file=sys.stderr)
            sys.exit(2)

    fetcher = ImageFetcher(source=args.source)

    if args.coords_file:
        # 批量模式
        try:
            coords = load_coordinates_file(args.coords_file)
        except CoordinateLoadError as e:
            print(f"错误：坐标文件解析失败: {e} ({e.path}) hint={e.hint}",
                  file=sys.stderr)
            sys.exit(2)
        print(f"解析到 {len(coords)} 个坐标点")
        summary = fetcher.fetch_batch(
            coords=coords,
            output_root=output_dir,
            zoom=args.zoom,
            buffer_size=args.buffer,
            date_range=date_range,
            coord_concurrency=args.coord_concurrency,
        )

        # 打印批量摘要
        print("\n批量结果摘要:")
        print(f"数据源: {info.display_name} (source={info.name})")
        total_success = 0
        total_failed = 0
        all_zero = True
        for s in summary:
            status = "[OK]" if s['failed'] == 0 and s['success'] > 0 else (
                "[FAIL]" if s['success'] == 0 else "[PART]")
            print(f"  {status} {s['name']}  ({s['lat']:.6f}, {s['lon']:.6f}) "
                  f"成功 {s['success']}/{s['total_dates']}")
            total_success += s['success']
            total_failed += s['failed']
            if s['success'] > 0:
                all_zero = False

        print("\n" + "=" * 60)
        print(f"完成！共 {len(summary)} 个坐标点；日期版本成功 {total_success}, "
              f"失败 {total_failed}")
        print("=" * 60)
        # 退出码：所有坐标全部失败 → 1；否则 0
        if summary and all_zero:
            sys.exit(1)
        sys.exit(0)
    else:
        # 单点模式
        results = fetcher.fetch_all(
            lat=args.lat,
            lon=args.lon,
            zoom=args.zoom,
            output_dir=output_dir,
            buffer_size=args.buffer,
            date_range=date_range,
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
            sys.exit(1)


if __name__ == "__main__":
    main()
