"""
coordinate_loader.py - 批量下载坐标点解析模块

支持两种格式：
- CSV：表头至少含 lat,lon（可选 name,id）；UTF-8（含 BOM 自动处理）；分隔符自动识别。
- SHP：Point 直接取 (x, y)；Polygon / MultiPolygon 取 centroid；
       若 CRS 非 EPSG:4326，使用 pyproj 转换；取第一个非几何字符串字段作为 name。

统一入口：load_coordinates_file(path)
返回统一格式字典列表：
    {
        "lat": float,
        "lon": float,
        "name": str,         # 子目录命名（清洗后）
        "id": str,           # 优先于 name 用于命名
        "source": str,       # "csv" / "shp"
        "source_row": int,   # CSV 行号或 SHP 要素索引
    }
"""
from __future__ import annotations

import csv
import os
import re
import sys
from typing import Dict, List, Optional


# Windows 文件名非法字符 + 控制字符
_INVALID_NAME_CHARS = re.compile(r'[\\/:\*\?"<>\|\x00-\x1f]')


class CoordinateLoadError(Exception):
    """坐标文件加载失败。"""

    def __init__(self, message: str, path: str = "", hint: str = ""):
        self.path = path
        self.hint = hint
        super().__init__(message)


def _safe_name(raw: Optional[str], fallback: str) -> str:
    """清洗为安全的子目录名。"""
    if raw is None:
        return fallback
    s = str(raw).strip()
    if not s:
        return fallback
    s = _INVALID_NAME_CHARS.sub("_", s)
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("._")
    if not s:
        return fallback
    if len(s) > 64:
        s = s[:64].rstrip("._")
    return s


# ----------------------------------------------------------------------
# CSV
# ----------------------------------------------------------------------
def _detect_dialect(sample: str) -> csv.Dialect:
    """从样本检测分隔符。优先 ; , \\t。"""
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return sniffed
    except csv.Error:
        # 回退到逗号
        class _Default(csv.excel):
            delimiter = ","

        return _Default()


def load_coordinates(csv_path: str) -> List[Dict]:
    """读取 CSV，返回坐标字典列表。

    要求：表头至少含 lat,lon（大小写不敏感、忽略前后空格）。
    可选列：name, id。
    """
    if not os.path.exists(csv_path):
        raise CoordinateLoadError(f"CSV 文件不存在: {csv_path}", csv_path)

    # UTF-8 BOM 处理
    with open(csv_path, "rb") as f:
        raw = f.read(8192)

    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise CoordinateLoadError(
            f"无法识别 CSV 编码: {csv_path}", csv_path, hint="请保存为 UTF-8"
        )

    sample = text[:4096]
    try:
        dialect = _detect_dialect(sample)
    except Exception:
        dialect = csv.excel

    coords: List[Dict] = []
    reader = csv.reader(text.splitlines(), dialect=dialect)
    try:
        header = next(reader)
    except StopIteration:
        raise CoordinateLoadError(f"CSV 为空: {csv_path}", csv_path)

    norm_header = [h.strip().lower() for h in header]
    try:
        lat_idx = norm_header.index("lat")
        lon_idx = norm_header.index("lon")
    except ValueError:
        raise CoordinateLoadError(
            f"CSV 表头缺少 lat 或 lon 列: {header}", csv_path,
            hint="表头需含 'lat' 与 'lon'，大小写不限"
        )

    name_idx = norm_header.index("name") if "name" in norm_header else None
    id_idx = norm_header.index("id") if "id" in norm_header else None

    for row_no, row in enumerate(reader, start=2):  # 第 2 行起为数据
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) <= max(lat_idx, lon_idx):
            raise CoordinateLoadError(
                f"第 {row_no} 行列数不足: {row}", csv_path
            )
        try:
            lat = float(row[lat_idx].strip())
            lon = float(row[lon_idx].strip())
        except ValueError as e:
            raise CoordinateLoadError(
                f"第 {row_no} 行 lat/lon 无法解析: {row}", csv_path, hint=str(e)
            )
        if not (-90.0 <= lat <= 90.0):
            raise CoordinateLoadError(
                f"第 {row_no} 行 lat 越界 {lat}", csv_path
            )
        if not (-180.0 <= lon <= 180.0):
            raise CoordinateLoadError(
                f"第 {row_no} 行 lon 越界 {lon}", csv_path
            )

        raw_id = row[id_idx].strip() if id_idx is not None and id_idx < len(row) else ""
        raw_name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else ""
        # raw_id/raw_name 已 strip，非空才清洗（空字符串避免无谓的清洗路径）
        safe_id = _safe_name(raw_id, "") if raw_id else ""
        safe_name = _safe_name(raw_name, "") if raw_name else ""

        coords.append({
            "lat": lat,
            "lon": lon,
            "name": safe_name,
            "id": safe_id,
            "source": "csv",
            "source_row": row_no - 1,
        })

    if not coords:
        raise CoordinateLoadError(f"CSV 无有效数据行: {csv_path}", csv_path)

    return coords


# ----------------------------------------------------------------------
# SHP
# ----------------------------------------------------------------------
def load_coordinates_shp(shp_path: str) -> List[Dict]:
    """读取 SHP（Point/Polygon），取 centroid，返回坐标列表。

    依赖：pyshp（shapefile） + pyproj（CRS 转换）。
    """
    if not os.path.exists(shp_path):
        raise CoordinateLoadError(f"SHP 文件不存在: {shp_path}", shp_path)

    try:
        import shapefile  # pyshp
    except ImportError:
        raise CoordinateLoadError(
            "缺少依赖 pyshp", shp_path, hint="请运行 pip install pyshp"
        )

    try:
        from pyproj import Transformer, CRS as PJCRS
    except ImportError:
        raise CoordinateLoadError(
            "缺少依赖 pyproj", shp_path, hint="请运行 pip install pyproj"
        )

    try:
        reader = shapefile.Reader(shp_path)
    except Exception as e:
        raise CoordinateLoadError(f"SHP 打开失败: {e}", shp_path)

    # 字段名：跳过几何删除字段（pyshp 中 Geometry 字段不会出现在 fields[1:]）
    fields = [f[0] for f in reader.fields[1:]]  # 第一个是 (b"DeletionFlag", ...)
    name_field = None
    for f in fields:
        # 优先取名为 name / id / NAME / ID 的字段
        fl = f.lower()
        if fl in ("name", "id", "name_zh", "名称"):
            name_field = f
            break
    if name_field is None and fields:
        # 退化到第一个字符串型字段
        for f_name, f_type, *_ in reader.fields[1:]:
            if f_type in ("C",):  # Character
                name_field = f_name
                break

    # CRS：通过 .prj 读取
    prj_path = os.path.splitext(shp_path)[0] + ".prj"
    transformer = None
    crs_label = "EPSG:4326 (假定)"
    if os.path.exists(prj_path):
        try:
            with open(prj_path, "r", encoding="utf-8", errors="ignore") as f:
                wkt = f.read()
            src_crs = PJCRS.from_wkt(wkt)
            if src_crs.to_epsg() != 4326:
                transformer = Transformer.from_crs(src_crs, 4326, always_xy=True)
                crs_label = f"EPSG:{src_crs.to_epsg()} → EPSG:4326"
            else:
                crs_label = "EPSG:4326"
        except Exception:
            transformer = None
            crs_label = "未知（按 EPSG:4326 处理）"

    coords: List[Dict] = []
    shapes = list(reader.iterShapes())
    records = list(reader.iterRecords())

    for idx, (shape, record) in enumerate(zip(shapes, records), start=1):
        if shape.shapeType is None:
            continue
        geom_type = shape.shapeTypeName  # e.g. "POINT", "POLYGON"

        lon, lat = None, None
        if geom_type == "POINT":
            lon, lat = shape.points[0]
        elif geom_type in ("POLYGON", "POLYGONZ", "POLYGONM", "MULTIPOLYGON"):
            # centroid：pyshp 在 polygon 闭合时会重复首尾点；
            # 用 bbox 中点更稳健（避免首个顶点被重复计算拉偏中心）
            try:
                # shapefile Reader 不直接给 bbox，shape.bbox 返回 [xmin, ymin, xmax, ymax]
                bbox = getattr(shape, 'bbox', None)
                if bbox and len(bbox) >= 4:
                    lon = (bbox[0] + bbox[2]) / 2.0
                    lat = (bbox[1] + bbox[3]) / 2.0
                else:
                    raise AttributeError
            except (AttributeError, TypeError, IndexError):
                xs, ys = [], []
                for pt in shape.points:
                    xs.append(pt[0])
                    ys.append(pt[1])
                if xs:
                    lon = sum(xs) / len(xs)
                    lat = sum(ys) / len(ys)
        else:
            # 其他类型（LINESTRING 等）跳过
            continue

        if lon is None or lat is None:
            continue

        if transformer is not None:
            lon, lat = transformer.transform(lon, lat)

        # 字段值
        name_value = ""
        if name_field and record is not None:
            try:
                fname_idx = fields.index(name_field)
                name_value = str(record[fname_idx]).strip()
            except Exception:
                name_value = ""

        fb = f"feature_{idx}"
        # SHP 默认不暴露 id 字段；后续按需回填到 feature_N
        safe_id = ""
        safe_name = _safe_name(name_value, fb)
        # 若 name 是 feature_X，额外把 id 设为 idx 以便复用
        if safe_name == fb:
            safe_id = str(idx)

        coords.append({
            "lat": float(lat),
            "lon": float(lon),
            "name": safe_name,
            "id": safe_id,
            "source": "shp",
            "source_row": idx,
        })

    reader.close()

    if not coords:
        raise CoordinateLoadError(
            f"SHP 无有效几何: {shp_path}", shp_path,
            hint=f"检测到 CRS={crs_label}；只支持 Point/Polygon"
        )

    return coords


# ----------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------
def load_coordinates_file(path: str) -> List[Dict]:
    """按扩展名自动分发，返回坐标列表。"""
    if not os.path.exists(path):
        raise CoordinateLoadError(f"文件不存在: {path}", path)

    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        coords = load_coordinates(path)
    elif ext == ".shp":
        coords = load_coordinates_shp(path)
    else:
        raise CoordinateLoadError(
            f"不支持的文件格式: {ext}", path, hint="仅支持 .csv / .shp"
        )

    # 后置校验
    for i, c in enumerate(coords):
        if not c.get("name") and not c.get("id"):
            c["name"] = f"point_{i + 1}"
            c["id"] = c["name"]
        elif not c.get("name"):
            c["name"] = c["id"]
        elif not c.get("id"):
            c["id"] = c["name"]
    return coords


if __name__ == "__main__":
    # 自测：python coordinate_loader.py <file>
    if len(sys.argv) < 2:
        print("Usage: python coordinate_loader.py <file.csv|file.shp>")
        sys.exit(1)
    try:
        coords = load_coordinates_file(sys.argv[1])
        print(f"Loaded {len(coords)} points:")
        for c in coords[:10]:
            print(f"  {c}")
    except CoordinateLoadError as e:
        print(f"ERROR: {e} ({e.path}) hint={e.hint}")
        sys.exit(2)