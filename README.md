# TiffGetter - ESRI Wayback 历史影像获取工具

获取单个坐标点的所有历史时期卫星影像（ESRI Wayback 数据源），生成带地理参考的 GeoTIFF/PNG 文件。

## 功能

- 输入单个坐标（经纬度），获取该点所有历史时期的卫星影像
- 数据源自 **ESRI Wayback**，提供全球历史卫星影像
- 支持日期范围筛选
- 可调节缩放级别（1-20）和缓冲区大小
- 多线程并发下载，自动 MD5 去重
- 输出 GeoTIFF（带地理参考）和 PNG 预览
- 提供命令行和图形界面两种使用方式

## 使用方法

### 命令行

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

### GUI

```bash
python ui_main.py
```

图形界面提供完整的参数控制：

| 区域 | 参数 | 说明 |
|------|------|------|
| 坐标 | 纬度、经度 | 目标点坐标 |
| 参数设置 | 缩放级别 (1-20) | 地图瓦片缩放级别 |
| | 缓冲区（米，50-5000） | 下载范围半径 |
| 日期范围 | 起始 / 截止（可选） | 筛选特定时间段的影像 |
| 输出设置 | 输出目录 | 下载文件保存路径 |

界面特点：

- **深色日志面板** — 实时显示下载进度和调试信息
- **状态栏** — 显示当前任务状态（就绪 / 运行中 / 完成 / 已停止）
- **停止按钮** — 支持随时终止正在进行的下载
- **窗口自适应** — 缩放宽高时自动调整布局

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--lat` | 纬度 | 必填 |
| `--lon` | 经度 | 必填 |
| `--zoom` | 缩放级别 (1-20) | 18 |
| `--buffer` | 缓冲区大小（米） | 500 |
| `--output` | 输出目录 | data/output/historical |
| `--date-range` | 日期范围筛选（起始 截止） | 全部 |

## 输出结构

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

每个历史日期包含：
- `*.png` — 卫星影像预览图
- `*.tif` — 带地理参考的 GeoTIFF（CRS: EPSG:4326 WGS84）

## 系统要求

- Python 3.10+
- [GDAL](https://gdal.org/)（用于 GeoTIFF 输出）
- 依赖：`requests`, `pillow`, `numpy`, `rasterio`, `pyyaml`, `psutil`

## 安装

```bash
conda env create -f environment.yml
conda activate satellite-image-processing
```