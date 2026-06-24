# TiffGetter - ESRI Wayback 历史影像获取工具

单点全历史模式：输入单个坐标，获取该点所有历史时期的卫星影像。

## 核心文件

- `main.py` - 命令行入口
- `ui_main.py` - GUI 界面
- `satellite_processor.py` - 历史影像获取逻辑（WaybackImageFetcher）
- `config.py` / `config.yaml` - 配置

## 数据源

- **ESRI Wayback** - 主要数据源，提供全球历史卫星影像
- 版本列表硬编码在 `satellite_processor.py` 的 `KNOWN_WAYBACK_VERSIONS`

## 工作流程

1. 输入经纬度坐标
2. 获取 ESRI Wayback 可用的历史日期列表
3. 对每个历史日期：
   - 下载对应瓦片
   - 拼接成完整影像
   - 转换为 GeoTIFF

## 配置项

- `zoom`: 缩放级别 (1-20)
- `buffer_size`: 缓冲区大小 (米)
- `thread_pool_size`: 下载线程数