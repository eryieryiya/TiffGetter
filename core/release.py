"""metadata 读取与 release 日期筛选辅助。"""
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _read_metadata_source(date_dir: str) -> str:
    """读取 release 目录的数据源；缺少/损坏 metadata 时按 wayback 处理。"""
    meta_path = os.path.join(date_dir, 'metadata.json')
    if not os.path.exists(meta_path):
        return 'wayback'
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return str(data.get('source') or 'wayback')
    except Exception as e:
        logger.warning(f"读取 {meta_path} 失败，按 wayback 处理: {e}")
        return 'wayback'


def filter_releases_by_date_range(releases: List[Dict],
                                  date_range: Tuple[str, str]) -> List[Dict]:
    """按 [start, end] 闭区间筛选 release 列表。"""
    return [d for d in releases if date_range[0] <= d['date'] <= date_range[1]]


def select_releases(releases: List[Dict],
                    date_range: Optional[Tuple[str, str]] = None) -> List[Dict]:
    """按日期升序排序；给定 date_range 时再筛选并记录剩余数量。"""
    dates = sorted(releases, key=lambda d: d['date'])
    if date_range:
        dates = filter_releases_by_date_range(dates, date_range)
        logger.info(f"日期筛选后剩余 {len(dates)} 个")
    return dates
