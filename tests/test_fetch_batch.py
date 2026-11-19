"""``fetch_batch`` 的坐标级并发行为测试。

全部离线：把 ``ImageFetcher.fetch_all`` 替换为受控假实现，真实调用
``fetch_batch``，验证线程并发、独立实例、返回顺序与 ValueError 隔离。
"""

from __future__ import annotations

import threading
import time

import satellite_processor


def _success_result(date: str = "2020-01-01"):
    """构造单条成功结果，供假 fetch_all 返回。"""
    return [{"status": "success", "date": date}]


def test_fetch_batch_runs_coordinates_in_parallel(fetcher_factory, monkeypatch, tmp_path):
    """coord_concurrency=2 时两个坐标在不同线程、不同实例上并发执行。"""
    fetcher = fetcher_factory()
    barrier = threading.Barrier(2, timeout=5)
    records = []
    lock = threading.Lock()

    def _fake_fetch_all(self, lat, lon, zoom=18, output_dir=None,
                        buffer_size=500, date_range=None, dedup=None,
                        emit_events=False, event_coord=None):
        with lock:
            records.append((threading.current_thread().ident, id(self)))
        barrier.wait()
        return _success_result()

    monkeypatch.setattr(
        satellite_processor.ImageFetcher, "fetch_all", _fake_fetch_all
    )

    coords = [
        {"lat": 31.2304, "lon": 121.4737, "name": "a"},
        {"lat": 31.2400, "lon": 121.4800, "name": "b"},
    ]
    summary = fetcher.fetch_batch(
        coords, str(tmp_path / "out"), coord_concurrency=2
    )

    assert len(summary) == 2
    assert len({ident for ident, _ in records}) == 2
    assert len({inst_id for _, inst_id in records}) == 2


def test_fetch_batch_preserves_input_order(fetcher_factory, monkeypatch, tmp_path):
    """后提交的坐标先完成时，summary 仍按输入顺序排列。"""
    fetcher = fetcher_factory()

    def _fake_fetch_all(self, lat, lon, zoom=18, output_dir=None,
                        buffer_size=500, date_range=None, dedup=None,
                        emit_events=False, event_coord=None):
        if lat == 31.2304:
            time.sleep(0.05)
        return _success_result()

    monkeypatch.setattr(
        satellite_processor.ImageFetcher, "fetch_all", _fake_fetch_all
    )

    coords = [
        {"lat": 31.2304, "lon": 121.4737, "name": "slow"},
        {"lat": 31.2400, "lon": 121.4800, "name": "fast"},
    ]
    summary = fetcher.fetch_batch(
        coords, str(tmp_path / "out"), coord_concurrency=2
    )

    assert [s["name"] for s in summary] == ["slow", "fast"]
    assert [s["index"] for s in summary] == [1, 2]


def test_fetch_batch_value_error_is_isolated(fetcher_factory, monkeypatch, tmp_path):
    """单个坐标越界抛 ValueError 只影响自身，其余坐标正常汇总。"""
    fetcher = fetcher_factory()

    def _fake_fetch_all(self, lat, lon, zoom=18, output_dir=None,
                        buffer_size=500, date_range=None, dedup=None,
                        emit_events=False, event_coord=None):
        if lat == 999:
            raise ValueError("lat 越界")
        return _success_result()

    monkeypatch.setattr(
        satellite_processor.ImageFetcher, "fetch_all", _fake_fetch_all
    )

    coords = [
        {"lat": 999, "lon": 121.4737, "name": "bad"},
        {"lat": 31.2400, "lon": 121.4800, "name": "good"},
    ]
    summary = fetcher.fetch_batch(
        coords, str(tmp_path / "out"), coord_concurrency=2
    )

    assert len(summary) == 2
    bad, good = summary
    assert bad["name"] == "bad"
    assert bad["total_dates"] == 0
    assert bad["success"] == 0
    assert bad["failed"] == 0
    assert good["name"] == "good"
    assert good["success"] == 1
