# UI 现代化与用户友好改进设计

- 日期：2026-08-20
- 范围：方案 A（分层渐进改造），不改动业务逻辑与子进程协议
- 默认主题：Tokyo Night（暗/亮配对），支持持久化切换
- 日期控件：tkcalendar 可选依赖（缺失降级为 Entry + placeholder）

## 1. 架构不变性（测试零风险保证）

下列契约**完全保留**，不修改已有 96 个测试的任何代码：

- 子进程启动方式：`python main.py <args>` 通过 `subprocess.Popen(stdout=PIPE, stderr=STDOUT)` 读取行流
- 日志行解析正则：`[i/N]` 进度、`[OK]`/`[FAIL]`/`[PART]` 结果行语义
- `_validate_inputs_single` / `_validate_inputs_batch` 的输入值域（zoom∈[1,20]、buffer∈[50,5000]、坐标范围、日期格式 `YYYY-MM-DD`）
- `cleanup`、`coordinate_loader`、`satellite_processor` 三模块的公共 API

## 2. 主题系统

### 2.1 主题配对表（硬编码 8 组常用，首位默认）

| pair_key     | dark theme            | light theme             |
|--------------|-----------------------|-------------------------|
| tokyo-night  | tokyo-night-dark      | tokyo-night-light       |
| everforest   | everforest-dark       | everforest-light        |
| dracula      | dracula-dark          | dracula-light           |
| catppuccin   | catppuccin-dark       | catppuccin-light        |
| nord         | nord-dark             | nord-light              |
| gruvbox      | gruvbox-dark          | gruvbox-light           |
| vapor        | vapor-dark            | vapor-light             |
| minty        | minty-dark            | minty-light             |

> 当前仅暴露暗/亮两档切换（不做 8 组下拉），避免过度决策；`pair_key` 留作扩展位，默认锁定 `tokyo-night`。

### 2.2 持久化

新增文件 `utils/theme_pref.py`：

```python
# schema: {"theme_pair": "tokyo-night", "mode": "dark" | "light"}
def load_pref() -> dict: ...          # 失败返回 {}，从不抛异常
def save_pref(pref: dict) -> None: ... # 失败静默
def pref_path() -> str: ...            # Windows: %APPDATA%/TiffGetter/theme_pref.json
                                       # Unix:    ~/.config/tiffgetter/theme_pref.json
```

### 2.3 切换流程

`App._apply_theme(mode: Literal["dark","light"])`：
1. `root.withdraw()` 防止闪屏
2. `self.style = tb.Style(theme=对应完整主题名)`（失败捕获 → 回退上一次成功的主题并写日志）
3. `root.configure(bg=style.lookup("TFrame", "background"))`
4. 重新配置：日志 Text bg/fg、Treeview 三态 tag、预览斑马纹 tag（见 §2.4 色表）
5. `self.theme_mode = mode` → `save_pref()`
6. `root.deiconify()`
7. 刷新状态栏右侧「主题：xxx」标签

### 2.4 跟随主题的视觉色表（以 Tokyo Night 为基准，其他主题按命名近似色）

| 组件元素                 | Tokyo Night Dark        | Tokyo Night Light       |
|--------------------------|-------------------------|-------------------------|
| 日志面板 bg              | `#1a1b26`               | `#f5f7ff`               |
| 日志面板 fg（默认）      | `#a9b1d6`               | `#343b58`               |
| 日志 `lvl_info` 标签     | `#7aa2f7`               | `#2e7de9`               |
| 日志 `lvl_warn` 标签     | `#e0af68`               | `#8c6c3e`               |
| 日志 `lvl_err` 标签      | `#f7768e` bold          | `#c64343` bold          |
| 日志 `lvl_ok` 标签       | `#9ece6a`               | `#485e30`               |
| 结果树 `row_success`     | fg `#9ece6a`            | fg `#587539`            |
| 结果树 `row_partial`     | fg `#e0af68`            | fg `#8c6c3e`            |
| 结果树 `row_failed`      | fg `#f7768e`            | fg `#c64343`            |
| 预览树 奇行斑马纹        | bg `#24283b`            | bg `#e8ecf4`            |
| 清理列表 `danger` tag    | 同 `row_failed`         | 同 `row_failed`         |
| 清理列表 `warning` tag   | 同 `row_partial`        | 同 `row_partial`        |

> 实现方式：`_get_theme_colors(theme_name_full) -> dict` 按主题名前缀匹配（匹配失败退回 Tokyo Night 色表），不硬编码 8×N 组合矩阵。

### 2.5 切换器 UI

头部品牌区右侧两个按钮：
- 🌙 暗色：`bootstyle=PRIMARY Outline`，`mode=="dark"` 时去掉 Outline 实心
- ☀️ 亮色：`bootstyle=WARNING Outline`，`mode=="light"` 时实心

## 3. 头部品牌区

布局：`ttk.Frame(header, padding=(12, 8))` 内三部分并排：

1. 左：图标 `ttk.Label(image=self.icon_img, padding=(0, 0, 12, 0))` + 48×48 base64 PNG 卫星剪影（内嵌约 2 KB，启动时 `PhotoImage(data=b64decode(...))`）
2. 中：两行 `ttk.Label` 同列
   - 主标题 16pt bold：`ESRI Wayback 历史影像获取`
   - 副标题 10pt SECONDARY：`批量 · 坐标解析 · GeoTIFF 导出`
3. 右：主题切换器（§2.5）

品牌 Frame 底部分隔线：`ttk.Separator(orient=HORIZONTAL).pack(fill=X, after=header_frame)`

## 4. 三 Tab 改造

### 4.1 Tab 1：单点下载

**A. 粘贴坐标按钮**
- 位置：`"在地图上选点"` 按钮右侧（同一 grid row）
- 实现：`clipboard_get()` → regex `r"^[\s]*([\-0-9.]+)[,\s]+([\-0-9.]+)[\s]*$"` → 成功则 `lat_var.set(x)`，`lon_var.set(y)`；失败静默（不弹窗）

**B. 即时校验 Label**
- 位置：坐标 LabelFrame 底部新 grid row，columnspan=4
- 触发：`lat_var.trace_add('write', _refresh_coord_hint)` + `lon_var.trace_add(...)`
- 三态文字 + bootstyle：
  - 两者均空：`"请填入纬度和经度"`（INFO）
  - 合法：`"✓ 坐标合法"`（SUCCESS）
  - 非法：`"✗ lat 越界 / 非数字"`（DANGER）

**C. 日期控件替换**
- 新增方法 `_date_entry(parent, variable: StringVar) -> Widget`：
  - `try: from tkcalendar import DateEntry` → 返回 `DateEntry(parent, textvariable=variable, date_pattern='y-mm-dd', bootstyle=PRIMARY, width=22)`
  - `except ImportError`: 返回 Entry 带 placeholder（灰色 foreground；`<FocusIn>` 若文本等于 placeholder 则清空并改正常 fg；`<FocusOut>` 若文本为空还原 placeholder + fg=placeholder）
- 与现有 `date_start_var` / `date_end_var` 直接绑定，验证逻辑 (`r'^\d{4}-\d{2}-\d{2}$'`) 不变

### 4.2 Tab 2：批量下载

**A. 统计徽标**
- `预览`按钮右侧 `ttk.Label(bootstyle=INFO Outline, text="待加载")`
- `_preview_coords`：成功 → `text=f"共 {N} 个点"` + bootstyle PRIMARY；失败 → bootstyle DANGER，`text=异常类型`

**B. 模板 CSV 导出按钮**
- 位置：`选择文件 / 预览` 行右侧（grid row=0 column=4）
- 实现：
  1. 写 `%TEMP%/tiffgetter_coord_template.csv`（三列表头 + 两行示例：Tokyo Tower / 天安门）
  2. `os.startfile(os.path.dirname(path))` 或对应 Linux/macOS xdg-open / open
  3. log_msg 写入「已导出模板：path」

**C. 预览斑马纹**
- `_preview_coords` 中插入第 N 条时：
  - `tags=('odd',)` if idx % 2 else `()`
- `preview_tree.tag_configure('odd', background=主题斑马纹色)`（切换主题时重配）

### 4.3 Tab 3：清理与维护

**A. 全选 / 反选按钮**
- 位置：按钮行最右侧，`执行清理`之后追加
  - `self._btn(..."全选", command=_select_all_cleanup, style=INFO Outline)`
  - `self._btn(..."反选", command=_invert_cleanup, style=SECONDARY Outline)`
- 实现：操作 `_cleanup_selects[iid] = True/False` 后调用 `_refresh_cleanup_checkmarks()`

**B. 强化复选框视觉 + 单击切换**
- `_refresh_cleanup_checkmarks()`：遍历所有 iid，values[0] 写入 `☑`（fg SUCCESS bold）或 `□`（fg SECONDARY）
- 新绑定：`cleanup_tree.bind('<Button-1>', _on_cleanup_click)`
  - 若 `identify_column(event.x) == '#1'` → 切换对应 iid 的勾选 + 刷新
- 双击切换保留（`_toggle_cleanup_row` 不变），单双操作同时支持

**C. 扫描统计行**
- `_scan_residuals` 结尾：`total_size = sum(it['size_bytes'] for it in items)`
- `status_var.set(f"发现 {len(items)} 条，共 {format_size(total_size)}")`

## 5. 底部共享区

### 5.1 日志面板彩色分级

**tag 定义**：构造 Text 后即 `log.tag_configure(...)`，切换主题时 `tag_configure` 重配颜色。

**着色时机**：`poll_log_queue` 内每次 `log.insert(END, msg+'\n')` 之后立即调 `_colorize_last_log_line()`，解析本 insert 的最后一行：

```
正则 r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (INFO|WARNING|ERROR) - (.*)'
```
- INFO → tag_add `lvl_info`
- WARNING → tag_add `lvl_warn`
- ERROR → tag_add `lvl_err`
- 叠加：若 msg 含 `[OK]` 或 `[PART] ok` → `lvl_ok`；含 `[FAIL]` → `lvl_err`

### 5.2 日志面板工具栏

位置：`log_frame` 顶部加一行 `ttk.Frame(log_frame)`，`pack(fill=X, pady=(0,2))`

| 控件 | 行为 | bootstyle |
|---|---|---|
| 🗑️ 清空 | `log.delete(1.0, tk.END)` | SECONDARY Outline, ipad=2 |
| 📋 复制选中 | try `clipboard_clear()` + `clipboard_append(log.selection_get())`；except TclError（无选中文本）静默 | SECONDARY Outline, ipad=2 |
| `[pad 扩张]` | spacer `ttk.Frame(...).pack(side=LEFT, fill=X, expand=True)` | — |
| 📜 自动滚动开关 | `ttk.Checkbutton(text="自动滚动", variable=self.auto_scroll_var, bootstyle=SUCCESS Roundtoggle)`；默认 True；`see(END)` 仅 True 时调用 | — |

### 5.3 结果 Treeview 三态徽标 + 行色

`_parse_result_line` 插入时：
- values[1] = `"✅ success"` / `"⚠️ partial"` / `"❌ failed"`
- `tags=('row_success',)` 等对应 tag
- 切换主题时 `result_tree.tag_configure(...)` 重配 fg
- `_open_selected_path` 逻辑不变（仍取 vals[2]）

### 5.4 进度条精细化

- 构造：`ttk.Progressbar(bootstyle=SUCCESS-striped, mode='determinate', maximum=100, value=0)`
- `_on_done`：`_stopping=True` 或解析出失败时→ `bootstyle=WARNING-striped`；正常完成→ `bootstyle=SUCCESS`
- 精细推进：现有 `[i/N]` 解析保留（粗粒度坐标点）；新增在 `_parse_result_line` 中对 `[OK] date` / `[FAIL] date` 的单点模式行做计数，与 `findall(r'\[OK\]|\[FAIL\]', 已输出结果树行数)` 合并估算总体进度 `min(已完成日期数 / 估计总日期数, 99)`。`估计总日期数` 从第一个 `[OK]` / `[FAIL]` 出现前若有「找到 K 个版本」日志行提取 K；否则回退只用 `[i/N]` 粗粒度。失败回退，不崩溃。

### 5.5 状态栏增强

原有 `status_var`（左侧文本）保留。右侧追加：
- `ttk.Label(text="主题：Tokyo Night Dark", bootstyle=SECONDARY Outline, padding=(8,2))`，切换主题时改 `text`

## 6. 错误处理与降级原则（全文件统一）

- 新增按钮回调（粘贴坐标、模板导出、复制选中日志）：全部 `try/except`，异常 `log_msg(...)`，不弹 `messagebox`
- 主题切换：`tb.Style(theme=X)` 失败 → 捕获 `Exception`，写日志 + 退回上一次成功主题
- tkcalendar 缺失：§4.1-C 已定义 Entry+placeholder 回退
- 剪贴板操作（粘贴坐标、复制日志）：`TclError` 静默，不打扰用户

## 7. 文件变更清单

| 文件 | 变更类型 | 预计行数 |
|---|---|---|
| `ui_main.py` | 修改（主要改造目标） | +220 / 改 60 |
| `utils/theme_pref.py` | 新增 | ~45 |
| `environment.yml` | 修改（追加 tkcalendar 可选行注释） | ~+1 |
| `tests/test_unit_theme_pref.py` | 新增（可选） | ~60 |

> 不修改：`main.py` / `satellite_processor.py` / `coordinate_loader.py` / `utils/cleanup.py` / 现有 96 个测试文件。
