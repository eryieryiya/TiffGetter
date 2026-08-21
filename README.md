# TiffGetter - ESRI Wayback 历史影像获取工具

获取坐标点的所有历史时期卫星影像（ESRI Wayback 数据源），生成带地理参考的 GeoTIFF/PNG 文件。

支持单点下载与批量下载（CSV / SHP）；提供命令行与图形界面两种使用方式。

## 功能

- 输入单个坐标（经纬度），获取该点所有历史时期的卫星影像
- 批量下载：CSV / SHP 文件批量坐标，Point 直接取点、Polygon 自动取 centroid
- 数据源自 **ESRI Wayback**，提供全球历史卫星影像
- 支持日期范围筛选
- 可调节缩放级别（1-20）和缓冲区大小
- 多线程并发下载，自动 MD5 去重
- 输出 GeoTIFF（带地理参考）和 PNG 预览
- 提供命令行和图形界面两种使用方式
- GUI 三 Tab：单点下载（含地图选点）/ 批量下载 / 清理与维护
- 启动时自动清理 `temp_tiles_*` 临时瓦片残余

## 使用方法

### 命令行

#### 单点模式（向后兼容）

```bash
# 基本用法 - 获取东京塔的历史影像
python main.py --lat 35.6586 --lon 139.7454

# 指定缩放级别和缓冲区大小
python main.py --lat 35.6586 --lon 139.7454 --zoom 18 --buffer 500

# 指定输出目录
python main.py --lat 35.6586 --lon 139.7454 --output ./output

# 日期范围筛选
python main.py --lat 35.6586 --lon 139.7454 --date-range 2020-01-01 2024-12-31
```

#### 批量模式（CSV / SHP）

```bash
# CSV 文件
python main.py --coords-file points.csv --output ./batch_out

# SHP 文件（自动读 .prj 转 WGS84，Polygon 取 centroid）
python main.py --coords-file sites.shp --output ./batch_out

# 日期范围 + 并发数
python main.py --coords-file points.csv --date-range 2024-01-01 2024-12-31 \
    --coord-concurrency 2 --output ./batch_out
```

#### CSV 文件格式

表头必须含 `lat` 与 `lon`；可选 `name`、`id`。UTF-8 编码，逗号/分号/Tab 自动识别。

```csv
name,id,lat,lon
Tokyo Tower,tokyo_tower,35.6586,139.7454
Beijing,Tiananmen,39.9087,116.3975
New York,liberty,40.6892,-74.0445
```

#### SHP 文件要求

- 几何类型：Point / Polygon / MultiPolygon；其他几何被跳过
- CRS：自动读取 `.prj`；非 EPSG:4326 时使用 `pyproj` 转换
- 名称字段：优先 `name` / `id` / `name` / `name_zh` / 名称；否则取第一个字符串型字段

### GUI

```bash
python ui_main.py
```

图形界面提供完整的参数控制，三 Tab 设计：

| Tab | 功能 |
|-----|------|
| 单点下载 | 坐标/参数/日期/输出 + 地图选点（点击地图选坐标） |
| 批量下载 | CSV/SHP 文件选择 + 预览 + 通用参数 + 结果表 |
| 清理与维护 | 扫描残留（temp_tiles_*/历史日期目录）+ 勾选 + 二次确认删除 |

| 区域 | 参数 | 说明 |
|------|------|------|
| 坐标 | 纬度、经度 | 目标点坐标（单点 Tab） |
| 参数设置 | 缩放级别 (1-20) | 地图瓦片缩放级别 |
| | 缓冲区（米，50-5000） | 下载范围半径 |
| 日期范围 | 起始 / 截止（可选） | 筛选特定时间段的影像 |
| 输出设置 | 输出目录 | 下载文件保存路径 |
| 批量文件 | CSV / SHP 文件 | 批量下载 Tab |
| | 坐标并发数 (1-16) | 坐标级并发，默认 1（避免限流） |

界面特点：

- **ttkbootstrap darkly 主题** — 深色风格、现代化外观
- **三 Tab 布局** — 单点 / 批量 / 清理 Tab 互不干扰
- **地图选点** — 嵌入式 OpenStreetMap 地图（Toplevel 弹窗），左键选点回写
- **进度条** — 日志中的 `[i/N]` 自动驱动 determinate 进度条
- **结果表** — Treeview 显示 success/existing/duplicate/failed；双击打开所在目录
- **深色日志面板** — 实时显示下载进度和调试信息
- **状态栏** — 显示当前任务状态（就绪 / 运行中 / 正在停止 / 完成 / 已停止 / 清理中）
- **停止按钮** — 支持随时终止正在进行的下载（CTRL_BREAK_EVENT）
- **清理 Tab** — 勾选式二次确认删除，避免误删

## 参数说明

### 通用参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--zoom` | 缩放级别 (1-20) | 18 |
| `--buffer` | 缓冲区大小（米） | 500 |
| `--output` | 输出目录 | data/output/historical |
| `--date-range` | 日期范围筛选（起始 截止） | 全部 |
| `--coord-concurrency` | 批量模式下坐标并发数 (1-16) | 1 |

### 单点模式（与 `--coords-file` 互斥）

| 参数 | 说明 | 必填 |
|------|------|------|
| `--lat` | 纬度 | 是（与 `--lon` 同时） |
| `--lon` | 经度 | 是（与 `--lat` 同时） |

### 批量模式

| 参数 | 说明 | 必填 |
|------|------|------|
| `--coords-file` | CSV 或 SHP 文件路径 | 是 |

## 输出结构

### 单点模式

```
data/output/historical/
├── 2024-01-15/
│   ├── 2024-01-15.png
│   └── 2024-01-15.tif
├── 2023-06-20/
│   ├── 2023-06-20.png
│   └── 2023-06-20.tif
└── ...
```

### 批量模式

```
data/output/batch/
├── tokyo_tower/                  # id 优先；否则 name；否则 point_N_lat_lon
│   ├── 2024-01-15/
│   │   ├── 2024-01-15.png
│   │   └── 2024-01-15.tif
│   └── 2023-06-20/
│       ├── 2023-06-20.png
│       └── 2023-06-20.tif
├── Tiananmen/
│   ├── ...
└── ...
```

每个历史日期包含：
- `*.png` — 卫星影像预览图
- `*.tif` — 带地理参考的 GeoTIFF（CRS: EPSG:4326 WGS84）

## 系统要求

- Python 3.10+
- [GDAL](https://gdal.org/)（用于 GeoTIFF 输出）
- 依赖：`requests`, `pillow`, `numpy`, `rasterio`, `pyyaml`, `psutil`, `pyshp`, `pyproj`, `ttkbootstrap`, `tkintermapview`

## 安装

```bash
conda env create -f environment.yml
conda activate satellite-image-processing
```

或纯 pip：

```bash
pip install requests pillow numpy rasterio pyyaml psutil pyshp pyproj ttkbootstrap tkintermapview
```

## 打包为独立 exe

将项目打包为独立的 Windows 可执行文件，无需安装 Python 环境即可运行。

### 一键打包

```powershell
.\build_exe.ps1
```

脚本会自动：
- 探测可用的 Python 环境（优先使用 Anaconda base）
- 安装缺失的依赖（pyinstaller、tkcalendar）
- 执行 PyInstaller 打包
- 验证产物（CLI --help、GUI 启动冒烟、归档内容检查）

### 产物

```
dist/TiffGetter.exe    # 约 83 MB，onefile 单文件
```

### 使用方式

- **GUI 模式**：双击 `TiffGetter.exe`
- **CLI 模式**：`TiffGetter.exe --lat 35.6586 --lon 139.7454`

### 构建环境要求

- Python 3.10+（推荐 3.12）
- PyInstaller 6.x
- 所有项目依赖（见 `environment.yml`）

### 已知问题与解决方案

打包过程中可能遇到的问题及解决方案已内置到 `TiffGetter.spec` 中：

1. **Tcl/Tk DLL 版本冲突**：多 conda 环境 PATH 污染时，PyInstaller 可能从错误的环境收集 tcl86t.dll。spec 中的 `_normalize_tcl_binaries()` 函数会自动修正。

2. **ttkbootstrap 资源缺失**：ttkbootstrap 无官方 PyInstaller hook，spec 中通过 `collect_data_files('ttkbootstrap')` 手动收集主题资源。

3. **rasterio 子模块缺失**：PyInstaller 静态分析无法发现 rasterio 的动态导入子模块，spec 中通过 `hiddenimports` 显式声明所有子模块。

4. **tkcalendar 与主题切换兼容性**：DateEntry 组件不使用 `bootstyle` 参数，避免 Calendar 内部对象缺少 `.style` 属性导致的 AttributeError。

### 手动打包

如需自定义打包参数：

```powershell
# 使用指定的 Python 环境
.\build_exe.ps1 -Python D:\Python312\python.exe

# 跳过自动安装依赖
.\build_exe.ps1 -NoInstallDeps

# 跳过打包后验证
.\build_exe.ps1 -SkipVerify
```

## 旧版本残余清理

启动时 `WaybackImageFetcher.__init__` 会自动清理根目录下所有 `temp_tiles_*` 目录。

也可在 GUI「清理与维护」Tab 手动扫描 temp_tiles + 历史日期子目录，勾选后二次确认批量删除。