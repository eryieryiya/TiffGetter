# TiffGetter 使用说明书

> 多数据源卫星影像获取工具 — Windows 桌面程序详细使用指南

---

## 目录

1. [程序简介](#1-程序简介)
2. [快速上手](#2-快速上手)
3. [界面总览](#3-界面总览)
4. [Tab 1：单点下载](#4-tab-1单点下载)
5. [Tab 2：批量下载](#5-tab-2批量下载)
6. [Tab 3：清理与维护](#6-tab-3清理与维护)
7. [共享区域：进度条/日志面板/结果表/状态栏](#7-共享区域)
8. [主题切换](#8-主题切换)
9. [命令行模式（CLI）](#9-命令行模式cli)
10. [输出文件结构](#10-输出文件结构)
11. [常见问题](#11-常见问题)

---

## 1. 程序简介

TiffGetter 是一个 Windows 桌面程序（支持 macOS / Linux 开发态），用于从多个在线数据源（**ESRI Wayback、ESRI 当前影像、Google Earth（实验性）、Bing、OpenStreetMap**）自动下载指定坐标点的**历史或当前卫星影像**，并输出**带地理参考的 GeoTIFF 文件**。

**核心特性**

- 数据源选择：GUI 顶部下拉框或 CLI `--source`，默认 ESRI Wayback
- 单点下载：输入一个经纬度，自动获取所选数据源提供的历史或当前影像
- 批量下载：CSV / SHP 文件导入坐标点，依次处理
- 地图选点：内置 OpenStreetMap 地图可视化选点
- 日期范围筛选：只下载指定时间段内的历史版本（仅支持历史的数据源）
- 智能去重：基于 PNG 哈希，自动跳过与之前版本重复的影像（按数据源隔离）；加 `--no-dedup` 可保留每个日期
- 多 Tab 界面：单点 / 批量 / 清理三个独立工作区
- 主题切换：8 套暗色 + 亮色配色（tokyo-night、everforest、dracula、catppuccin、nord、gruvbox、vapor、minty）

**两种运行形态**

| 形态 | 启动方式 | 适用场景 |
|------|---------|---------|
| 独立 exe | 双击 `TiffGetter.exe` | 普通用户，无需 Python 环境 |
| 开发态 | `python ui_main.py` 或 `python main.py --lat ...` | 开发者调试、贡献代码 |

---

## 2. 快速上手

**最快的三步**

1. **打开程序** — 双击 `TiffGetter.exe`（或解压后运行 `dist/TiffGetter.exe`）
2. **输入坐标** — 在"单点下载"Tab，默认已填入东京塔坐标 `(35.6586, 139.7454)`，可直接点击「开始获取」
3. **等待完成** — 日志面板实时显示下载进度，结果表逐条追加。结果文件位于输出目录的日期子文件夹下

**默认输出路径**

默认路径随所选数据源变化：

```
# ESRI Wayback（默认）
data/output/historical/<日期>/<日期>.tif
data/output/historical/<日期>/<日期>.png

# 其它数据源（esri / bing / osm / google）
data/output/<source>/current/current.tif
data/output/<source>/current/current.png
```

例如 `data/output/historical/2024-08-15/2024-08-15.tif`，或 `data/output/esri/current/current.tif`。
每个 release 目录还会写入 `metadata.json`（数据源、版权、范围与参数）。

---

## 3. 界面总览

主界面自上而下分为五大区域：

```
┌─────────────────────────────────────────────────────────┐
│  头部：图标 + 标题 + 副标题              🌙暗色  ☀️亮色  │  ← 主题切换
├─────────────────────────────────────────────────────────┤
│  [单点下载] [批量下载] [清理与维护]                      │  ← Tab 切换
│                                                          │
│                  （当前 Tab 内容）                        │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  结果 Treeview（日期 / 状态 / 路径，双击打开目录）       │
├─────────────────────────────────────────────────────────┤
│  进度: ████████████░░░░░░░░  58%                         │  ← 进度条
├─────────────────────────────────────────────────────────┤
│  日志  🗑️清空  📋复制选中              [✓] 自动滚动       │
│  ┌──────────────────────────────────────────────────┐  │
│  │ [INFO] 找到 196 个版本                             │  │
│  │ [INFO] [1/196] 2026-08-05...                      │  │
│  │ [INFO] 下载 2026-08-05 (ID: 26334)...             │  │
│  └──────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  状态：就绪 / 运行中 / 正在停止 / 完成         主题：...  │  ← 状态栏
└─────────────────────────────────────────────────────────┘
```

**配色**

- 深色为主（默认 `tokyo-night-dark`）
- INFO/WARN/ERROR 三种日志级别颜色：蓝 / 黄 / 红
- 结果行颜色：成功（绿）/ 部分成功（黄）/ 失败（红）

### 3.1 数据源选择

界面头部下方有一条数据源栏，包含「数据源」下拉框、当前版权文本与实验性提示。下拉框由**单点下载**和**批量下载**两个 Tab 共用，子进程启动时会显式传递 `--source`。

| 显示名称 | `--source` | 历史版本 | 最大 zoom | 默认输出目录 | 版权 |
|---|---|---|---|---|---|
| ESRI Wayback | `wayback` | 支持 | 20 | `data/output/historical` | Esri World Imagery Wayback |
| ESRI 当前影像 | `esri` | 不支持 | 18 | `data/output/esri` | Esri World Imagery |
| Google Earth（实验性） | `google` | 支持 | 20 | `data/output/google` | Google |
| Bing 影像 | `bing` | 不支持 | 19 | `data/output/bing` | Microsoft Bing Maps |
| OpenStreetMap | `osm` | 不支持 | 19 | `data/output/osm` | © OpenStreetMap contributors |

切换数据源时联动：

- **日期范围**：不支持历史的数据源会禁用并清空起始/截止日期（单点与批量同时生效）。
- **缩放上限**：缩放控件范围随数据源更新，超限值自动截断（如 OSM 上限 19）。
- **默认输出目录**：用户未手动修改过输出目录时自动跟随数据源；手动修改后不再自动覆盖。
- **版权与实验性提示**：数据源栏与状态栏显示当前数据源及版权；选择 Google Earth 时额外显示「⚠ 实验性数据源，接口可能失效」。
- **批量 Tab**：使用同一数据源，预览表的「坐标来源」列表示 CSV/SHP 文件名，与数据源无关。

---

## 4. Tab 1：单点下载

输入一个坐标点 → 下载该点在所选数据源下的历史或当前影像。

### 4.1 坐标区

| 控件 | 说明 |
|------|------|
| **纬度输入框** | 输入 `-90 ~ 90` 范围的浮点数，例如 `35.6586` |
| **经度输入框** | 输入 `-180 ~ 180` 范围的浮点数，例如 `139.7454` |
| **🗺️ 在地图上选点** | 弹出 OpenStreetMap 地图窗口，左键单击设置标记，确认后回写到经纬度 |
| **📋 粘贴坐标** | 从剪贴板读取 `"lat, lon"` 格式文本并自动填入 |
| **即时校验提示** | 输入合法时显示 ✓ 坐标合法（绿色），非法时显示 ✗ 错误原因（红色） |

**粘贴坐标格式支持**

```
35.6586, 139.7454
35.6586,139.7454
35.6586 139.7454
```

### 4.2 参数设置

| 参数 | 范围 | 默认 | 说明 |
|------|------|------|------|
| 缩放级别 | 1-20（随数据源上限） | 18 | 地图瓦片层级。18 ≈ 0.6 米/像素；19 ≈ 0.3 米/像素。数值越大越清晰但下载量越大；超过当前数据源上限会被截断（esri 18、bing/osm 19、wayback/google 20） |
| 缓冲区 (米) | 50-5000 | 500 | 以输入点为中心，向外扩展的正方形范围半径。建议：建筑 200-500，街区 500-1000，城市 2000-5000 |

### 4.3 日期范围（可选）

| 字段 | 格式 | 说明 |
|------|------|------|
| 起始 | YYYY-MM-DD | 留空表示不限制起始日期 |
| 截止 | YYYY-MM-DD | 留空表示不限制截止日期 |

- 仅**支持历史版本**的数据源（`wayback`、`google`）可用；`esri` / `bing` / `osm` 会禁用并清空日期输入。
- 留空两者 → 获取该数据源提供的所有版本（非历史源只有一个 `current`）
- 同时填写 → 仅获取 `[起始, 截止]` 区间内的版本
- `tkcalendar` 可用时显示日历下拉控件，否则显示占位符输入框
- 占位符 `YYYY-MM-DD` 视为空（不算填写）

### 4.4 输出设置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 输出目录 | 随数据源：wayback → `data/output/historical`，其它 → `data/output/<source>` | 在该目录下按 release 创建子文件夹（历史源为日期，其它为 `current`）；手动修改后不再自动跟随数据源 |
| 浏览 | — | 弹出文件夹选择对话框 |

### 4.5 控制按钮

| 按钮 | 状态 | 行为 |
|------|------|------|
| **开始获取**（绿） | 输入合法时启用 | 启动 CLI 子进程下载，实时回传日志 |
| **停止**（红） | 运行时启用 | 发送 `CTRL_BREAK_EVENT` 信号，子进程优雅退出 |

---

## 5. Tab 2：批量下载

从 CSV / SHP 文件导入多个坐标点，依次下载每个点在当前数据源下的历史或当前影像。

### 5.1 坐标文件

**支持格式**

- CSV（UTF-8 / UTF-8 with BOM / GBK 自动识别；逗号 / 分号 / Tab 分隔）
- SHP（ESRI Shapefile，含 `.shp`、`.shx`、`.dbf` 同目录）

**CSV 表头要求**

```csv
name,lat,lon
Tokyo Tower,35.6586,139.7454
Tiananmen,39.9042,116.4074
```

- `lat`、`lon` **必填**（不区分大小写，也接受 `latitude`/`longitude`、`y`/`x`）
- `name` / `id` 可选，用于在输出目录命名子文件夹

**SHP 要求**

- 几何类型必须为 `Point`（不支持 Polygon / Line）
- `.shp` / `.shx` / `.dbf` 必须在同一目录

**控件**

| 控件 | 说明 |
|------|------|
| **文件路径输入框** | 显示/编辑文件绝对路径 |
| **选择文件** | 弹出文件选择对话框 |
| **预览** | 解析文件并填入下方预览表（最多 100 行） |
| **徽标** | 显示"待加载" / "共 N 个点" / "解析失败"等状态 |
| **📄 导出 CSV 模板** | 在系统临时目录生成示例 CSV，并打开所在文件夹 |

### 5.2 通用参数

与单点 Tab 类似：**缩放级别 / 缓冲区 / 起始日期 / 截止日期**，但作用于**所有批量点**，且与单点 Tab 共用同一个数据源。非历史数据源的日期输入同样被禁用。

### 5.3 输出设置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 输出根目录 | 随数据源：wayback → `data/output/batch`，其它 → `data/output/<source>` | 每个坐标点会在该目录下生成一个子目录 |
| 并发数 | 1（范围 1-16） | 同时处理的坐标点数。**默认 1 是为了避免触发服务端限流** |

**子目录命名规则**

```
<输出根目录>/<name 或 id>/<日期>/<日期>.tif      # 历史源
<输出根目录>/<name 或 id>/<日期>/<日期>.png
<输出根目录>/<name 或 id>/current/current.tif    # 非历史源
<输出根目录>/<name 或 id>/current/current.png
```

每个 release 目录同样包含 `metadata.json`。

### 5.4 坐标点预览表

解析后显示前 100 个点，列：

- **名称 / ID** — 来自 `name` 或 `id` 列
- **纬度** — 6 位小数
- **经度** — 6 位小数
- **坐标来源** — 文件名（CSV / SHP），用于与「数据源」区分

### 5.5 控制按钮

- **开始批量下载**（绿）— 启动批量处理，状态栏显示「批量下载中...」

---

## 6. Tab 3：清理与维护

清理临时瓦片目录与各数据源的 release 目录，释放磁盘空间。

### 6.1 操作按钮

| 按钮 | 行为 |
|------|------|
| **扫描残留**（蓝） | 扫描项目根目录下的 `temp_tiles_*` 临时目录 + `data/output` 下所有数据源与批量输出的 release 目录 |
| **仅清临时瓦片**（黄） | 不扫描直接清理所有 `temp_tiles_*`（需二次确认） |
| **执行清理（按勾选）**（红） | 删除扫描结果中已勾选的项（需二次确认） |
| **全选** | 勾选所有扫描条目 |
| **反选** | 反转当前勾选状态 |

### 6.2 清理列表

扫描后填充，列：

- **勾选** — 单击切换 ☑/□（仅勾选列响应单击）
- **类型** — `historical_date`（红，含所有数据源的 release 目录）/ `temp_tiles`（黄）
- **大小** — 人类可读（KB / MB / GB）
- **修改时间** — `YYYY-MM-DD HH:MM:SS`
- **路径** — 完整目录路径

扫描范围说明：

- 覆盖 `data/output` 下的 `wayback` 历史目录、`esri` / `bing` / `osm` / `google` 的 `current` 目录，以及批量坐标子目录下的 release。
- 仅识别包含 `metadata.json` 或同名 PNG 的 release 目录，命中后不再深入其子目录。
- 不扫描 `data/input`；扫描函数只读，删除需用户勾选并二次确认。

### 6.3 二次确认

执行清理时会弹出：

```
将永久删除 N 个目录：
  - <path 1>
  - <path 2>
  ...
确认？
```

点击「是」才真正删除，删除完成后自动重新扫描。

---

## 7. 共享区域

### 7.1 进度条

- 样式：SUCCESS-striped 进度条
- 驱动方式：解析日志中的 `[i/N]` 标记自动推进
- 启动 → 显示 `[1/N]` 起始位置；完成 → 100%

### 7.2 日志面板

**工具栏**

- **🗑️ 清空** — 一键清空所有日志
- **📋 复制选中** — 复制选中区域到剪贴板
- **[✓] 自动滚动** — 默认勾选，新日志自动滚到底部

**日志级别颜色**

| 级别 | 颜色 |
|------|------|
| INFO | 蓝色 |
| WARNING | 黄色 |
| ERROR | 红色（粗体） |
| `[OK]` 行 | 绿色 |
| `[FAIL]` 行 | 红色 |

**关键日志格式**

```
[INFO] 查询坐标 (35.6586, 139.7454) 的可用历史影像...
[INFO] 在线元数据返回 196 个 release
[INFO] 找到 196 个版本
[INFO] [1/196] 2026-08-05...
[INFO] 下载 2026-08-05 (ID: 26334)...
[INFO] 成功: data/output/historical/2026-08-05/2026-08-05.tif
[INFO] 完成！成功 156/196 个
```

### 7.3 结果表

| 列 | 说明 |
|----|------|
| 日期 / 名称 | 单点模式：日期；批量模式：坐标名称 |
| 状态 | ✅ success / ⚠️ partial / ❌ failed / 🔁 duplicate |
| 路径 | 文件完整路径（批量模式下显示 `lat,lon 成功 X/Y`） |

**双击行**：在文件资源管理器中打开路径所在目录。

### 7.4 状态栏

显示当前状态：

- **就绪** — 启动后空闲
- **运行中...** — 子进程运行中
- **正在停止...** — 已发送停止信号，等待子进程退出
- **完成** — 全部任务成功完成
- **已停止** — 用户主动停止
- **清理中... / 清理完成（N 成功 / M 失败）** — 清理 Tab 状态

右下角显示当前主题（如「主题：tokyo-night-dark」）。

---

## 8. 主题切换

头部右上角两个按钮：

- **🌙 暗色** — 当前亮色模式时为实心，激活后切换到深色主题
- **☀️ 亮色** — 当前暗色模式时为实心，激活后切换到亮色主题

**8 套预设主题**（在 `THEME_PAIRS` 中定义）

| 主题键 | 暗色 | 亮色 |
|--------|------|------|
| `tokyo-night`（默认）| tokyo-night-dark | tokyo-night-light |
| `everforest` | everforest-dark | everforest-light |
| `dracula` | dracula-dark | dracula-light |
| `catppuccin` | catppuccin-dark | catppuccin-light |
| `nord` | nord-dark | nord-light |
| `gruvbox` | gruvbox-dark | gruvbox-light |
| `vapor` | vapor-dark | vapor-light |
| `minty` | minty-dark | minty-light |

主题偏好通过 `utils.theme_pref` 保存，下次启动自动恢复。

**注意事项**

- `tkcalendar` 的 Calendar 组件与主题切换存在已知兼容问题，切换时可能出现 AttributeError 警告但不影响功能
- 日志面板颜色、结果树颜色、清理树颜色会自动随主题重新着色

---

## 9. 命令行模式（CLI）

虽然使用说明书聚焦 GUI，TiffGetter.exe 也支持命令行模式（用于脚本批处理、CI/CD）：

```bash
# 完整路径（默认 wayback 历史影像）
TiffGetter.exe --lat 35.6586 --lon 139.7454

# 指定数据源：ESRI 当前影像
TiffGetter.exe --lat 35.6586 --lon 139.7454 --source esri

# 指定数据源：OpenStreetMap
TiffGetter.exe --lat 35.6586 --lon 139.7454 --source osm --zoom 18

# 指定参数
TiffGetter.exe --lat 35.6586 --lon 139.7454 --zoom 18 --buffer 500 --output data/output/tokyo

# 日期范围（仅 wayback / google 支持）
TiffGetter.exe --lat 35.6586 --lon 139.7454 --date-range 2020-01-01 2024-12-31

# 批量下载（所有坐标共用 bing 数据源）
TiffGetter.exe --coords-file points.csv --source bing --coord-concurrency 2

# 帮助
TiffGetter.exe --help
```

**所有参数**

| 参数 | 说明 |
|------|------|
| `--lat LAT` | 纬度（单点模式，必填，与 --lon 同时使用） |
| `--lon LON` | 经度（单点模式，必填，与 --lat 同时使用） |
| `--coords-file PATH` | 批量坐标文件（CSV / SHP），与 --lat/--lon 互斥 |
| `--source` | 数据源：`wayback`（默认）/ `esri` / `google` / `bing` / `osm` |
| `--zoom` | 缩放级别 1-20（默认 18，按数据源上限截断） |
| `--output` | 输出目录（默认 wayback → `data/output/historical`，其它 → `data/output/<source>`；显式指定后不再追加层级） |
| `--buffer` | 缓冲区大小（米，50-5000，默认 500） |
| `--date-range START END` | 日期范围筛选，如 `2020-01-01 2024-12-31`（非历史源不可用，退出码 2） |
| `--coord-concurrency N` | 批量模式并发数 1-16（默认 1） |
| `--no-dedup` | 关闭重复检测，每个历史日期都单独输出（默认去重） |

---

## 10. 输出文件结构

### 单点模式

```
# wayback（默认）
data/output/historical/
├── 2026-08-05/
│   ├── 2026-08-05.png    ← 拼接后的预览图
│   ├── 2026-08-05.tif    ← 带地理参考的 GeoTIFF
│   └── metadata.json
└── ...

# 其它数据源（esri / bing / osm / google）
data/output/<source>/
└── current/
    ├── current.png
    ├── current.tif
    └── metadata.json
```

显式指定输出目录（GUI 浏览或 CLI `--output`）时，严格写入该目录，不再自动追加数据源或 `current` 层级，但仍按 release 建立子目录（日期或 `current`）。

### 批量模式

```
data/output/batch/                  # wayback 默认；其它源为 data/output/<source>
├── Tokyo Tower/                    # id 优先；否则 name；否则 point_N_lat_lon
│   ├── 2026-08-05/
│   │   ├── 2026-08-05.png
│   │   ├── 2026-08-05.tif
│   │   └── metadata.json
│   └── ...
├── current/                        # 非历史源
│   ├── current.png
│   ├── current.tif
│   └── metadata.json
└── ...
```

### metadata.json 字段

每个 release 目录均有 `metadata.json`，用于记录来源与参数，并作为去重按数据源隔离的依据：

| 字段 | 说明 |
|------|------|
| `source` | 数据源名称（wayback / esri / google / bing / osm） |
| `release_id` / `release_date` | 版本 ID 与日期；非历史源均为 `current` |
| `attribution` | 版权归属文本 |
| `lat` / `lon` | 采集坐标 |
| `zoom` / `buffer` | 缩放级别与缓冲区（米） |
| `bounds` | 输出影像的 WGS84 边界（min_lon/min_lat/max_lon/max_lat） |
| `created_at` | 采集时间（ISO 8601，含时区） |
| `files` | `png` / `tif` 文件名（GeoTIFF 失败时 `tif` 为 `null`） |

### 去重规则

- 仅在同一数据源内比较 MD5、dHash 与中心瓦片预筛结果，同一地点用不同数据源下载会各自保留。
- 缺少 `metadata.json` 的旧输出按 `wayback` 处理。
- 同一视觉组保留最早日期：按日期升序处理，后续相同影像标记为 `duplicate`。
- 指定日期范围时，去重只与区间内的已有输出比较，避免区间外影像让区间内最早日期被跳过；结束时打印 `[区间校验] 区间内最早保留影像日期: ...`。
- 结果状态：`success` / `existing` / `duplicate` / `failed` / `unsupported`。
- 加 `--no-dedup` 关闭上述检测，每个历史日期都会单独下载并输出。

### GeoTIFF 文件

- **格式**：TIFF + LZW 压缩
- **坐标系**：WGS84 (EPSG:4326)
- **波段**：3 波段 RGB
- **地理范围**：根据 `buffer` 参数自动计算

---

## 11. 常见问题

### Q1：启动后看不到 GUI 窗口？

- **macOS / Linux 开发态**：GUI 需要 X11 转发，使用 `ssh -X` 连接或在本机运行
- **Windows exe**：检查是否被安全软件拦截；尝试以管理员身份运行
- **依赖缺失**：打包后的 exe 应自带所有依赖；如提示 `tkintermapview` 缺失，"地图选点"按钮会被禁用，其他功能正常

### Q2：下载很慢或频繁失败？

- **降低并发**：批量模式并发数改为 1
- **缩小缓冲区**：5000m → 500m，瓦片数从 ~50 减到 ~5
- **降低缩放级别**：18 → 17 或 16
- **网络问题**：检查代理 / 防火墙是否允许访问对应数据源域名：`*.arcgisonline.com` / `*.maptiles.arcgis.com`（ESRI）、`*.virtualearth.net`（Bing）、`*.tile.openstreetmap.org`（OSM）、Google Earth 相关端点

### Q3：某个日期版本下载失败？

部分历史版本可能因瓦片数据缺失而无法下载，这是所选数据源服务的常见现象，程序会标记该日期为「失败」并继续下载其他日期，不会中断整体流程。

### Q4：某些日期明明在 ESRI 网站上能看到，但下载结果是「重复」？

ESRI、Google 等数据源经常在多个日期 ID 上发布相同瓦片数据，程序通过 PNG 哈希自动去重，避免重复下载占用空间。被标记「重复」的日期是真正无差异的版本，并非下载失败。去重仅在**同一数据源内**生效，不同数据源下载的同一地点不会被判为重复。若需要每个日期都有独立目录，使用 `--no-dedup`。

### Q5：GUI 卡顿？

- 日志面板可能积累大量历史日志：点击「🗑️ 清空」
- 自动滚动开关开启时会持续滚动：调试时可关闭
- 极大批量任务建议用 CLI 模式（`--coords-file` + `nohup` 后台跑）

### Q6：如何查看程序的输出日志？

- GUI 中：「日志」面板实时显示
- CLI 中：stdout 直接输出到终端
- 磁盘：临时瓦片目录（`temp_tiles_*`）可保留作为断点续传依据

### Q7：如何彻底重置？

```powershell
# 删除所有临时与各数据源输出
Remove-Item -Recurse -Force temp_tiles_*
Remove-Item -Recurse -Force data\output
```

或在 GUI「清理与维护」Tab 扫描后全选执行清理。

### Q8：批量文件解析失败？

- CSV：BOM 头 / 编码 / 分隔符自动识别，但表头必须含 `lat` 和 `lon`
- SHP：必须是 Point 类型，且 `.shp` / `.shx` / `.dbf` 同目录
- 失败时「预览」按钮会弹出详细错误（含 hint 提示）

### Q9：不同数据源有什么区别与使用限制？

| 数据源 | 历史 | 最大 zoom | 并发 | 使用限制 |
|---|---|---|---|---|
| ESRI Wayback | 支持 | 20 | 10 | 版权 Esri World Imagery Wayback |
| ESRI 当前影像 | 不支持 | 18 | 8 | 版权 Esri World Imagery |
| Google Earth | 支持（实验性） | 20 | 4 | 接口可能随时失效；批量前自行确认 Google 服务条款 |
| Bing 影像 | 不支持 | 19 | 4 | 批量前自行确认 Microsoft Bing Maps 条款 |
| OpenStreetMap | 不支持 | 19 | 2 | 需注明 © OpenStreetMap contributors；并发固定 2，请勿高频抓取 |

选择非历史数据源时日期范围不可用，且输出目录为 `data/output/<source>/current/`。数据源版权会写入 `metadata.json`。

---

## 附录：常用快捷操作

| 操作 | 快捷键 |
|------|--------|
| 粘贴坐标（单点 Tab） | 先复制 `"lat, lon"`，再点击「📋 粘贴坐标」 |
| 打开结果目录 | 在结果表中双击对应行 |
| 切换主题 | 点击头部 🌙/☀️ 按钮 |
| 停止运行 | 点击「停止」按钮（红色） |

---

## 反馈与支持

- 项目仓库：https://github.com/eryieryiya/TiffGetter
- 提交问题：在仓库 Issues 区反馈（附 GUI 日志面板截图与 `python -V` / `python -c "import rasterio; print(rasterio.__version__)"` 输出）