# TiffGetter - 多数据源卫星影像获取工具

获取坐标点的历史或当前卫星影像，生成带地理参考的 GeoTIFF/PNG 文件。支持 **ESRI Wayback、ESRI 当前影像、Google Earth（实验性）、Bing、OpenStreetMap** 五个数据源。

支持单点下载与批量下载（CSV / SHP）；提供命令行与图形界面两种使用方式。

## 功能

- 输入单个坐标（经纬度），获取该点在所选数据源下的历史或当前影像
- 批量下载：CSV / SHP 文件批量坐标，Point 直接取点、Polygon 自动取 centroid
- 多数据源可选，默认 **ESRI Wayback**（历史影像）
- 支持日期范围筛选（仅支持历史版本的数据源）
- 可调节缩放级别（1-20）和缓冲区大小
- 多线程并发下载，自动 MD5 + dHash 去重（按数据源隔离），可用 `--no-dedup` 关闭
- 输出 GeoTIFF（带地理参考）和 PNG 预览
- 每个输出目录写入 `metadata.json`（数据源、版本、版权、范围、参数）
- 提供命令行和图形界面两种使用方式
- GUI 三 Tab：单点下载（含地图选点）/ 批量下载 / 清理与维护
- 启动时自动清理 `temp_tiles_*` 临时瓦片残余

## 数据源

`--source` 可选值与能力如下（并发上限为实际下载线程数，线程池更大时也会被限制到该值）：

| source | 名称 | 历史版本 | 最大 zoom | 并发 | 版权 / 归属 |
|---|---|---|---|---|---|
| `wayback`（默认） | ESRI Wayback | 支持 | 20 | 10 | Esri World Imagery Wayback |
| `esri` | ESRI 当前影像 | 不支持 | 18 | 8 | Esri World Imagery |
| `google` | Google Earth（实验性） | 支持（实验性） | 20 | 4 | Google |
| `bing` | Bing 影像 | 不支持 | 19 | 4 | Microsoft Bing Maps |
| `osm` | OpenStreetMap | 不支持 | 19 | 2 | © OpenStreetMap contributors |

- 不支持历史版本的数据源只返回一个 `current` 版本，输出目录为 `current/`。
- 请求的缩放级别超过数据源上限时会自动截断到上限并给出警告。
- 未注册的 `--source` 以退出码 2 结束，并列出可选数据源。

## 能力边界

先按需求选数据源，避免把“数据源不提供历史”误判为下载失败：

| 需求 | 应使用 | 说明 |
|---|---|---|
| 某点的 ESRI 历史影像 | `wayback` | ESRI 官方历史存档，按 release 日期逐版本输出 |
| 某点的 Google 历史影像 | `google` | 实验性 TimeMachine 接口，可用日期取决于该坐标的存档 |
| 只要最新影像 | `esri` / `bing` / `osm` | 仅返回一个 `current`，没有历史版本 |
| 保留每一个历史日期目录 | `wayback` / `google` + `--no-dedup` | 关闭去重后，即使影像视觉相同也按日期各写一份 |

各数据源的边界：

- **ESRI Wayback**：历史影像的正解。日期来自 ESRI 官方 release 列表，不同日期可能发布完全相同的瓦片，默认会被去重。
- **ESRI 当前影像**：与 Wayback 使用同一套 World Imagery 瓦片服务，但服务元数据 `timeInfo = null`，没有时间维度，因此只提供 `current`。需要 ESRI 历史请改用 `--source wayback`。
- **Google Earth**：实验性数据源，依赖 Google 的非公开 TimeMachine 接口，可用日期、瓦片层级与接口本身都可能随时变化；部分日期只存在于特定层级，程序会自动向下探测。GUI 中选择该数据源时会在下拉框下方显示使用边界提示。
- **Bing**：仅提供当前影像，没有公开的历史影像接口。
- **OpenStreetMap**：实时渲染瓦片，不提供按日期的历史快照；并发上限固定为 2。OSM 可能用 HTTP 200 返回 “Access blocked” 拦截页（响应头 `X-Blocked`），程序会识别并拒绝保存；遇到时请降低频率、等待解封或改用其它数据源。GUI 中选择 OSM 时会显示边界提示（公共瓦片仅适合轻量、单点使用），批量下载启动前还会弹出二次确认，可取消。地图选点支持 Esri 卫星图 / 矢量图底图切换，不受 OSM 限流影响。

统一限制：

- 只有 `wayback` 与 `google` 接受 `--date-range`；其它数据源传入时直接以退出码 2 结束。
- CLI 启动时会打印 `版本能力: 支持历史版本` 或 `版本能力: 仅当前影像（数据源本身无历史存档）`。
- 非历史源的输出固定为 `<输出目录>/current/current.png|tif`。
- 默认开启去重（中心瓦片预筛 + 整图 MD5/dHash），因此“请求 N 个日期只得到少量目录”属于正常现象；需要全部日期时加 `--no-dedup`。

## 使用方法

### 命令行

#### 单点模式（向后兼容）

```bash
# 基本用法 - 获取东京塔的 Wayback 历史影像（默认数据源）
python main.py --lat 35.6586 --lon 139.7454

# 显式指定 Wayback 历史影像
python main.py --lat 35.6586 --lon 139.7454 --source wayback

# ESRI 当前影像（不支持 --date-range）
python main.py --lat 35.6586 --lon 139.7454 --source esri

# OpenStreetMap 当前影像（并发上限 2）
python main.py --lat 35.6586 --lon 139.7454 --source osm --zoom 18

# 指定缩放级别和缓冲区大小
python main.py --lat 35.6586 --lon 139.7454 --zoom 18 --buffer 500

# 指定输出目录（不再在其下追加数据源层级）
python main.py --lat 35.6586 --lon 139.7454 --output ./output

# 日期范围筛选（仅 wayback / google 支持）
python main.py --lat 35.6586 --lon 139.7454 --date-range 2020-01-01 2024-12-31

# 获取 2022-2025 的每一个历史日期（不去重）
python main.py --source wayback --lat 35.6586 --lon 139.7454 \
    --zoom 17 --buffer 500 --no-dedup \
    --date-range 2022-01-01 2025-12-31 --output ./wayback_all

# Google Earth 历史影像（实验性）
python main.py --source google --lat 35.6586 --lon 139.7454 \
    --zoom 17 --buffer 500 --no-dedup \
    --date-range 2022-01-01 2025-12-31 --output ./google_all

# 当前影像（esri / bing / osm 只输出 current，不能带 --date-range）
python main.py --source bing --lat 35.6586 --lon 139.7454 --zoom 17 --buffer 500
```

`--no-dedup` 与 `--date-range` 组合时，数据源返回多少个日期，就输出多少个日期目录；不使用 `--no-dedup` 时，视觉相同的日期会被合并，属预期行为。

#### 批量模式（CSV / SHP）

```bash
# CSV 文件
python main.py --coords-file points.csv --output ./batch_out

# SHP 文件（自动读 .prj 转 WGS84，Polygon 取 centroid）
python main.py --coords-file sites.shp --output ./batch_out

# 指定数据源（所有坐标点共用）
python main.py --coords-file points.csv --source bing --output ./batch_out

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

### Docker（仅 CLI）

镜像只包含命令行模式，不含 GUI。镜像地址：`ghcr.io/eryieryiya/tiffgetter`；`:latest` 随最新 tag 更新，生产环境建议固定 `:vX.Y.Z`。

```bash
# 单点：输出到宿主机 ./out
docker run --rm \
  -v "$PWD/out:/app/data/output" \
  ghcr.io/eryieryiya/tiffgetter:v0.1.0 \
  --source esri --lat 35.6586 --lon 139.7454 --zoom 15 --buffer 300

# 批量：挂载坐标文件
docker run --rm \
  -v "$PWD/out:/app/data/output" \
  -v "$PWD/points.csv:/app/points.csv:ro" \
  ghcr.io/eryieryiya/tiffgetter:latest \
  --coords-file /app/points.csv --source bing
```

- 容器内输出根目录为 `/app/data/output`，对应上面的宿主机挂载目录；默认仍按数据源生成 `<source>/current/` 或历史日期目录。
- Linux 下若宿主机目录不可写，可加 `-u "$(id -u):$(id -g)"`，或提前给挂载目录写权限。
- PowerShell 中把 `"$PWD/out:..."` 写成 `"${PWD}/out:/app/data/output"`。
- 镜像不含 GUI；OSM 对数据中心 IP 可能限流，容器内建议优先使用 `esri`、`bing` 或 `wayback`。
- GHCR 首次发布后包默认私有，需要在 GitHub 的 Packages 设置中把可见性改为 Public（如需公开）。

### GUI

```bash
python ui_main.py
```

图形界面提供完整的参数控制，三 Tab 设计：

| Tab | 功能 |
|-----|------|
| 单点下载 | 坐标/参数/日期/输出 + 地图选点（点击地图选坐标） |
| 批量下载 | CSV/SHP 文件选择 + 预览 + 通用参数 + 结果表 |
| 清理与维护 | 扫描残留（temp_tiles_*/所有数据源 release 目录）+ 勾选 + 二次确认删除 |

顶部工具条的「数据源」下拉框由单点 / 批量两个 Tab 共用，切换时联动日期范围可用性、缩放上限、默认输出目录，并显示当前数据源版权与实验性提示。

| 区域 | 参数 | 说明 |
|------|------|------|
| 数据源 | wayback / esri / google / bing / osm | 默认 ESRI Wayback；子进程显式传递 `--source` |
| 坐标 | 纬度、经度 | 目标点坐标（单点 Tab） |
| 参数设置 | 缩放级别 (1-20，随数据源) | 地图瓦片缩放级别，非历史源上限较低 |
| | 缓冲区（米，50-5000） | 下载范围半径 |
| 日期范围 | 起始 / 截止（可选） | 仅支持历史版本的数据源可用 |
| 输出设置 | 输出目录 | 下载文件保存路径，默认随数据源变化 |
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
| `--source` | 数据源：`wayback` / `esri` / `google` / `bing` / `osm` | `wayback` |
| `--zoom` | 缩放级别 (1-20，按数据源上限截断) | 18 |
| `--buffer` | 缓冲区大小（米） | 500 |
| `--output` | 输出目录 | wayback → `data/output/historical`；其它 → `data/output/<source>` |
| `--date-range` | 日期范围筛选（起始 截止，仅支持历史的数据源） | 全部 |
| `--coord-concurrency` | 批量模式下坐标并发数 (1-16) | 1 |
| `--no-dedup` | 关闭重复检测，每个历史日期都单独输出 | 关闭（默认去重） |

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

默认路径随数据源变化：

- `wayback`：`data/output/historical/<date>/<date>.png|tif`（与旧版一致，不追加 source 层级）
- 其它数据源：`data/output/<source>/current/current.png|tif`
- 显式传入 `--output <dir>`：严格写入该目录，不再自动追加数据源或 `current` 层级

```
data/output/
├── historical/                 # wayback 默认
│   ├── 2024-01-15/
│   │   ├── 2024-01-15.png
│   │   ├── 2024-01-15.tif
│   │   └── metadata.json
│   └── ...
├── esri/                       # --source esri 默认
│   └── current/
│       ├── current.png
│       ├── current.tif
│       └── metadata.json
├── bing/
│   └── current/...
└── osm/
    └── current/...
```

### 批量模式

输出根目录同样随数据源变化（GUI 批量默认 wayback → `data/output/batch`，其它 → `data/output/<source>`；CLI 未指定 `--output` 时 wayback 为 `data/output/historical`），每个坐标点一个独立子目录：

```
data/output/batch/                    # wayback
├── tokyo_tower/                      # id 优先；否则 name；否则 point_N_lat_lon
│   ├── 2024-01-15/                   # 历史源：日期目录
│   │   ├── 2024-01-15.png
│   │   ├── 2024-01-15.tif
│   │   └── metadata.json
│   └── 2023-06-20/...
└── ...

data/output/esri/                     # 非历史源
└── tokyo_tower/
    └── current/                      # 非历史源：current 目录
        ├── current.png
        ├── current.tif
        └── metadata.json
```

每个 release 目录包含：

- `*.png` — 卫星影像预览图
- `*.tif` — 带地理参考的 GeoTIFF（CRS: EPSG:4326 WGS84）
- `metadata.json` — 数据源、版本、版权、坐标、缩放、缓冲区、边界、采集时间与文件列表

### metadata.json

```json
{
  "source": "esri",
  "release_id": "current",
  "release_date": "current",
  "attribution": "Esri World Imagery",
  "lat": 35.6586,
  "lon": 139.7454,
  "zoom": 18,
  "buffer": 500,
  "bounds": {"min_lon": 139.74, "min_lat": 35.65, "max_lon": 139.75, "max_lat": 35.66},
  "created_at": "2026-11-18T12:00:00+08:00",
  "files": {"png": "current.png", "tif": "current.tif"}
}
```

### 去重规则

- 去重索引（MD5、dHash、中心瓦片预筛）仅在**同一数据源内**比较，同一地点用不同数据源下载会各自保留。
- 扫描已有输出时，只纳入 `metadata.json` 中 `source` 与本次一致的文件。
- 缺少 `metadata.json` 的旧输出按 `wayback` 处理，保持向后兼容。
- 同一视觉组保留**最早日期**：按日期升序遍历，先下载的日期保留，后续相同影像标记为 `duplicate`。
- 指定 `--date-range` 时，去重只与区间内的已有输出比较，区间外的旧影像不会让区间内更早的日期被跳过；结束时打印 `[区间校验] 区间内最早保留影像日期: ...`，区间内没有影像时给出告警。
- 需要保留下载到的每个历史日期时，加 `--no-dedup`：跳过中心瓦片预筛与整图去重，即使影像视觉相同也各写一个日期目录。

## 版权与使用限制

- **ESRI Wayback / ESRI 当前影像**：影像版权归 Esri（World Imagery / Wayback），输出 `metadata.json` 保留归属文本。
- **OpenStreetMap**：并发上限固定为 2，请勿批量高频抓取；使用或分发时需注明 **© OpenStreetMap contributors**，并遵守 OSM Tile Usage Policy。
- **Bing**：影像版权归 Microsoft Bing Maps；批量下载前请自行确认 Bing Maps 服务条款与许可范围。
- **Google Earth**：实验性数据源，接口可能随时失效，且使用受 Google 服务条款约束；批量下载前请自行确认许可。
- 本项目仅提供下载工具，不授予任何影像的再分发权利，商用或公开发布前请自行核实各数据源条款。

## 系统要求

- Python 3.10+
- [GDAL](https://gdal.org/)（用于 GeoTIFF 输出）
- 依赖：`requests`, `pillow`, `numpy`, `rasterio`, `psutil`, `pyshp`, `pyproj`, `ttkbootstrap`, `tkintermapview`

## 安装

```bash
conda env create -f environment.yml
conda activate satellite-image-processing
```

或纯 pip：

```bash
pip install requests pillow numpy rasterio psutil pyshp pyproj ttkbootstrap tkintermapview
```

## 测试

测试套件全部离线运行，不访问网络、不读写 `data/output`：

```bash
python -m pytest
```

`pytest` 与 `ruff` 的配置统一放在 `pyproject.toml`。静态检查：

```bash
python -m ruff check .
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

启动时 `ImageFetcher.__init__` 会自动清理根目录下所有 `temp_tiles_*` 目录。

也可在 GUI「清理与维护」Tab 手动扫描 temp_tiles 与 `data/output` 下所有数据源的 release 目录（仅识别包含 `metadata.json` 或同名 PNG 的目录），勾选后二次确认批量删除。