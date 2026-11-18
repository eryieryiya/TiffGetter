"""Google Earth 数据包解析的离线测试（全部使用合成字节）。"""

import pytest

from providers.google_earth_client import (
    ProtobufParser,
    encode_ge_date,
    parse_quadtree_packet,
)


# ---------------------------------------------------------------------------
# 编码辅助
# ---------------------------------------------------------------------------
def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _varint_field(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def _bytes_field(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def _group_field(field: int, payload: bytes) -> bytes:
    return _tag(field, 3) + payload + _tag(field, 4)


def _dated_tile(date: int, epoch: int = 11, provider: int = 2) -> bytes:
    return (
        _varint_field(1, date)
        + _varint_field(2, epoch)
        + _varint_field(3, provider)
    )


def _layer(date: int, layer_type: int = 3, layer_epoch: int = 22) -> bytes:
    dates = _bytes_field(1, _dated_tile(date))
    return (
        _varint_field(1, layer_type)
        + _varint_field(2, layer_epoch)
        + _bytes_field(4, dates)
    )


def _node(flags: int, cache_epoch: int, layer: bytes) -> bytes:
    return (
        _varint_field(1, flags)
        + _varint_field(2, cache_epoch)
        + _bytes_field(3, layer)
    )


def _sparse_node(index: int, node: bytes) -> bytes:
    return _varint_field(3, index) + _bytes_field(4, node)


# ---------------------------------------------------------------------------
# ProtobufParser 原语
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 16384, (1 << 21) - 1])
def test_read_varint(value):
    parser = ProtobufParser(_varint(value))
    assert parser.read_varint() == value
    assert parser.offset == len(parser.data)
    assert parser.has_more() is False


def test_read_tag_splits_field_and_wire_type():
    parser = ProtobufParser(_tag(5, 2) + b"\x00")
    assert parser.read_tag() == (5, 2)


def test_read_bytes_honors_length_prefix():
    payload = b"hello-protobuf"
    parser = ProtobufParser(_varint(len(payload)) + payload + b"tail")
    assert parser.read_bytes() == payload
    assert parser.data[parser.offset:] == b"tail"


def test_skip_field_varint_then_read_next():
    parser = ProtobufParser(_varint_field(1, 300) + _varint_field(2, 9))
    assert parser.read_tag() == (1, 0)
    parser.skip_field(0)
    assert parser.read_tag() == (2, 0)
    assert parser.read_varint() == 9


def test_skip_field_fixed64_and_fixed32():
    parser = ProtobufParser(
        _tag(1, 1) + b"\x01" * 8 + _tag(2, 5) + b"\x02" * 4 + _varint_field(3, 7)
    )
    field, wire = parser.read_tag()
    parser.skip_field(wire)
    field, wire = parser.read_tag()
    parser.skip_field(wire)
    assert (field, wire) == (2, 5)
    assert parser.read_tag() == (3, 0)
    assert parser.read_varint() == 7


def test_skip_field_length_delimited():
    parser = ProtobufParser(_bytes_field(1, b"abc") + _varint_field(2, 4))
    assert parser.read_tag() == (1, 2)
    parser.skip_field(2)
    assert parser.read_tag() == (2, 0)
    assert parser.read_varint() == 4


def test_read_group_consumes_until_end_tag():
    body = _varint_field(1, 5) + _bytes_field(2, b"xy")
    data = body + _tag(9, 4) + b"after"
    parser = ProtobufParser(data)
    group = parser.read_group(9)
    assert group[: len(body)] == body
    assert group[-1:] == _tag(9, 4)
    assert parser.data[parser.offset:] == b"after"


# ---------------------------------------------------------------------------
# 最小可解析数据包
# ---------------------------------------------------------------------------
def _minimal_packet() -> bytes:
    date = encode_ge_date(2023, 6, 15)
    packet = _varint_field(1, 1234)
    # 普通 group 节点（wire type 3）
    packet += _group_field(
        2, _sparse_node(5, _node(7, 42, _layer(date, layer_type=3)))
    )
    # length-delimited 形式的节点（wire type 2）
    packet += _bytes_field(
        2, _sparse_node(9, _node(3, 0, _layer(date, layer_type=0)))
    )
    return packet


def test_parse_minimal_packet():
    epoch, nodes = parse_quadtree_packet(_minimal_packet())

    assert epoch == 1234
    assert set(nodes) == {5, 9}

    group_node = nodes[5]
    assert group_node.index == 5
    assert group_node.flags == 7
    assert group_node.cache_node_epoch == 42
    assert len(group_node.layers) == 1

    layer = group_node.layers[0]
    assert layer.type == 3
    assert layer.layer_epoch == 22
    assert len(layer.dated_tiles) == 1

    dated = layer.dated_tiles[0]
    assert (dated.year, dated.month, dated.day) == (2023, 6, 15)
    assert dated.hex_date == format(encode_ge_date(2023, 6, 15), "x")

    plain_node = nodes[9]
    assert plain_node.index == 9
    assert plain_node.flags == 3
    assert plain_node.cache_node_epoch == 0
    assert plain_node.layers[0].type == 0


def test_parse_packet_skips_unknown_fields():
    data = (
        _varint_field(1, 77)
        + _varint_field(15, 555)
        + _tag(16, 1)
        + b"\x00" * 8
        + _tag(17, 5)
        + b"\x00" * 4
        + _group_field(
            2, _sparse_node(1, _node(1, 2, _layer(encode_ge_date(2021, 3, 4))))
        )
    )
    epoch, nodes = parse_quadtree_packet(data)
    assert epoch == 77
    assert set(nodes) == {1}
    assert nodes[1].layers[0].dated_tiles[0].date == encode_ge_date(2021, 3, 4)


def test_sparse_node_without_node_data_is_ignored():
    data = _group_field(2, _varint_field(3, 5))
    epoch, nodes = parse_quadtree_packet(data)
    assert epoch == 0
    assert nodes == {}


# ---------------------------------------------------------------------------
# 空 / 截断输入
# ---------------------------------------------------------------------------
def test_empty_packet_returns_empty_result():
    assert parse_quadtree_packet(b"") == (0, {})
    assert ProtobufParser(b"").has_more() is False


@pytest.mark.parametrize(
    "data",
    [
        b"\x08",              # 字段 1 只有 tag，没有 varint 值
        b"\x13",              # group 开始但立即结束
        b"\x13\x18",          # group 内 index 缺少取值
        b"\x13\x18\x05",      # group 没有 end tag
        b"\x12\x05\x00",      # length 声明 5 字节但只给 1 字节
        b"\x22\xff",          # 长度 varint 被截断
        b"\x13\x22\xff\x00",  # group 内节点长度被截断
    ],
)
def test_truncated_packet_does_not_crash(data):
    epoch, nodes = parse_quadtree_packet(data)
    assert isinstance(epoch, int)
    assert isinstance(nodes, dict)
