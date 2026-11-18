"""临时目录心跳与并行安全清理策略测试。

所有目录均创建在 pytest 的 tmp_path 下，绝不触碰仓库根目录的真实
temp_tiles_* 目录。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from utils.cleanup import (
    TEMP_HEARTBEAT_NAME,
    cleanup_stale_temp_tiles,
    create_temp_dir,
    is_temp_dir_active,
    scan_residuals,
)


def _age(path: Path, seconds: int) -> None:
    """将文件/目录 mtime 设置为指定秒数之前。"""
    ts = time.time() - seconds
    os.utime(path, (ts, ts))


def test_create_temp_dir_naming_and_heartbeat(tmp_path):
    path = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-01"))

    assert path.parent == tmp_path
    prefix = f"temp_tiles_wayback_2024-01-01_{os.getpid()}_"
    assert path.name.startswith(prefix)
    # mkdtemp 追加的随机后缀为 8 位（可能包含下划线，需按前缀截取）
    assert len(path.name[len(prefix):]) == 8

    assert (path / TEMP_HEARTBEAT_NAME).is_file()
    assert is_temp_dir_active(str(path)) is True


def test_expired_heartbeat_is_removed(tmp_path):
    path = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-02"))
    _age(path / TEMP_HEARTBEAT_NAME, 2 * 3600)

    assert is_temp_dir_active(str(path)) is False
    removed = cleanup_stale_temp_tiles(str(tmp_path))
    assert str(path) in removed
    assert not path.exists()


def test_dir_without_heartbeat_falls_back_to_mtime(tmp_path):
    stale = tmp_path / "temp_tiles_wayback_stale_noheartbeat"
    stale.mkdir()
    _age(stale, 2 * 3600)
    fresh = tmp_path / "temp_tiles_wayback_fresh_noheartbeat"
    fresh.mkdir()

    removed = cleanup_stale_temp_tiles(str(tmp_path))

    assert str(stale) in removed
    assert not stale.exists()
    assert str(fresh) not in removed
    assert fresh.exists()


def test_parallel_simulation_only_removes_stale(tmp_path):
    active = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-03"))
    stale = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-04"))
    _age(stale / TEMP_HEARTBEAT_NAME, 2 * 3600)

    removed = cleanup_stale_temp_tiles(str(tmp_path))

    assert removed == [str(stale)]
    assert active.exists()
    assert not stale.exists()


def test_fetcher_startup_cleanup_skips_active(tmp_path, fetcher_factory):
    active = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-05"))
    stale = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-06"))
    _age(stale / TEMP_HEARTBEAT_NAME, 2 * 3600)

    fetcher = fetcher_factory()
    removed = fetcher._cleanup_residual_temp_tiles(root_dir=str(tmp_path))

    assert str(stale) in removed
    assert not stale.exists()
    assert active.exists()


def test_scan_residuals_reports_active_flag(tmp_path):
    active = Path(create_temp_dir(str(tmp_path), "wayback", "2024-01-07"))
    stale = tmp_path / "temp_tiles_wayback_stale_scan"
    stale.mkdir()
    _age(stale, 2 * 3600)

    release = tmp_path / "data" / "output" / "wayback" / "2024-01-01"
    release.mkdir(parents=True)
    (release / "metadata.json").write_text("{}", encoding="utf-8")

    by_name = {Path(it["path"]).name: it for it in scan_residuals(str(tmp_path))}

    assert by_name[active.name]["active"] is True
    assert by_name[stale.name]["active"] is False
    assert by_name["2024-01-01"]["active"] is False
