# 项目配置指南

## 1. 环境配置

### 1.1 创建Conda环境

```bash
# 创建新的conda环境
conda create -n satellite-image-processing python=3.13

# 激活环境
conda activate satellite-image-processing
```

### 1.2 安装核心依赖

```bash
# 安装GDAL（地理空间数据处理）
conda install -c conda-forge gdal

# 安装其他核心依赖
pip install requests pillow numpy rasterio pyyaml psutil

# 安装可选依赖（用于现代UI界面）
pip install ttkbootstrap
```

## 2. 项目配置

### 2.1 配置文件设置

项目使用 `config.yaml` 文件进行配置，主要配置项包括：

- **paths**: 输入输出路径配置
- **processing**: 处理参数配置
- **satellite_services**: 卫星影像服务配置
- **wayback_services**: 历史影像服务配置

### 2.2 数据源配置

默认已配置以下卫星数据源：
- ESRI World Imagery
- Google Earth
- Bing Maps
- OpenStreetMap

## 3. 目录结构

```
modular_version/
├── __init__.py          # 包初始化文件
├── buffer_generator.py   # 缓冲区生成模块
├── config.py            # 配置管理模块
├── config.yaml          # 配置文件
├── example_usage.py     # 使用示例
├── point_kml2tif.py     # 主处理脚本
├── point_reader.py      # 点数据读取模块
├── satellite_processor.py # 卫星影像处理模块
├── test_historical_imagery.py # 历史影像测试
├── ui_main.py           # UI界面
└── data/                # 数据目录
    ├── input/           # 输入数据
    └── output/          # 输出数据
```

## 4. 使用方法

### 4.1 命令行使用

```bash
# 基本使用
python point_kml2tif.py --input data/input/test_kml_point_data/变化.kml --output data/output

# 自定义下载模式
python point_kml2tif.py --input data/input/test_kml_point_data/变化.kml --output data/output --mode both

# 指定数据源
python point_kml2tif.py --input data/input/test_kml_point_data/变化.kml --output data/output --service "Google Earth"
```

### 4.2 UI界面使用

```bash
# 启动UI界面
python ui_main.py
```

### 4.3 模块导入使用

```python
from point_reader import read_points
from buffer_generator import generate_buffers
from satellite_processor import SatelliteToTiffConverter

# 1. 读取点数据
points = read_points('data/input/test_kml_point_data/变化.kml')

# 2. 生成缓冲区
shapefile_path, kml_path = generate_buffers(points, 500, 'square_buffers')

# 3. 生成TIFF影像
converter = SatelliteToTiffConverter()
converter.process_kml_to_tiff(kml_path, 'data/output')
```

## 5. 配置选项

### 5.1 主要配置项

| 配置项 | 描述 | 默认值 |
|-------|------|-------|
| thread_pool_size | 线程池大小 | 自动计算（基于系统资源） |
| request_timeout | 请求超时时间（秒） | 30 |
| retry_count | 请求重试次数 | 3 |
| tile_size | 瓦片大小（像素） | 256 |
| default_zoom | 默认缩放级别 | 18 |
| max_zoom | 最大缩放级别 | 19 |
| min_zoom | 最小缩放级别 | 1 |
| download_mode | 下载模式 | current |

### 5.2 数据源配置

| 数据源 | 最大缩放级别 | URL模板 |
|-------|------------|--------|
| ESRI World Imagery | 18 | https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x} |
| Google Earth | 20 | https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z} |
| Bing Maps | 19 | https://t0.tiles.virtualearth.net/tiles/a{quadkey}?g=1 |
| OpenStreetMap | 19 | https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png |

## 6. 故障排除

### 6.1 常见问题

1. **GDAL安装失败**
   - 尝试使用conda-forge通道：`conda install -c conda-forge gdal`
   - 或使用pip：`pip install GDAL`

2. **卫星影像下载失败**
   - 检查网络连接
   - 检查数据源URL是否正确
   - 尝试减少线程池大小

3. **内存不足**
   - 减少线程池大小
   - 处理较小的数据集
   - 增加系统内存

### 6.2 日志查看

- 运行过程中的日志会显示在终端或UI界面的日志窗口中
- 详细的错误信息会帮助诊断问题

## 7. 性能优化

- **线程池大小**：系统会自动根据CPU和内存资源计算最优线程数
- **缓存机制**：临时瓦片会被自动清理，避免磁盘空间占用
- **并发处理**：使用多线程同时下载多个瓦片，提高效率

## 8. 扩展功能

- **添加新数据源**：在 `config.yaml` 中添加新的卫星服务配置
- **自定义处理流程**：通过模块导入方式，可以自定义处理流程
- **批量处理**：可以通过脚本批量处理多个输入文件

## 9. 系统要求

- Python 3.10+
- 至少 4GB 内存
- 50GB 磁盘空间（用于临时文件和输出）
- 稳定的网络连接（用于下载卫星影像）

## 10. 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。