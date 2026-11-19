# -*- mode: python ; coding: utf-8 -*-
"""TiffGetter PyInstaller 打包配置（onefile 单 exe，GUI + CLI 统一入口）

生成: dist/TiffGetter.exe
入口: app_entry.py（无参数 → GUI；带参数 → CLI）
数据: GDAL 数据目录 + rasterio 自带 proj/gdal 数据
"""
import os
import sys

# CI 的 Windows 控制台可能是 cp1252，spec 内中文 print 会抛 UnicodeEncodeError。
# 统一把标准输出/错误切换为 UTF-8，避免打包在非中文代码页环境下中断。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

project_root = os.path.abspath(SPECPATH)  # spec 所在目录 = 项目根目录

# ---------------------------------------------------------------------------
# 数据文件
# ---------------------------------------------------------------------------
datas = []

# 1) GDAL 数据目录（gdalvrt.xsd、WKT 定义等）：
#    conda 环境默认位置 Library/share/gdal，打包为 gdal_data/
def _find_gdal_share():
    candidates = []
    for base in (sys.base_prefix, os.environ.get('CONDA_PREFIX', ''),
                 os.path.dirname(sys.executable)):
        if base:
            candidates.append(os.path.join(base, 'Library', 'share', 'gdal'))
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


_gdal_share = _find_gdal_share()
if _gdal_share:
    datas.append((_gdal_share, 'gdal_data'))
    print(f'[*] 打包 GDAL 数据: {_gdal_share} -> gdal_data')
else:
    print('[!] 未找到 conda GDAL 数据目录，使用 rasterio wheel 自带 GDAL/PROJ 数据')

# 3) rasterio wheel 自带的 proj.db 与 GDAL 数据（无官方 hook，必须手动收集）
_rasterio_datas = collect_data_files(
    'rasterio', includes=['proj_data/**', 'gdal_data/**'])
datas += _rasterio_datas
print(f'[*] rasterio 数据文件 {len(_rasterio_datas)} 项'
      f'（含 proj.db / gdalvrt.xsd）')

# 4) pyproj 自带的 proj 数据（proj_dir/proj.db，与 hooks-contrib 的 hook 互补）
_pyproj_datas = collect_data_files('pyproj', includes=['proj_dir/**'])
datas += _pyproj_datas
print(f'[*] pyproj 数据文件 {len(_pyproj_datas)} 项')

# 5) ttkbootstrap 主题资源（assets/icons/*.ttf 等，无官方 hook 必须手动收集）
_ttk_datas = collect_data_files('ttkbootstrap')
datas += _ttk_datas
print(f'[*] ttkbootstrap 资源文件 {len(_ttk_datas)} 项'
      f'（含主题图标字体 assets/icons/）')

# ---------------------------------------------------------------------------
# 二进制（rasterio 包内的动态库：GDAL DLL 等，防止依赖分析漏检）
# ---------------------------------------------------------------------------
binaries = collect_dynamic_libs('rasterio')
print(f'[*] rasterio 动态库 {len(binaries)} 个')

# ---------------------------------------------------------------------------
# 排除大型无关依赖（缩小体积、加快启动）
# ---------------------------------------------------------------------------
excludes = [
    'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'scipy', 'pandas', 'geopandas', 'IPython', 'jedi', 'notebook', 'pytest',
]

# ---------------------------------------------------------------------------
# 图标：自动从 icon/main_v2.png 生成 icon/main_v2.ico（多尺寸 16/32/48/64/128/256）
# ---------------------------------------------------------------------------
icon_png = os.path.join(project_root, 'icon', 'main_v2.png')
icon_path = None
if os.path.exists(icon_png):
    try:
        from PIL import Image
        ico_path = os.path.join(project_root, 'icon', 'main_v2.ico')
        img = Image.open(icon_png)
        # ICO 内嵌多尺寸（Windows 资源管理器/任务栏/快捷方式分别使用）
        ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        # 仅保留源图能覆盖的尺寸（避免 PIL 上采样模糊）
        sizes = [s for s in ico_sizes if min(img.size) >= s[0]]
        img.save(ico_path, format='ICO', sizes=sizes)
        icon_path = ico_path
        print(f'[*] 已从 {icon_png} 生成 ICO: {ico_path}（尺寸 {sizes}）')
    except Exception as e:
        print(f'[!] 图标生成失败（将使用默认图标）: {e}')
        icon_path = None
else:
    print('[!] 未找到 icon/main_v2.png，使用默认图标')

# ---------------------------------------------------------------------------
# 隐式导入（PyInstaller 静态分析无法发现的模块）
# ---------------------------------------------------------------------------
hiddenimports = [
    # 数据源实现：registry 通过 importlib 字符串映射动态导入，静态分析无法发现
    'providers.wayback',
    'providers.esri_current',
    'providers.bing',
    'providers.osm',
    'providers.google_earth',
    'providers.google_earth_client',
    # rasterio 子模块：动态导入，静态分析遗漏
    'rasterio.sample',
    'rasterio.vrt',
    'rasterio.warp',
    'rasterio.mask',
    'rasterio.merge',
    'rasterio.features',
    'rasterio.fill',
    'rasterio.plot',
    'rasterio.profiles',
    'rasterio.rpc',
    'rasterio.session',
    'rasterio.shutil',
    'rasterio.stack',
    'rasterio.tools',
    'rasterio.windows',
    'rasterio.rio',
    'rasterio.rio.main',
    'rasterio.rio.options',
    'rasterio.rio.helpers',
    'rasterio._base',
    'rasterio._env',
    'rasterio._err',
    'rasterio._features',
    'rasterio._filepath',
    'rasterio._fill',
    'rasterio._io',
    'rasterio._path',
    'rasterio._show_versions',
    'rasterio._transform',
    'rasterio._version',
    'rasterio._vsiopener',
    'rasterio._warp',
]

# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(project_root, 'app_entry.py')],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

# ---------------------------------------------------------------------------
# 修正 Tcl/Tk DLL 来源（多 conda 环境 PATH 污染问题）
#
# 当构建时 PATH/CONDA_PREFIX 指向其他 conda 环境时，PyInstaller 的二进制
# 依赖解析可能从该环境收集 tcl86t.dll/tk86t.dll，与 _tcl_data（取自构建
# 解释器自身环境、版本匹配）不一致，GUI 启动即抛
# "version conflict for package Tcl"（have X, need exactly Y）。
# 这里强制把 Tcl/Tk DLL 归一化为构建解释器自己的 Library/bin。
def _normalize_tcl_binaries(a):
    dll_names = {'tcl86t.dll', 'tk86t.dll', 'tcl86gd.dll', 'tk86gd.dll'}
    own = {}
    for name in dll_names:
        p = os.path.join(sys.base_prefix, 'Library', 'bin', name)
        if os.path.exists(p):
            own[name] = p
    if not own:
        print('[!] 未在构建环境找到 Tcl/Tk DLL（Library/bin），跳过归一化')
        return

    base = os.path.abspath(sys.base_prefix).lower()
    envs_root = os.path.join(base, 'envs')

    def _is_own_env(path):
        """来源属于构建解释器自身环境（且不在其他 conda envs 子目录下）"""
        p = os.path.abspath(path).lower()
        if not p.startswith(base):
            return False
        return not p.startswith(envs_root)

    kept, replaced = [], 0
    for tu in a.binaries:
        dest = os.path.basename(tu[0]) if tu else ''
        if dest in dll_names and not _is_own_env(tu[1]):
            replaced += 1
            continue  # 丢弃来自其他 conda 环境的同名 DLL
        kept.append(tu)
    for name, p in own.items():
        if not any(os.path.basename(t[0]) == name for t in kept):
            kept.append((name, p, 'BINARY'))
    a.binaries = kept
    print(f'[*] Tcl/Tk DLL 归一化: {replaced} 个别名来自外部环境，'
          f'已统一为 {sys.base_prefix}\\Library\\bin')


_normalize_tcl_binaries(a)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TiffGetter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # 保留控制台：CLI 模式可用、GUI 疑难可看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if icon_path else None,
)