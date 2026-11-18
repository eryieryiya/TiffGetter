"""
utils/cleanup.py - 残余清理模块

提供临时瓦片目录的心跳与清理策略：
- create_temp_dir(root_dir, source, date_str): 创建带心跳的临时瓦片目录
- touch_temp_heartbeat(dir_path): 刷新心跳文件 mtime
- is_temp_dir_active(dir_path, ttl): 依据心跳判断目录是否仍在使用
- cleanup_stale_temp_tiles(root_dir, ttl): 仅清理过期（心跳超时）目录
- cleanup_temp_tiles(root_dir): 强制清理全部临时瓦片目录（危险，仅供显式调用）
- scan_residuals(root_dir): 扫描所有可清理项（temp_tiles_*、data/output 下的 release 目录），
                           返回 [{path, kind, size_bytes, mtime, is_dir, active}]

data/output 支持多数据源与批量输出结构：
- wayback 单点：data/output/historical/<date>/
- 非 wayback 单点：data/output/<source>/<current|date>/
- 批量：data/output/.../<coord>/<current|date>/
仅当目录包含 metadata.json 或同名 PNG 时视为 release 目录，识别后剪枝，不扫描其子目录；
不扫描 data/input，本模块扫描函数只读不删。

供 GUI Tab 3 "清理与维护" 使用。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from typing import Dict, List

# data/output 下允许扫描的最大相对深度（覆盖 source/batch/coord/release 结构）
_MAX_OUTPUT_DEPTH = 4

# 临时目录心跳文件名与默认过期时间（秒）
TEMP_HEARTBEAT_NAME = ".active"
TEMP_TTL_SECONDS = 1800


def create_temp_dir(root_dir: str, source: str, date_str: str) -> str:
    """在 root_dir 下创建带 PID/随机后缀的临时瓦片目录并写入心跳。"""
    prefix = f"temp_tiles_{source}_{date_str}_{os.getpid()}_"
    path = tempfile.mkdtemp(prefix=prefix, dir=root_dir)
    touch_temp_heartbeat(path)
    return path


def touch_temp_heartbeat(dir_path: str) -> None:
    """刷新心跳文件 mtime；任何失败静默忽略。"""
    heartbeat = os.path.join(dir_path, TEMP_HEARTBEAT_NAME)
    try:
        with open(heartbeat, "a"):
            pass
        os.utime(heartbeat, None)
    except OSError:
        pass


def is_temp_dir_active(dir_path: str, ttl: int = TEMP_TTL_SECONDS) -> bool:
    """判断临时目录是否仍在使用：以心跳 mtime 为准，缺失时回退目录 mtime。"""
    heartbeat = os.path.join(dir_path, TEMP_HEARTBEAT_NAME)
    try:
        mtime = os.path.getmtime(heartbeat)
    except OSError:
        try:
            mtime = os.path.getmtime(dir_path)
        except OSError:
            return False
    return (time.time() - mtime) < ttl


def cleanup_stale_temp_tiles(root_dir: str,
                             ttl: int = TEMP_TTL_SECONDS) -> List[str]:
    """仅清理已过期（心跳超时）的 temp_tiles_* 目录，返回已清理路径列表。"""
    removed: List[str] = []
    try:
        entries = os.listdir(root_dir)
    except OSError:
        return removed

    for entry in entries:
        full = os.path.join(root_dir, entry)
        if not (os.path.isdir(full) and entry.startswith('temp_tiles_')):
            continue
        if is_temp_dir_active(full, ttl=ttl):
            continue
        try:
            shutil.rmtree(full, ignore_errors=True)
            removed.append(full)
        except Exception:
            pass
    return removed


def _is_release_dir(dirpath: str, filenames: List[str]) -> bool:
    """目录包含 metadata.json 或与目录同名的 PNG 时视为 release 目录。"""
    if 'metadata.json' in filenames:
        return True
    return f"{os.path.basename(dirpath)}.png" in filenames


def scan_residuals(root_dir: str) -> List[Dict]:
    """扫描根目录及 data/output/ 下所有可清理条目。

    Returns:
        每项：
            path: 绝对路径
            kind: "temp_tiles" | "historical_date"
            size_bytes: 目录占用字节
            mtime: 最近修改时间戳
            is_dir: 是否目录
            active: 是否仍在使用（仅 temp_tiles 有意义）
    """
    items: List[Dict] = []

    # 1) temp_tiles_* （根目录）
    try:
        for entry in os.listdir(root_dir):
            full = os.path.join(root_dir, entry)
            if os.path.isdir(full) and entry.startswith('temp_tiles_'):
                items.append({
                    "path": full,
                    "kind": "temp_tiles",
                    "size_bytes": _dir_size(full),
                    "mtime": os.path.getmtime(full),
                    "is_dir": True,
                    "active": is_temp_dir_active(full),
                })
    except OSError:
        pass

    # 2) data/output/ 下的 release 目录（多数据源、批量结构）
    output_root = os.path.join(root_dir, 'data', 'output')
    if os.path.isdir(output_root):
        for dirpath, dirnames, filenames in os.walk(output_root, topdown=True):
            rel = os.path.relpath(dirpath, output_root)
            depth = 0 if rel == os.curdir else rel.count(os.sep) + 1
            if depth == 0:
                continue
            if _is_release_dir(dirpath, filenames):
                items.append({
                    "path": dirpath,
                    "kind": "historical_date",
                    "size_bytes": _dir_size(dirpath),
                    "mtime": os.path.getmtime(dirpath),
                    "is_dir": True,
                    "active": False,
                })
                dirnames[:] = []  # 命中 release 目录后剪枝
                continue
            if depth >= _MAX_OUTPUT_DEPTH:
                dirnames[:] = []  # 限制递归深度

    # 按 mtime 倒序（新→旧）
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return items


def cleanup_temp_tiles(root_dir: str) -> List[str]:
    """强制清理全部 temp_tiles_* 目录，返回已清理路径列表。

    WARNING: 危险操作——不检查心跳，会删除其他进程正在使用的临时目录。
    正常运行流程请使用 cleanup_stale_temp_tiles()。
    """
    removed: List[str] = []
    try:
        entries = os.listdir(root_dir)
    except OSError:
        return removed

    for entry in entries:
        full = os.path.join(root_dir, entry)
        if not (os.path.isdir(full) and entry.startswith('temp_tiles_')):
            continue
        try:
            shutil.rmtree(full, ignore_errors=True)
            removed.append(full)
        except Exception:
            pass
    return removed


def delete_paths(paths: List[str]) -> List[Dict]:
    """批量删除路径；返回每项执行结果 [{path, ok, error}]。

    不存在的路径视为失败（避免误删除的静默成功）。
    """
    results = []
    for p in paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=False)
            elif os.path.isfile(p):
                os.remove(p)
            else:
                raise FileNotFoundError(f"路径不存在: {p}")
            results.append({"path": p, "ok": True, "error": ""})
        except Exception as e:
            results.append({"path": p, "ok": False, "error": str(e)})
    return results


def _dir_size(path: str) -> int:
    """递归累计目录占用字节数。"""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def format_size(n: int) -> str:
    """字节 → 人类可读。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} TB"


if __name__ == "__main__":
    # 自测
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"扫描根目录: {base}")
    items = scan_residuals(base)
    print(f"发现 {len(items)} 个可清理条目:")
    for it in items:
        from datetime import datetime
        ts = datetime.fromtimestamp(it['mtime']).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  [{it['kind']}] {format_size(it['size_bytes']):>10} {ts}  {it['path']}")