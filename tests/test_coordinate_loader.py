"""coordinate_loader.py 的 CSV 解析与命名清洗测试（全部使用 tmp_path，无网络）。"""
from __future__ import annotations

import pytest

from coordinate_loader import (
    CoordinateLoadError,
    _safe_name,
    load_coordinates,
    load_coordinates_file,
)


def _write(tmp_path, name, content, encoding="utf-8"):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding=encoding)
    return path


# ----------------------------------------------------------------------
# 基本解析
# ----------------------------------------------------------------------
def test_load_comma_csv(tmp_path):
    path = _write(
        tmp_path, "points.csv",
        "lat,lon,name,id\n"
        "35.6586,139.7454,Tokyo Tower,t1\n"
        "-33.8568,151.2153,Sydney Opera,s1\n",
    )

    coords = load_coordinates(str(path))

    assert len(coords) == 2
    assert coords[0]["lat"] == pytest.approx(35.6586)
    assert coords[0]["lon"] == pytest.approx(139.7454)
    assert coords[0]["name"] == "Tokyo_Tower"
    assert coords[0]["id"] == "t1"
    assert coords[0]["source"] == "csv"
    assert coords[0]["source_row"] == 1
    assert coords[1]["name"] == "Sydney_Opera"
    assert coords[1]["source_row"] == 2


def test_load_semicolon_csv(tmp_path):
    path = _write(
        tmp_path, "points_semicolon.csv",
        "lat;lon;name\n"
        "48.8584;2.2945;Eiffel Tower\n"
    )

    coords = load_coordinates(str(path))

    assert len(coords) == 1
    assert coords[0]["lat"] == pytest.approx(48.8584)
    assert coords[0]["lon"] == pytest.approx(2.2945)
    assert coords[0]["name"] == "Eiffel_Tower"


def test_load_csv_with_bom(tmp_path):
    content = "\ufefflat,lon,name\n35.0,139.0,BOM Point\n".encode("utf-8")
    path = _write(tmp_path, "bom.csv", content)

    coords = load_coordinates(str(path))

    assert len(coords) == 1
    assert coords[0]["lat"] == pytest.approx(35.0)
    assert coords[0]["lon"] == pytest.approx(139.0)
    assert coords[0]["name"] == "BOM_Point"


def test_header_is_case_insensitive_and_trimmed(tmp_path):
    path = _write(
        tmp_path, "spaced.csv",
        " Lat , LON \n10.0,20.0\n",
    )

    coords = load_coordinates(str(path))

    assert len(coords) == 1
    assert (coords[0]["lat"], coords[0]["lon"]) == (10.0, 20.0)


def test_load_coordinates_file_fills_missing_name_and_id(tmp_path):
    path = _write(
        tmp_path, "noname.csv",
        "lat,lon\n1.0,2.0\n3.0,4.0\n",
    )

    coords = load_coordinates_file(str(path))

    assert [c["name"] for c in coords] == ["point_1", "point_2"]
    assert [c["id"] for c in coords] == ["point_1", "point_2"]


# ----------------------------------------------------------------------
# 错误处理
# ----------------------------------------------------------------------
def test_missing_lat_lon_columns_raises(tmp_path):
    path = _write(tmp_path, "bad_header.csv", "x,y\n1,2\n")

    with pytest.raises(CoordinateLoadError) as excinfo:
        load_coordinates(str(path))

    message = str(excinfo.value)
    assert "表头缺少 lat 或 lon 列" in message
    assert excinfo.value.hint


def test_invalid_number_raises(tmp_path):
    path = _write(tmp_path, "bad_value.csv", "lat,lon\nabc,139.0\n")

    with pytest.raises(CoordinateLoadError) as excinfo:
        load_coordinates(str(path))

    assert "无法解析" in str(excinfo.value)
    assert excinfo.value.path == str(path)


def test_short_row_raises(tmp_path):
    path = _write(tmp_path, "short_row.csv", "lat,lon,name\n35.0\n")

    with pytest.raises(CoordinateLoadError) as excinfo:
        load_coordinates(str(path))

    assert "列数不足" in str(excinfo.value)


def test_empty_file_raises(tmp_path):
    path = _write(tmp_path, "empty.csv", b"")

    with pytest.raises(CoordinateLoadError) as excinfo:
        load_coordinates(str(path))

    assert "CSV 为空" in str(excinfo.value)


def test_nonexistent_file_raises(tmp_path):
    missing = tmp_path / "nope.csv"

    with pytest.raises(CoordinateLoadError):
        load_coordinates_file(str(missing))


def test_unsupported_extension_raises(tmp_path):
    path = _write(tmp_path, "points.txt", "lat,lon\n1,2\n")

    with pytest.raises(CoordinateLoadError) as excinfo:
        load_coordinates_file(str(path))

    assert "不支持的文件格式" in str(excinfo.value)


# ----------------------------------------------------------------------
# _safe_name
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("New York", "New_York"),
        ("a/b", "a_b"),
        ("a//b", "a_b"),
        ("a:b?c", "a_b_c"),
        ("..name..", "name"),
        ("  padded  ", "padded"),
    ],
)
def test_safe_name_cleans_invalid_chars(raw, expected):
    assert _safe_name(raw, "fallback") == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "__", "._."])
def test_safe_name_falls_back_for_empty_values(raw):
    assert _safe_name(raw, "fallback") == "fallback"


def test_safe_name_truncates_long_values():
    result = _safe_name("x" * 100, "fallback")

    assert len(result) == 64
    assert result == "x" * 64
