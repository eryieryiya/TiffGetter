"""瓦片坐标 / WGS84 边界 / PNG 裁剪等纯几何逻辑。"""
import logging
import math
from typing import Dict, Optional, Set, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0 * n
    )
    return xtile, ytile


def tile_to_lonlat(x: int, y: int, zoom: int) -> Tuple[float, float]:
    """瓦片 (x, y) 左上角的 WGS84 经纬度"""
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2.0 * y / n)))
    lat = math.degrees(lat_rad)
    return lon, lat


def _log_zoom_buffer_diagnostic(lat: float, lon: float, zoom: int,
                                buffer_size: int, cos_lat: float,
                                diag_done: Set[Tuple[int, float, float, int]]) -> None:
    """首次调用时打印 zoom / buffer 与地面覆盖的对应关系，异常时 WARNING。
    节流键：同一 (zoom, round(lat,1), round(lon,1), buffer_size) 只打印一次。
    """
    key = (zoom, round(lat, 1), round(lon, 1), buffer_size)
    already = key in diag_done
    if already:
        return

    # 估算该 zoom 级单瓦片在 (lat, lon) 附近的大致地面覆盖尺寸
    n = 2.0 ** zoom
    one_tile_lon_deg = 360.0 / n
    # 纬度方向用相邻两张瓦片的纬度差近似（Mercator 非线性，但取局部差足够）
    x_tile, y_tile = latlon_to_tile(lat, lon, zoom)
    _lon1, lat_top = tile_to_lonlat(x_tile, y_tile, zoom)
    _lon2, lat_bot = tile_to_lonlat(x_tile, y_tile + 1, zoom)
    one_tile_ns_m = abs(lat_top - lat_bot) * 111320.0
    one_tile_ew_m = one_tile_lon_deg * 111320.0 * cos_lat

    # 单瓦片覆盖 与 buffer 的比值（判断 buffer 是否有意义）
    ratio_ns = one_tile_ns_m / max(buffer_size, 1)
    ratio_ew = one_tile_ew_m / max(buffer_size, 1)
    ratio = max(ratio_ns, ratio_ew)

    msg = (
        f"[瓦片粒度诊断] zoom={zoom}, buffer={buffer_size}m, "
        f"单瓦片≈ {one_tile_ew_m:.0f}m(EW) × {one_tile_ns_m:.0f}m(NS)；"
    )
    if ratio <= 4.0:
        logger.info(msg + f"单瓦片/缓冲 ≈ {ratio:.1f}×，覆盖范围将与 buffer 匹配 ✓")
    elif ratio <= 20.0:
        logger.warning(
            msg
            + f"单瓦片/缓冲 ≈ {ratio:.1f}×，最终输出 ≈ 单瓦片粒度（比 buffer 大）。"
            + " 若希望更小范围，请提高 zoom。"
        )
    else:
        logger.warning(
            msg
            + f"单瓦片/缓冲 ≈ {ratio:.0f}×！！！"
            + f" 此时 buffer={buffer_size}m 远小于 zoom={zoom} 的瓦片粒度，"
            + " 输出影像将覆盖 10+km 级别的范围（与 buffer 数值完全不匹配）。"
            + " 请大幅提高 zoom 级别（建议 zoom ≥ 17）或增大 buffer_size。"
        )
    diag_done.add(key)


def get_tile_coords(lat: float, lon: float, zoom: int,
                    buffer_size: int = 500,
                    diag_done: Optional[Set[Tuple[int, float, float, int]]] = None,
                    ) -> Tuple[int, int, int, int]:
    """计算覆盖 (lat, lon) ± buffer 米 范围所需的瓦片坐标范围。

    返回 (x_min, x_max, y_min, y_max)，其中：
    - x_min/x_max 包含两端（含）
    - y_min 是 tile y 的较小值（对应更北 / 更大纬度）
    - y_max 是 tile y 的较大值（对应更南 / 更小纬度）

    注意：
        最终下载范围 = 瓦片拼接后的整块矩形，其大小受 ``zoom`` 级别决定。
        例如 zoom=12 单瓦片在 35°N 约覆盖 16km(EW) × 8km(NS)，
        此时即使 buffer=200m，最终输出也必然 ≥ 单瓦片尺寸。
        若用户希望"输出范围约等于 buffer"，请选择 zoom ≥ 17。
    """
    # ----- 入参硬断言：防止「米被当成度 / 级别当成米」这种灾难级错误 -----
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"lat 越界 {lat}，必须 ∈ [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"lon 越界 {lon}，必须 ∈ [-180, 180]")
    if not isinstance(zoom, int) or not (1 <= zoom <= 22):
        # Esri Wayback 实测支持到 z≤20，这里上限稍微放宽做防御
        raise ValueError(f"zoom 越界 {zoom!r}，必须为 1..22 的整数")
    if not isinstance(buffer_size, int) or not (10 <= buffer_size <= 200000):
        raise ValueError(f"buffer_size 越界 {buffer_size!r}，必须为 10..200000 的整数（米）")

    # 经度方向按纬度做 cos 修正，保证东西向距离正确
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    half_lon_deg = (buffer_size / 2) / (111320.0 * cos_lat)
    half_lat_deg = (buffer_size / 2) / 111320.0

    # ----- 防「buffer_size 被当成度」的二次防线 -----
    # 合法 buffer_size（米）换算后的半纬范围，即使 200km 也只有 ~1.8°；
    # 一旦超过 5°，只可能是「buffer 被当成度」或调用链把 zoom/buffer 传反了。
    if half_lat_deg > 5.0:
        raise ValueError(
            f"buffer_size 换算异常：half_lat_deg={half_lat_deg:.4f}° 过大，"
            f"请确认 buffer_size={buffer_size} 的单位是否为米、"
            f"以及调用时 zoom={zoom} 与 buffer_size 位置是否反传。"
        )

    # ----- zoom×buffer 合理性诊断（首次触发时打印一次） -----
    if diag_done is None:
        diag_done = set()
    _log_zoom_buffer_diagnostic(lat, lon, zoom, buffer_size, cos_lat, diag_done)

    # 四个角点
    sx_tile, sy_tile = latlon_to_tile(lat - half_lat_deg, lon - half_lon_deg, zoom)
    nx_tile, ny_tile = latlon_to_tile(lat + half_lat_deg, lon + half_lon_deg, zoom)

    x_min, x_max = min(sx_tile, nx_tile), max(sx_tile, nx_tile)
    # 在 Web Mercator 中，纬度越高 y 越小，因此 y_min = 较大纬度对应的瓦片
    y_min, y_max = min(sy_tile, ny_tile), max(sy_tile, ny_tile)
    return x_min, x_max, y_min, y_max


def _tile_bounds_wgs84(x_min: int, x_max: int, y_min: int, y_max: int,
                       zoom: int) -> Tuple[float, float, float, float]:
    """基于瓦片四角精确计算覆盖范围的 WGS84 边界。

    返回 (min_lon, min_lat, max_lon, max_lat)。
    """
    # y_min 是更靠北的瓦片（更小 y），其顶边 = max_lat
    # y_max 是更靠南的瓦片（更大 y），其底边 = min_lat
    lon_nw, lat_nw = tile_to_lonlat(x_min, y_min, zoom)
    lon_se, lat_se = tile_to_lonlat(x_max + 1, y_max + 1, zoom)
    min_lon = lon_nw
    max_lon = lon_se
    max_lat = lat_nw
    min_lat = lat_se
    return min_lon, min_lat, max_lon, max_lat


def _buffer_wgs84_rect(lat: float, lon: float,
                       buffer_size: int) -> Tuple[float, float, float, float]:
    """返回 (lat, lon) ± buffer 米 的 WGS84 裁剪矩形：
    (clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat)。
    """
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    half_lon = (buffer_size / 2.0) / (111320.0 * cos_lat)
    half_lat = (buffer_size / 2.0) / 111320.0
    clip_min_lon = lon - half_lon
    clip_max_lon = lon + half_lon
    clip_min_lat = lat - half_lat  # 更南
    clip_max_lat = lat + half_lat  # 更北
    return clip_min_lon, clip_min_lat, clip_max_lon, clip_max_lat


def _crop_png_to_wgs84_rect(png_path: str,
                            canvas_bounds: Tuple[float, float, float, float],
                            clip_rect: Tuple[float, float, float, float],
                            ) -> Tuple[Dict[str, float], Tuple[int, int, int, int], bool]:
    """按 WGS84 裁剪矩形裁剪 PNG 文件（原地覆盖写回）。

    Args:
        png_path      : 待裁剪的 PNG（通常是整张瓦片拼接图）。
        canvas_bounds : 该 PNG 对应的 WGS84 边界 (min_lon, min_lat, max_lon, max_lat)。
        clip_rect     : 用户想要的裁剪矩形 (min_lon, min_lat, max_lon, max_lat)。

    Returns:
        (new_bounds, px_box, did_crop) ——
            new_bounds: 裁剪后实际的 WGS84 边界字典（已按图像像素做整数对齐，
                        可能与 clip_rect 差 ±1 像素对应的度数）。
            px_box    : (left, top, right, bottom) 实际裁剪的像素 box（若未裁剪则为整图 (0,0,w,h)）。
            did_crop  : True 表示实际发生了裁剪（图像尺寸变小）；
                        False 表示 clip_rect 已与画布接近全同，未动文件。
    """
    c_min_lon, c_min_lat, c_max_lon, c_max_lat = canvas_bounds
    k_min_lon, k_min_lat, k_max_lon, k_max_lat = clip_rect

    # --- 与画布求交集（防御性：裁剪矩形不应超出 PNG 地理覆盖） ---
    #   命名统一：min_lon=西（小经度/左）、max_lon=东（大经度/右）、
    #            min_lat=南（小纬度/下）、max_lat=北（大纬度/上）
    i_min_lon = max(c_min_lon, k_min_lon)   # 交集西边界 = 两者西边中更东的那个
    i_max_lon = min(c_max_lon, k_max_lon)   # 交集东边界 = 两者东边中更西的那个
    i_min_lat = max(c_min_lat, k_min_lat)   # 交集南边界 = 两者南边中更北的那个（数值更大）
    i_max_lat = min(c_max_lat, k_max_lat)   # 交集北边界 = 两者北边中更南的那个（数值更小）
    # 判空：西 ≥ 东  或  南 ≥ 北
    if i_max_lon <= i_min_lon or i_min_lat >= i_max_lat:
        raise ValueError(
            f"裁剪矩形与画布无交集：clip={clip_rect}, canvas={canvas_bounds}"
        )

    with Image.open(png_path) as img:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        w, h = img.size
        lon_per_px = (c_max_lon - c_min_lon) / float(w)
        lat_per_px = (c_max_lat - c_min_lat) / float(h)  # >0（度/像素向下）

        # 图像左上角 = (c_min_lon, c_max_lat)，向下 y+ → 纬度减小
        px_left_f   = (i_min_lon - c_min_lon) / lon_per_px
        px_right_f  = (i_max_lon - c_min_lon) / lon_per_px
        px_top_f    = (c_max_lat - i_max_lat) / lat_per_px   # max_lat 为更北（图像顶部），减去大纬度得 top
        px_bottom_f = (c_max_lat - i_min_lat) / lat_per_px   # 减去小纬度得到 bottom（更大 y）

        # --- 判断是否"基本没裁"：交集 ≈ 画布（<1px 差异）就直接跳过 ---
        no_crop_east  = (abs(px_left_f)       < 0.95) and (abs(w - px_right_f)  < 0.95)
        no_crop_north = (abs(px_top_f)        < 0.95) and (abs(h - px_bottom_f) < 0.95)
        if no_crop_east and no_crop_north:
            new_bounds = {
                'min_lon': c_min_lon, 'min_lat': c_min_lat,
                'max_lon': c_max_lon, 'max_lat': c_max_lat,
            }
            return new_bounds, (0, 0, w, h), False

        # --- 像素取整（floor(左/上)、ceil(右/下) 保证覆盖 clip 矩形，±1px 无差） ---
        px_left   = max(0, int(math.floor(px_left_f)))
        px_top    = max(0, int(math.floor(px_top_f)))
        px_right  = min(w, int(math.ceil(px_right_f)))
        px_bottom = min(h, int(math.ceil(px_bottom_f)))
        # 保证 1px 以上尺寸
        px_right  = max(px_right,  px_left   + 1)
        px_bottom = max(px_bottom, px_top    + 1)

        cropped = img.crop((px_left, px_top, px_right, px_bottom))
        cropped.save(png_path, 'PNG')
        new_w, new_h = cropped.size
        cropped.close()

    # 按裁剪后实际像素反推 WGS84 边界（与整数像素对齐，避免 ±半度浮点缝）
    new_min_lon = c_min_lon + px_left  * lon_per_px
    new_max_lon = c_min_lon + px_right * lon_per_px
    new_max_lat = c_max_lat - px_top    * lat_per_px
    new_min_lat = c_max_lat - px_bottom * lat_per_px

    new_bounds = {
        'min_lon': new_min_lon, 'min_lat': new_min_lat,
        'max_lon': new_max_lon, 'max_lat': new_max_lat,
    }
    return new_bounds, (px_left, px_top, px_right, px_bottom), True


def _center_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """返回覆盖 (lat, lon, zoom) 的瓦片坐标（int, int）。"""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y
