# 卫星影像处理工具 - Satellite Image Processing Tool

一个模块化的地理空间数据处理工具，用于从点数据生成缓冲区并下载多源卫星影像，最终生成带有地理参考的 TIFF 影像。

## 📋 目录

- [功能特性](#-功能特性)
- [系统要求](#-系统要求)
- [安装说明](#-安装说明)
- [项目结构](#-项目结构)
- [配置说明](#-配置说明)
- [使用方法](#-使用方法)
- [输入输出](#-输入输出)
- [示例](#-示例)
- [注意事项](#-注意事项)
- [故障排除](#-故障排除)

## ✨ 功能特性

- **多格式支持**：支持 KML 和 ESRI Shapefile (SHP) 格式的点数据输入
- **缓冲区生成**：为点数据自动生成指定大小的正方形缓冲区
- **多数据源支持**：
  - ESRI World Imagery
  - Google Earth
  - Bing Maps
  - OpenStreetMap
- **历史影像**：支持通过 ESRI Wayback 服务下载历史卫星影像
- **智能处理**：
  - 自动计算最佳缩放级别
  - 动态线程池优化
  - 自动重试机制
- **多种输出格式**：
  - Shapefile (SHP)
  - KML
  - 地理参考 TIFF (GeoTIFF)
- **用户界面**：提供图形化界面 (GUI) 和命令行两种使用方式

## 💻 系统要求

- **操作系统**：Windows 10/11, macOS, Linux
- **Python 版本**：3.10 或更高（推荐 3.13）
- **内存**：至少 4GB RAM
- **磁盘空间**：至少 50GB 可用空间（用于临时文件和输出）
- **网络**：稳定的互联网连接（用于下载卫星影像）

## 📦 安装说明

### 方法一：使用 Conda（推荐）

```bash
# 1. 克隆或下载项目
cd modular_version

# 2. 创建 conda 环境
conda env create -f environment.yml

# 3. 激活环境
conda activate satellite-image-processing
```

### 方法二：手动安装

```bash
# 1. 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux

# 2. 安装 GDAL（使用 conda 或系统包管理器）
conda install -c conda-forge gdal

# 3. 安装其他依赖
pip install requests pillow numpy rasterio pyyaml psutil ttkbootstrap
```

### 验证安装

```bash
python -c "from osgeo import ogr, osr; print('GDAL 安装成功')"
```

## 📁 项目结构

```
modular_version/
├── __init__.py              # 包初始化文件
├── buffer_generator.py      # 缓冲区生成模块
├── config.py                # 配置管理模块
├── config.yaml              # 配置文件
├── point_kml2tif.py         # 主程序入口
├── point_reader.py          # 点数据读取模块
├── satellite_processor.py   # 卫星影像处理模块
├── ui_main.py               # 图形用户界面
├── environment.yml          # Conda 环境配置
├── setup.md                 # 详细配置指南
├── README.md                # 本文件
└── data/                    # 数据目录
    ├── input/               # 输入数据目录
    │   ├── kml/             # KML 输入文件
    │   └── shp/             # SHP 输入文件
    └── output/              # 输出数据目录
        ├── shp/             # Shapefile 输出
        ├── kml/             # KML 输出
        ├── tiff_output/     # GeoTIFF 输出
        └── temp_tiles/      # 临时瓦片目录
```

### 核心模块说明

| 模块 | 功能 |
|------|------|
| `point_reader.py` | 读取 KML 和 SHP 文件中的点坐标数据 |
| `buffer_generator.py` | 为点数据生成正方形缓冲区 |
| `satellite_processor.py` | 下载卫星影像并生成地理参考 TIFF |
| `point_kml2tif.py` | 主程序，协调整个处理流程 |
| `config.py` + `config.yaml` | 配置管理和参数设置 |
| `ui_main.py` | 图形用户界面 |

## ⚙️ 配置说明

### config.yaml 配置文件

编辑 `config.yaml` 文件来自定义项目行为：

```yaml
# 路径配置
paths:
  input_file: data/input/kml/测试数据.kml  # 输入文件路径
  output_prefix: square_buffers           # 输出文件前缀
  shp_output_subdir: shp                  # Shapefile 输出子目录
  kml_output_subdir: kml                  # KML 输出子目录
  tiff_output_dir: data/output/tiff_output # TIFF 输出目录
  temp_tiles_dir: data/output/temp_tiles  # 临时瓦片目录

# 处理参数
processing:
  buffer_sizes: [500]      # 缓冲区大小（米）
  thread_pool_size: 49     # 线程池大小
  default_zoom: 18         # 默认缩放级别
  max_zoom: 19             # 最大缩放级别
  min_zoom: 1              # 最小缩放级别
  tile_size: 256           # 瓦片大小（像素）
  request_timeout: 30      # 请求超时（秒）
  retry_count: 3           # 重试次数
  download_mode: current   # 下载模式：current/previous/both

# 数据源配置
data_source:
  default_data_source: OpenStreetMap  # 默认数据源
```

### 支持的卫星数据源

| 数据源 | 最大缩放级别 | 特点 |
|--------|------------|------|
| ESRI World Imagery | 18 | 全球覆盖，更新频繁 |
| Google Earth | 20 | 高分辨率，城市地区细节丰富 |
| Bing Maps | 19 | 全球覆盖，影像质量高 |
| OpenStreetMap | 19 | 开源地图，需遵守使用政策 |

## 🚀 使用方法

### 方法一：命令行使用

#### 基本用法

```bash
# 使用配置文件中的默认设置
python point_kml2tif.py
```

#### 指定数据源

```bash
# 使用 Google Earth 数据源
python point_kml2tif.py --data-source "Google Earth"

# 使用 OpenStreetMap 数据源
python point_kml2tif.py --data-source "OpenStreetMap"
```

#### 下载模式

```bash
# 仅下载当前最新影像（默认）
python point_kml2tif.py --mode current

# 仅下载前一个时刻的影像
python point_kml2tif.py --mode previous

# 同时下载当前和历史影像
python point_kml2tif.py --mode both
```

#### 组合使用示例

```bash
# 使用 Google Earth 下载当前影像
python point_kml2tif.py --data-source "Google Earth" --mode current

# 使用 OpenStreetMap 下载历史和当前影像
python point_kml2tif.py --data-source "OpenStreetMap" --mode both
```

### 方法二：图形界面

```bash
# 启动 GUI 界面
python ui_main.py
```

在界面中：
1. 选择输入文件（KML 或 SHP）
2. 设置缓冲区大小
3. 选择卫星数据源
4. 选择下载模式
5. 点击"开始处理"

### 方法三：Python 模块导入

```python
from point_reader import read_points
from buffer_generator import generate_buffers
from satellite_processor import SatelliteToTiffConverter

# 1. 读取点数据
points = read_points('data/input/kml/测试数据.kml')

# 2. 生成缓冲区（500 米）
shapefile_path, kml_path = generate_buffers(points, 500, 'square_buffers')

# 3. 下载卫星影像并生成 TIFF
converter = SatelliteToTiffConverter()
converter.process_kml_to_tiff(
    kml_path, 
    'data/output/tiff_output',
    download_mode='current',
    service_name='Google Earth'
)
```

## 📤 输入输出

### 支持的输入格式

1. **KML 文件** (.kml)
   - Google Earth 点数据格式
   - 支持 Placemark 中的 Point 元素
   - 坐标格式：经度，纬度，高度

2. **ESRI Shapefile** (.shp)
   - ESRI 矢量数据格式
   - 支持点图层
   - 自动坐标转换到 WGS84

### 输出格式

1. **Shapefile** (.shp, .shx, .dbf 等)
   - 位置：`data/output/shp/`
   - 坐标系：WGS84 (EPSG:4326)
   - 包含缓冲区多边形

2. **KML** (.kml)
   - 位置：`data/output/kml/`
   - 坐标系：WGS84
   - 可在 Google Earth 中查看

3. **GeoTIFF** (.tif)
   - 位置：`data/output/tiff_output/`
   - 包含地理参考信息
   - 可直接在 GIS 软件中使用

### 输出目录结构

```
data/output/
├── shp/
│   └── square_buffers_500m.shp (及相关文件)
├── kml/
│   └── square_buffers_500m.kml
└── tiff_output/
    └── 测试数据/
        ├── png/           # 当前影像 PNG
        │   └── 20240316_缓冲区 ID.png
        ├── tif/           # 当前影像 TIFF
        │   └── 20240316_缓冲区 ID.tif
        ├── png_previous/  # 历史影像 PNG（mode=previous/both 时）
        └── tif_previous/  # 历史影像 TIFF（mode=previous/both 时）
```

## 📖 示例

### 示例 1：处理日本东京的点数据

```bash
# 使用配置文件中的默认设置（OpenStreetMap 数据源）
python point_kml2tif.py

# 输出：
# - data/output/shp/square_buffers_500m.shp
# - data/output/kml/square_buffers_500m.kml
# - data/output/tiff_output/测试数据/tif/时间戳_缓冲区 ID.tif
```

### 示例 2：使用 Google Earth 高清影像

```bash
# 使用 Google Earth 数据源
python point_kml2tif.py --data-source "Google Earth"
```

### 示例 3：对比历史影像变化

```bash
# 下载当前和历史影像进行对比
python point_kml2tif.py --mode both --data-source "ESRI World Imagery"
```

### 示例 4：自定义缓冲区大小

编辑 `config.yaml`：

```yaml
processing:
  buffer_sizes: [100, 500, 1000]  # 生成三种大小的缓冲区
```

然后运行：

```bash
python point_kml2tif.py
```

## ⚠️ 注意事项

### 1. OpenStreetMap 使用政策

使用 OpenStreetMap 数据源时，请遵守其使用政策：
- 必须设置合适的 User-Agent
- 限制请求频率，避免对服务器造成过大压力
- 大量下载建议使用本地镜像或其他商业数据源

### 2. 坐标系统

- 所有处理均使用 WGS84 坐标系 (EPSG:4326)
- KML 文件坐标格式：经度，纬度，高度
- Shapefile 文件自动处理坐标转换
- GDAL 3.0+ 版本已设置传统 GIS 坐标轴顺序（经度在前）

### 3. 缩放级别选择

- 程序会自动根据缓冲区大小计算最佳缩放级别
- 默认缩放级别：18
- 最大缩放级别取决于数据源（18-20）
- 缩放级别越高，影像分辨率越高，下载时间越长

### 4. 网络要求

- 需要稳定的互联网连接
- 大量瓦片下载可能需要较长时间
- 建议在网络状况良好时使用

## 🔧 故障排除

### 常见问题

#### 1. GDAL 安装失败

**问题**：`pip install gdal` 失败

**解决方案**：
```bash
# 使用 conda 安装（推荐）
conda install -c conda-forge gdal

# 或使用预编译的 wheel 文件
pip install GDAL --only-binary GDAL
```

#### 2. 卫星影像下载失败

**问题**：瓦片下载失败或响应超时

**解决方案**：
- 检查网络连接
- 减少线程池大小（在 config.yaml 中设置 `thread_pool_size: 10`）
- 增加请求超时时间（`request_timeout: 60`）
- 尝试更换数据源

#### 3. 坐标顺序错误

**问题**：生成的文件中经纬度颠倒

**解决方案**：
- 确保使用最新版本的代码（已设置坐标轴顺序）
- KML 文件坐标格式应为：经度，纬度，高度
- 检查 GDAL 版本，确保为 3.0+

#### 4. 内存不足

**问题**：处理大区域时内存不足

**解决方案**：
- 减少线程池大小
- 降低缩放级别
- 减小缓冲区大小
- 分批处理多个点

#### 5. 输出文件为空

**问题**：生成的 TIFF 文件为空白

**解决方案**：
- 检查输入文件是否包含有效的点坐标
- 确认坐标范围在有效区域内
- 查看日志中的瓦片下载成功率
- 尝试降低缩放级别

### 日志查看

程序运行时会输出详细的日志信息：
- 点数据读取情况
- 缓冲区生成参数
- 瓦片下载进度
- 错误和警告信息

如遇到问题，请仔细查看日志输出以定位问题。

## 📝 许可证

本项目采用 MIT 许可证。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📧 联系方式

如有问题或建议，请提交 Issue。
