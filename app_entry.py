#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TiffGetter 统一入口（开发与打包共用）

行为约定：
- 无参数（双击 exe 或 `python app_entry.py`）：启动 GUI（ui_main）
- 带参数：转发到 CLI（main.py），保持 --lat/--lon/--coords-file 等全部行为

打包说明：
PyInstaller onefile 打包后 exe 在系统临时目录解压运行，
osgeo/rasterio 的 GDAL 数据文件（gdalvrt.xsd 等）与 proj.db
不再位于 conda 环境中，需在启动时按 _MEIPASS 路径修正环境变量。
"""
import os
import sys


def _setup_geo_env():
    """修正 GDAL_DATA / PROJ_LIB，让打包后的 exe 找到地理数据文件。

    优先级：
    1) 已设置的环境变量（直接使用）
    2) PyInstaller 解压目录（spec 已将数据打包为 gdal_data/ 与 proj_data/）
    3) conda 环境默认路径（开发态 python app_entry.py 也适用）

    找不到时静默放过（不影响 PNG-only 输出，仅 GeoTIFF/坐标系转换受限）。
    """
    meipass = getattr(sys, '_MEIPASS', None)

    # ---- GDAL_DATA：gdalvrt.xsd / 坐标 WKT 定义等 ----
    if not os.environ.get('GDAL_DATA'):
        candidates = []
        if meipass:
            # spec 打包的 conda GDAL 数据目录
            candidates.append(os.path.join(meipass, 'gdal_data'))
            # rasterio wheel 自带的数据目录（spec 亦已收集）
            candidates.append(os.path.join(meipass, 'rasterio', 'gdal_data'))
        candidates.append(os.path.join(
            os.path.dirname(sys.executable), 'Library', 'share', 'gdal'))
        for path in candidates:
            try:
                if path and os.path.isdir(path):
                    os.environ['GDAL_DATA'] = os.path.abspath(path)
                    break
            except Exception:
                continue

    # ---- PROJ_LIB：proj.db（坐标参考系权威数据） ----
    if not os.environ.get('PROJ_LIB'):
        candidates = []
        if meipass:
            candidates.append(os.path.join(meipass, 'proj_data'))
            # rasterio wheel 自带的 proj.db
            candidates.append(os.path.join(meipass, 'rasterio', 'proj_data'))
        candidates.append(os.path.join(
            os.path.dirname(sys.executable), 'Library', 'share', 'proj'))
        for path in candidates:
            try:
                if path and os.path.isdir(path):
                    os.environ['PROJ_LIB'] = os.path.abspath(path)
                    break
            except Exception:
                continue


def _is_cli_invocation(argv):
    """判断是否为 CLI 调用。

    规则：存在参数且不是"单个 .py 文件"的情况才算 CLI。
    Windows 资源管理器可能把 .py 文件拖放/关联到 exe 上（例如 .py 文件
    关联被设为本程序，或 %TEMP% 中残留的历史解压入口脚本 main.py 被误
    双击），此时唯一的非选项参数是一个 .py 路径——这并非本工具 CLI 的
    合法用法，应视为 GUI 启动而非交给 argparse 报错。
    """
    args = argv[1:]
    if not args:
        return False
    non_option = [a for a in args if not a.startswith('-')]
    if len(non_option) == 1 and non_option[0].lower().endswith('.py'):
        return False
    return True


def _force_utf8_streams():
    """避免在 cp1252 等非中文控制台下打印中文时抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


def main():
    _force_utf8_streams()
    _setup_geo_env()

    if _is_cli_invocation(sys.argv):
        # CLI 模式：与 `python main.py ...` 行为完全一致
        from main import main as cli_main
        cli_main()
    else:
        # GUI 模式（默认）
        try:
            from ui_main import main as gui_main
        except Exception as e:
            sys.stderr.write(f"GUI 启动失败: {e}\n")
            sys.stderr.write("提示：可使用命令行模式，例如: "
                             "TiffGetter.exe --lat 35.6586 --lon 139.7454\n")
            sys.exit(1)
        gui_main()


if __name__ == "__main__":
    main()