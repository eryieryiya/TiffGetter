"""哈希与去重判定的离线单元测试。

覆盖：dHash 稳定性/区分度、汉明距边界、``_is_duplicate_image`` 的 MD5/dHash
命中与 strict 模式、以及 ``_read_metadata_source`` 的读取回退逻辑。
所有用例只操作 tmp_path，不访问网络。
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from satellite_processor import ImageFetcher


def _gradient(path: Path, reverse: bool = False, size: tuple = (256, 256)) -> Path:
    """生成水平灰阶渐变图；reverse=True 时方向相反（dHash 位全翻转）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    img = Image.new("L", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            v = int(255 * x / (w - 1))
            px[x, y] = 255 - v if reverse else v
    img.save(path, format="PNG")
    return path


# ----------------------------------------------------------------------
# dHash / 汉明距
# ----------------------------------------------------------------------
def test_dhash_solid_image_is_stable(tmp_path, sample_png):
    """纯色图的 dHash 应恒为 0 且多次计算一致（与颜色、编码无关）。"""
    red = sample_png(tmp_path / "red.png", color=(200, 30, 30), size=(64, 64))
    black = sample_png(tmp_path / "black.png", color=(0, 0, 0), size=(512, 512))

    d_red = ImageFetcher.compute_dhash_int_from_path(str(red))
    d_red_again = ImageFetcher.compute_dhash_int_from_path(str(red))
    d_black = ImageFetcher.compute_dhash_int_from_path(str(black))

    assert d_red is not None
    assert d_red == d_red_again == 0
    assert d_black == 0

    with Image.open(red) as im:
        assert ImageFetcher.compute_dhash_int(im) == 0


def test_dhash_distinct_images_exceed_threshold(tmp_path):
    """方向相反的渐变图 dHash 差异远大于判重阈值。"""
    up = _gradient(tmp_path / "up.png")
    down = _gradient(tmp_path / "down.png", reverse=True)

    d_up = ImageFetcher.compute_dhash_int_from_path(str(up))
    d_down = ImageFetcher.compute_dhash_int_from_path(str(down))

    assert d_up is not None and d_down is not None
    assert d_up != d_down
    assert ImageFetcher._hamming(d_up, d_down) > ImageFetcher.DHASH_DUP_THRESHOLD


def test_hamming_boundaries():
    """0 距离、全 1 距离与 None（最坏距离）的边界行为。"""
    bits = ImageFetcher.DHASH_SIZE * ImageFetcher.DHASH_SIZE

    assert ImageFetcher._hamming(0, 0) == 0
    assert ImageFetcher._hamming(123456789, 123456789) == 0
    assert ImageFetcher._hamming(0, (1 << bits) - 1) == bits
    assert ImageFetcher._hamming((1 << bits) - 1, 0) == bits
    assert ImageFetcher._hamming(None, 0) == bits
    assert ImageFetcher._hamming(0, None) == bits
    assert ImageFetcher._hamming(None, None) == bits


# ----------------------------------------------------------------------
# _is_duplicate_image
# ----------------------------------------------------------------------
def test_is_duplicate_image_md5_exact_hit(tmp_path, fetcher_factory, sample_png):
    """字节级 MD5 命中直接判定重复，并回传匹配到的 MD5。"""
    fetcher = fetcher_factory()
    a = sample_png(tmp_path / "a.png", color=(10, 120, 200), pattern="grid")
    b = sample_png(tmp_path / "b.png", color=(10, 120, 200), pattern="grid")

    img_md5 = fetcher.compute_image_hash(str(a))
    assert img_md5 is not None
    assert fetcher.compute_image_hash(str(b)) == img_md5

    is_dup, matched_md5, matched_dhash = fetcher._is_duplicate_image(
        str(b), byte_hashes={img_md5}, dhashes=set()
    )
    assert is_dup is True
    assert matched_md5 == img_md5
    assert matched_dhash is not None


def test_is_duplicate_image_dhash_near_hit(tmp_path, fetcher_factory):
    """轻微差异（单像素/亮度微调）的图 dHash 近似命中。"""
    fetcher = fetcher_factory()
    base = _gradient(tmp_path / "base.png")

    with Image.open(base) as im:
        tweaked = im.copy()
    tweaked.putpixel((5, 5), 255 if tweaked.getpixel((5, 5)) != 255 else 0)
    variant = tmp_path / "variant.png"
    tweaked.save(variant, format="PNG")
    tweaked.close()

    md5_base = fetcher.compute_image_hash(str(base))
    md5_variant = fetcher.compute_image_hash(str(variant))
    assert md5_base != md5_variant  # 字节级不同，排除 MD5 命中

    d_base = fetcher.compute_dhash_int_from_path(str(base))
    d_variant = fetcher.compute_dhash_int_from_path(str(variant))
    assert d_base is not None and d_variant is not None
    assert fetcher._hamming(d_base, d_variant) <= fetcher.DHASH_DUP_THRESHOLD

    is_dup, _, _ = fetcher._is_duplicate_image(
        str(variant), byte_hashes={md5_base}, dhashes={d_base}
    )
    assert is_dup is True


def test_is_duplicate_image_strict_mode(tmp_path, fetcher_factory):
    """strict=True 只接受 0/1 距离；默认阈值接受较大的近似差异。"""
    fetcher = fetcher_factory()
    base = _gradient(tmp_path / "base.png")
    d_base = fetcher.compute_dhash_int_from_path(str(base))
    assert d_base is not None

    near = d_base ^ 0b11  # 距离 2：默认阈值内，strict 下不算重复
    assert fetcher._hamming(d_base, near) == 2

    is_dup_default, md5_default, dhash_default = fetcher._is_duplicate_image(
        ("0" * 32, near), byte_hashes=set(), dhashes={d_base}, strict=False
    )
    assert is_dup_default is True
    assert md5_default == "0" * 32
    assert dhash_default == near

    is_dup_strict, _, _ = fetcher._is_duplicate_image(
        ("0" * 32, near), byte_hashes=set(), dhashes={d_base}, strict=True
    )
    assert is_dup_strict is False

    # 距离 1 在 strict 下仍判重
    closest = d_base ^ 0b1
    is_dup_one, _, _ = fetcher._is_duplicate_image(
        ("0" * 32, closest), byte_hashes=set(), dhashes={d_base}, strict=True
    )
    assert is_dup_one is True


def test_is_duplicate_image_no_match(tmp_path, fetcher_factory):
    """MD5 与 dHash 均不命中时返回 False，并回传计算出的哈希。"""
    fetcher = fetcher_factory()
    img = _gradient(tmp_path / "img.png")

    far = (1 << (ImageFetcher.DHASH_SIZE * ImageFetcher.DHASH_SIZE)) - 1
    is_dup, img_md5, img_dhash = fetcher._is_duplicate_image(
        str(img), byte_hashes={"deadbeef"}, dhashes={far}
    )
    assert is_dup is False
    assert img_md5 == fetcher.compute_image_hash(str(img))
    assert img_dhash == fetcher.compute_dhash_int_from_path(str(img))


# ----------------------------------------------------------------------
# _read_metadata_source
# ----------------------------------------------------------------------
def test_read_metadata_source_same_and_other(tmp_path):
    """同源 / 异源 metadata 分别返回其 source 字段。"""
    same = tmp_path / "same"
    same.mkdir()
    (same / "metadata.json").write_text(
        json.dumps({"source": "wayback"}), encoding="utf-8"
    )
    assert ImageFetcher._read_metadata_source(str(same)) == "wayback"

    other = tmp_path / "other"
    other.mkdir()
    (other / "metadata.json").write_text(
        json.dumps({"source": "esri"}), encoding="utf-8"
    )
    assert ImageFetcher._read_metadata_source(str(other)) == "esri"


def test_read_metadata_source_missing_falls_back_to_wayback(tmp_path):
    """缺少 metadata / 内容损坏 / source 为空时统一按 wayback 处理。"""
    missing = tmp_path / "missing"
    missing.mkdir()
    assert ImageFetcher._read_metadata_source(str(missing)) == "wayback"

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "metadata.json").write_text("{not-json", encoding="utf-8")
    assert ImageFetcher._read_metadata_source(str(broken)) == "wayback"

    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "metadata.json").write_text(
        json.dumps({"source": ""}), encoding="utf-8"
    )
    assert ImageFetcher._read_metadata_source(str(empty)) == "wayback"

    assert ImageFetcher._read_metadata_source(str(tmp_path / "not_exist")) == "wayback"
