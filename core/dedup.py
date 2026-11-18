"""字节级 MD5 与感知 dHash 去重逻辑。"""
import hashlib
import logging
from typing import Optional, Set

from PIL import Image

logger = logging.getLogger(__name__)

# 感知哈希汉明距阈值：<=DHASH_DUP_THRESHOLD 即视为「视觉同一影像」。
# dHash16 的 256 bits 中经验上：完全相同图像=0~2；轻微压缩差异<8；同一场景不同季节一般>30。
DHASH_SIZE = 16
DHASH_DUP_THRESHOLD = 6
# 预筛（单瓦片）使用更宽松阈值，避免误跳：瓦片粒度细节差异更大
DHASH_TILE_THRESHOLD = 4


def compute_image_hash(image_path: str,
                       chunk_size: int = 1 << 20) -> Optional[str]:
    """字节级 MD5（流式，避免一次读入大文件）。命中即 100% 确定重复。"""
    try:
        h = hashlib.md5()
        with open(image_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def compute_dhash_int(img, size: int = DHASH_SIZE) -> Optional[int]:
    """计算 dHash（差异哈希）整数（抗 PNG 编码、JPEG 压缩、色深差异）。

    img: PIL.Image（或任何已打开的图像）。内部会转为 L 并 resize。
    返回 int（size^2 bits）。失败返回 None。
    """
    try:
        gray = img.convert('L').resize((size + 1, size), Image.LANCZOS)
        px = list(gray.getdata())
        w = size + 1
        bits = 0
        idx = 0
        for y in range(size):
            row = y * w
            for x in range(size):
                if px[row + x] > px[row + x + 1]:
                    bits |= 1 << idx
                idx += 1
        return bits
    except Exception:
        return None


def compute_dhash_int_from_path(path: str,
                                size: int = DHASH_SIZE) -> Optional[int]:
    try:
        with Image.open(path) as im:
            return compute_dhash_int(im, size)
    except Exception:
        return None


def _hamming(a: Optional[int], b: Optional[int], size: int = DHASH_SIZE) -> int:
    if a is None or b is None:
        return size * size  # 最坏距离，永不判重
    return bin(a ^ b).count('1')


def _is_duplicate_image(path_or_dhash, byte_hashes: Optional[Set[str]] = None,
                        dhashes: Optional[Set[int]] = None, strict: bool = False,
                        dup_threshold: int = DHASH_DUP_THRESHOLD):
    """判定输入是否与历史记录重复。

    path_or_dhash: 图片路径(str) 或 预计算的 (md5, dhash) 二元组；
    byte_hashes:   字节级 MD5 set；
    dhashes:       感知 dhash int set；
    strict:        False 使用 dup_threshold；True 更严格（仅 0/1）。
    返回 (is_dup: bool, matched_md5, matched_dhash)。
    """
    if isinstance(path_or_dhash, tuple) and len(path_or_dhash) == 2:
        img_md5, img_dhash = path_or_dhash
    else:
        img_md5 = compute_image_hash(path_or_dhash)
        img_dhash = compute_dhash_int_from_path(path_or_dhash)

    # 1) 字节级 exact match → 直接确定重复
    if img_md5 and byte_hashes is not None and img_md5 in byte_hashes:
        return True, img_md5, img_dhash

    # 2) 感知级近似 match → 视觉重复（ESRI 重发布的坑）
    if img_dhash is not None and dhashes is not None:
        thresh = 1 if strict else dup_threshold
        for known in dhashes:
            if _hamming(img_dhash, known) <= thresh:
                return True, img_md5, img_dhash
    return False, img_md5, img_dhash
