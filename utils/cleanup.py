"""
utils/cleanup.py - 残余清理模块

提供两个工具函数：
- cleanup_temp_tiles(root_dir): 清理临时瓦片目录，返回清理路径列表
- scan_residuals(root_dir): 扫描所有可清理项（temp_tiles_*、历史日期子目录），
                           返回 [{path, kind, size_bytes, mtime, is_dir}]

供 GUI Tab 3 "清理与维护" 使用。
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Dict, List


def scan_residuals(root_dir: str) -> List[Dict]:
    """扫描根目录及 data/output/historical/ 下所有可清理条目。

    Returns:
        每项：
            path: 绝对路径
            kind: "temp_tiles" | "historical_date" | "other"
            size_bytes: 目录占用字节
            mtime: 最近修改时间戳
            is_dir: 是否目录
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
                })
    except OSError:
        pass

    # 2) data/output/historical/ 下的日期子目录
    hist_dir = os.path.join(root_dir, 'data', 'output', 'historical')
    if os.path.isdir(hist_dir):
        for date_sub in os.listdir(hist_dir):
            full = os.path.join(hist_dir, date_sub)
            if os.path.isdir(full):
                items.append({
                    "path": full,
                    "kind": "historical_date",
                    "size_bytes": _dir_size(full),
                    "mtime": os.path.getmtime(full),
                    "is_dir": True,
                })

    # 按 mtime 倒序（新→旧）
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return items


def cleanup_temp_tiles(root_dir: str) -> List[str]:
    """仅清理 temp_tiles_* 目录，返回已清理路径列表。"""
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