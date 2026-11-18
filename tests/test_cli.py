"""main.py CLI 参数校验测试。

只覆盖进入下载流程之前的校验分支，用子进程真实执行但不会触发任何网络请求。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_main(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # 强制子进程以 UTF-8 输出，避免 Windows 管道编码差异导致断言误判
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("--zoom", "0", "--lat", "0", "--lon", "0"), "zoom 越界"),
        (("--buffer", "10", "--lat", "0", "--lon", "0"), "buffer 越界"),
        (("--coord-concurrency", "0", "--lat", "0", "--lon", "0"),
         "coord-concurrency 越界"),
    ],
)
def test_numeric_range_validation_exits_with_code_2(args, expected):
    result = run_main(*args)

    assert result.returncode == 2
    assert expected in result.stderr
    assert "完成" not in result.stdout


def test_non_history_source_rejects_date_range():
    result = run_main(
        "--source", "esri",
        "--date-range", "2020-01-01", "2021-01-01",
        "--lat", "0", "--lon", "0",
    )

    assert result.returncode == 2
    assert "不支持历史日期" in result.stderr
    assert "--date-range" in result.stderr


def test_coords_file_conflicts_with_lat_lon():
    result = run_main(
        "--lat", "0", "--lon", "0", "--coords-file", "some.csv",
    )

    assert result.returncode == 2
    assert "--coords-file 与 --lat/--lon 不能同时使用" in result.stderr
