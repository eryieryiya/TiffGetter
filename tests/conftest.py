"""pytest 共享夹具：sys.path 注入、PNG 样张工厂、ImageFetcher 清理隔离。

所有夹具均显式使用，不做 autouse 全局 patch。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

import pytest
from PIL import Image, ImageDraw

# 将仓库根目录加入 sys.path，保证 `import satellite_processor` / `import providers...` 可用
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def sample_png(tmp_path: Path):
    """工厂夹具：用 Pillow 生成 PNG 样张（默认 256x256 纯色），返回写入路径。"""

    def _make(
        path: Optional[Path] = None,
        color: Tuple[int, int, int] = (200, 30, 30),
        size: Tuple[int, int] = (256, 256),
        pattern: str = "solid",
    ) -> Path:
        target = Path(path) if path is not None else tmp_path / "sample.png"
        target.parent.mkdir(parents=True, exist_ok=True)

        image = Image.new("RGB", size, color)
        if pattern == "grid":
            draw = ImageDraw.Draw(image)
            step_x = max(1, size[0] // 8)
            step_y = max(1, size[1] // 8)
            for x in range(0, size[0], step_x):
                draw.line([(x, 0), (x, size[1] - 1)], fill=(255, 255, 255))
            for y in range(0, size[1], step_y):
                draw.line([(0, y), (size[0] - 1, y)], fill=(255, 255, 255))

        image.save(target, format="PNG")
        return target

    return _make


@pytest.fixture
def no_cleanup(monkeypatch):
    """将 ImageFetcher 启动时的残留清理替换为受控版本。

    __init__ 调用（root_dir=None）保持 no-op，避免删除仓库根目录下的
    temp_tiles_* 目录；测试显式传入 root_dir 时仍执行真实的过期清理逻辑。
    """

    import satellite_processor

    original = satellite_processor.ImageFetcher._cleanup_residual_temp_tiles

    def _guarded(self, root_dir=None):
        if root_dir is None:
            return []
        return original(self, root_dir)

    monkeypatch.setattr(
        satellite_processor.ImageFetcher,
        "_cleanup_residual_temp_tiles",
        _guarded,
        raising=True,
    )
    return _guarded


@pytest.fixture
def fetcher_factory(no_cleanup):
    """工厂夹具：构造已隔离清理逻辑的 ImageFetcher 实例。"""

    from satellite_processor import ImageFetcher

    def _make(*args, **kwargs):
        return ImageFetcher(*args, **kwargs)

    return _make
