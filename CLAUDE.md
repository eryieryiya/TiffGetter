# TiffGetter - 多数据源卫星影像获取工具

单点 / 批量模式：输入单个坐标或 CSV/SHP 文件，从所选数据源获取历史或当前卫星影像。

## 核心文件

- `main.py` - 命令行入口（单点 + 批量，互斥组；`--source` 选择数据源）
- `ui_main.py` - GUI 界面（顶部数据源下拉框 + 三 Tab：单点 / 批量 / 清理）
- `satellite_processor.py` - 统一下载管线 `ImageFetcher`（`fetch_all` / `fetch_batch`），含瓦片坐标、并发下载、拼接、裁剪、GeoTIFF、去重与 `metadata.json` 写入
- `providers/` - 数据源包：
  - `base.py` - `SourceInfo` / `TileSource` 接口与 `build_session`
  - `xyz.py` - XYZ 瓦片下载模板方法（`XYZSource`）
  - `wayback.py` / `esri_current.py` / `bing.py` / `osm.py` - 各数据源实现
  - `google_earth.py` / `google_earth_client.py` - Google Earth Adapter（实验性）
  - `registry.py` - 数据源注册表（简单工厂），集中维护名称、缩放、并发、版权
- `coordinate_loader.py` - CSV / SHP 批量坐标解析（`load_coordinates_file`）
- `utils/cleanup.py` - 残余清理（`scan_residuals` / `cleanup_temp_tiles` / `delete_paths`）
- `config.py` - 配置常量（`THREAD_POOL_SIZE` 与 `WGS84_WKT`）
- `TiffGetter.spec` - PyInstaller 打包配置（providers 动态导入需 hiddenimports）

## 数据源

| source | 名称 | 历史 | 最大 zoom | 并发 | 版权 |
|---|---|---|---|---|---|
| `wayback`（默认） | ESRI Wayback | 支持 | 20 | 10 | Esri World Imagery Wayback |
| `esri` | ESRI 当前影像 | 不支持 | 18 | 8 | Esri World Imagery |
| `google` | Google Earth（实验性） | 支持 | 20 | 4 | Google |
| `bing` | Bing 影像 | 不支持 | 19 | 4 | Microsoft Bing Maps |
| `osm` | OpenStreetMap | 不支持 | 19 | 2 | © OpenStreetMap contributors |

- 数据源能力集中在 `providers/registry.py` 的 `_SOURCES`，工厂映射在 `_FACTORIES`（`模块:类名` 字符串，惰性 `importlib` 导入）。
- 非历史数据源的 `available_releases` 只返回一个 `id=current`、`date=current` 的 release。
- `ImageFetcher` 的线程池大小为 `min(THREAD_POOL_SIZE, info.max_concurrency)`。

## 数据源扩展方式

1. 在 `providers/registry.py` 的 `_SOURCES` 增加 `SourceInfo`（名称、显示名、是否历史、缩放范围、并发上限、版权、`experimental`）。
2. 在 `_FACTORIES` 增加 `'<name>': 'providers.<module>:<ClassName>'` 映射。
3. 新增 Provider 类：继承 `XYZSource`（实现 `build_url`，必要时覆写 `headers`）或直接继承 `TileSource`（实现 `available_releases` / `fetch_tile`）。
4. CLI `--source` 与 GUI 下拉框会自动出现，下载管线无需修改。
5. 若是新模块，需在 `TiffGetter.spec` 的 `hiddenimports` 中补上模块名（PyInstaller 无法静态发现字符串映射的动态导入）。

## 工作流程

1. 输入经纬度坐标（单点）或 CSV/SHP 文件（批量）
2. 通过 Registry 创建所选数据源，获取可用 release 列表
3. 对每个坐标点 × 每个 release：
   - 下载对应瓦片（受数据源并发上限约束）
   - 拼接成完整影像
   - 转换为 GeoTIFF
4. 批量模式：每个坐标点独立子目录，子目录名优先级 `id > name > point_N_lat_lon`

## 输出路径

- 未显式指定输出目录时：
  - `wayback` → `data/output/historical/<date>/<date>.png|tif`
  - 其它数据源 → `data/output/<source>/<current|date>/<current|date>.png|tif`
- 显式传入 `--output` 时严格使用该目录，不再追加数据源层级。
- 每个 release 目录写入 `metadata.json`：`source`、`release_id`、`release_date`、`attribution`、`lat`、`lon`、`zoom`、`buffer`、`bounds`、`created_at`、`files`。
- 去重索引按数据源隔离：只与 `metadata.json` 中 `source` 相同的已有输出比较；缺少 `metadata.json` 的旧文件按 `wayback` 处理。

## 配置项

- `zoom`: 缩放级别 (1-20，按数据源上限截断)
- `buffer_size`: 缓冲区大小 (米)
- `thread_pool_size`: 下载线程数（再受数据源 `max_concurrency` 限制）
- `coord_concurrency`: 批量模式下坐标并发数（默认 1，避免服务端限流）

## GUI 三 Tab

| Tab | 功能 |
|-----|------|
| 单点下载 | 坐标输入 + 地图选点 + 通用参数 |
| 批量下载 | CSV/SHP 文件选择 + 预览表 + 通用参数 + 结果表 |
| 清理与维护 | 扫描残留（temp_tiles + 所有数据源 release）+ 勾选 + 二次确认删除 |

## 残余清理

- 启动时自动清理根目录 `temp_tiles_*`（`ImageFetcher.__init__`）
- GUI 「清理与维护」Tab 扫描 `data/output` 下所有数据源与批量结构的 release 目录（包含 `metadata.json` 或同名 PNG），不扫描 `data/input`
