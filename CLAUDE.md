# TiffGetter - ESRI Wayback 历史影像获取工具

单点 / 批量模式：输入单个坐标或 CSV/SHP 文件，获取这些点所有历史时期的卫星影像。

## 核心文件

- `main.py` - 命令行入口（单点 + 批量，互斥组）
- `ui_main.py` - GUI 界面（三 Tab：单点 / 批量 / 清理）
- `satellite_processor.py` - 历史影像获取逻辑（`WaybackImageFetcher`，含 `fetch_all_historical` / `fetch_batch_historical`）
- `coordinate_loader.py` - CSV / SHP 批量坐标解析（`load_coordinates_file`）
- `utils/cleanup.py` - 残余清理（`scan_residuals` / `cleanup_temp_tiles` / `delete_paths`）
- `config.py` - 配置常量（`THREAD_POOL_SIZE` 与 `WGS84_WKT`）

## 数据源

- **ESRI Wayback** - 主要数据源，提供全球历史卫星影像
- 在线元数据优先；fallback `KNOWN_WAYBACK_VERSIONS` 仅保留 5 条最近 ID（在线 endpoint 不可用时兜底）

## 工作流程

1. 输入经纬度坐标（单点）或 CSV/SHP 文件（批量）
2. 获取 ESRI Wayback 可用的历史日期列表
3. 对每个坐标点 × 每个历史日期：
   - 下载对应瓦片
   - 拼接成完整影像
   - 转换为 GeoTIFF
4. 批量模式：每个坐标点独立子目录，子目录名优先级 `id > name > point_N_lat_lon`

## 配置项

- `zoom`: 缩放级别 (1-20)
- `buffer_size`: 缓冲区大小 (米)
- `thread_pool_size`: 下载线程数
- `coord_concurrency`: 批量模式下坐标并发数（默认 1，避免 ESRI 限流）

## GUI 三 Tab

| Tab | 功能 |
|-----|------|
| 单点下载 | 坐标输入 + 地图选点 + 通用参数 |
| 批量下载 | CSV/SHP 文件选择 + 预览表 + 通用参数 + 结果表 |
| 清理与维护 | 扫描残留（temp_tiles + 历史日期）+ 勾选 + 二次确认删除 |

## 残余清理

- 启动时自动清理根目录 `temp_tiles_*`（`WaybackImageFetcher.__init__`）
- GUI 「清理与维护」Tab 提供可视化勾选清理（temp_tiles + 历史日期子目录）