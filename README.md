# Google Earth 历史影像获取工具

获取单个坐标点的所有历史时期卫星影像，生成带地理参考的 GeoTIFF 文件。

## 功能

- 输入单个坐标（经纬度）
- 自动获取该点所有可用的历史影像日期
- 下载所有历史时期的卫星影像
- 支持日期范围筛选
- 生成带地理参考的 GeoTIFF 文件

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

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--lat` | 纬度 | 必填 |
| `--lon` | 经度 | 必填 |
| `--zoom` | 缩放级别 (1-20) | 18 |
| `--buffer` | 缓冲区大小（米） | 500 |
| `--output` | 输出目录 | data/output/historical |
| `--date-range` | 日期范围筛选 | 全部 |

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

## 系统要求

- Python 3.10+
- GDAL
- 依赖：`requests`, `pillow`, `numpy`, `rasterio`, `pyyaml`, `psutil`

## 安装

```bash
conda env create -f environment.yml
conda activate satellite-image-processing
```