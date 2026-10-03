from __future__ import annotations

import random
import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.mio0 import (
    HEADER_SIZE,
    MIO0_MAGIC,
    Mio0Block,
    compress_mio0,
    decompress_mio0,
    find_mio0,
    mio0_packed_size,
)

# Assembled by hand, so the format is proven independently of the encoder:
# seven items, 1110100(0) in the layout byte, padded to a 4-byte boundary.
# a, b, c; a 6-byte match at distance 3 (runs on into its own output); x; an
# 18-byte match at distance 1; a 3-byte match at distance 28 (back to "abc").
HAND_ASSEMBLED = bytes(
    [
        0x4D, 0x49, 0x4F, 0x30,  # "MIO0"
        0x00, 0x00, 0x00, 0x1F,  # 31 bytes decompressed
        0x00, 0x00, 0x00, 0x14,  # match stream at 20
        0x00, 0x00, 0x00, 0x1A,  # literal stream at 26
        0xE8, 0x00, 0x00, 0x00,  # layout bits and padding
        0x30, 0x02,  # length 6, distance 3
        0xF0, 0x00,  # length 18, distance 1
        0x00, 0x1B,  # length 3, distance 28
        0x61, 0x62, 0x63, 0x78,  # "abcx"
    ]
)  # fmt: skip
HAND_ASSEMBLED_OUTPUT = b"abcabcabc" + b"x" * 19 + b"abc"


def _header(size: int, match_offset: int, literal_offset: int) -> bytes:
    return MIO0_MAGIC + struct.pack(">III", size, match_offset, literal_offset)


def _items(packed: bytes) -> list[tuple[int, int]]:
    """(length, distance) of every item of a block, (1, 0) for a literal."""
    size, match_offset, literal_offset = struct.unpack_from(">III", packed, 4)
    items: list[tuple[int, int]] = []
    produced = 0
    bit = 0
    while produced < size:
        if packed[HEADER_SIZE + bit // 8] & 0x80 >> bit % 8:
            items.append((1, 0))
            produced += 1
        else:
            first, second = packed[match_offset], packed[match_offset + 1]
            match_offset += 2
            length = (first >> 4) + 3
            items.append((length, ((first & 0xF) << 8 | second) + 1))
            produced += length
        bit += 1
    return items


def _unique_filler(count: int) -> bytes:
    """``count`` bytes without any 3-byte sequence occurring twice (16-bit counters)."""
    return b"".join(value.to_bytes(2, "big") for value in range(-(-count // 2)))[:count]


def test_hand_assembled_stream_decodes():
    assert decompress_mio0(HAND_ASSEMBLED) == HAND_ASSEMBLED_OUTPUT
    assert mio0_packed_size(HAND_ASSEMBLED) == len(HAND_ASSEMBLED)


def test_block_decodes_at_an_offset_and_ignores_what_follows():
    image = b"\xff" * 7 + HAND_ASSEMBLED + b"MIO0 trailing"

    assert decompress_mio0(image, 7) == HAND_ASSEMBLED_OUTPUT
    assert mio0_packed_size(image, 7) == len(HAND_ASSEMBLED)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"a",
        b"abc",
        bytes(4000),
        b"\x5a" * 300 + bytes(300),
        b"abcabcabcabcabcabc" * 40,
        bytes(range(256)) * 9,
        b"The quick brown fox jumps over the lazy dog. " * 30 + b"the lazy fox",
        bytes(random.Random(7).randrange(4) for _ in range(5000)),
        random.Random(11).randbytes(3000),
    ],
)
def test_round_trip(data):
    packed = compress_mio0(data)

    assert packed[:4] == MIO0_MAGIC
    size, match_offset, literal_offset = struct.unpack_from(">III", packed, 4)
    assert size == len(data)
    assert match_offset % 4 == 0
    assert HEADER_SIZE <= match_offset <= literal_offset <= len(packed)
    assert decompress_mio0(packed) == data
    assert mio0_packed_size(packed) == len(packed)


def test_empty_input_is_a_bare_header():
    assert compress_mio0(b"") == _header(0, HEADER_SIZE, HEADER_SIZE)


def test_layout_bits_are_padded_so_the_match_stream_is_aligned():
    # Ten items (two literals, eight matches) need 2 layout bytes, padded to 4.
    data = b"a" + b"b" * (1 + 8 * 18)
    packed = compress_mio0(data)

    size, match_offset, literal_offset = struct.unpack_from(">III", packed, 4)
    assert match_offset == HEADER_SIZE + 4
    assert literal_offset == match_offset + 2 * 8
    assert len(packed) == literal_offset + 2
    assert decompress_mio0(packed) == data


def test_repetitive_data_compresses():
    data = bytes(32) * 64 + b"tile" * 200
    assert len(compress_mio0(data)) < len(data) // 7


def test_a_run_uses_distance_one_and_the_longest_match():
    data = b"\x11" * (1 + 11 * 18)
    packed = compress_mio0(data)

    assert _items(packed) == [(1, 0)] + [(18, 1)] * 11
    assert decompress_mio0(packed) == data


def test_match_at_the_far_edge_of_the_window():
    marker = b"\xff\xfe\xfd"
    data = marker + _unique_filler(4096 - len(marker)) + marker
    packed = compress_mio0(data)

    assert (len(marker), 4096) in _items(packed)
    assert decompress_mio0(packed) == data


def test_no_match_past_the_window():
    marker = b"\xff\xfe\xfd"
    data = marker + _unique_filler(4097 - len(marker)) + marker
    packed = compress_mio0(data)

    assert all(distance == 0 for _, distance in _items(packed))
    assert decompress_mio0(packed) == data


def test_input_larger_than_the_size_field_is_refused():
    class Huge(bytes):
        def __len__(self) -> int:
            return 1 << 32

    with pytest.raises(ClassicRetroError) as caught:
        compress_mio0(Huge())
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED


@pytest.mark.parametrize(
    "packed",
    [
        # wrong magic
        b"MIO1" + HAND_ASSEMBLED[4:],
        # header cut short
        b"MIO0",
        b"MIO0\x00\x00\x00\x1f\x00\x00\x00\x14\x00\x00\x00",
        # stream offsets outside the data
        _header(31, 0x1000, 0x1A) + HAND_ASSEMBLED[HEADER_SIZE:],
        _header(31, 0x14, len(HAND_ASSEMBLED) + 1) + HAND_ASSEMBLED[HEADER_SIZE:],
        # stream offsets inside the header
        _header(31, 8, 0x1A) + HAND_ASSEMBLED[HEADER_SIZE:],
        _header(31, 0x14, 0) + HAND_ASSEMBLED[HEADER_SIZE:],
        # the layout bits run out (a size with no bits to produce it)
        _header(5, HEADER_SIZE, HEADER_SIZE),
        # the match stream runs out (one byte where a match needs two)
        _header(3, 20, 21) + b"\x00\x00\x00\x00" + b"\x00",
        # the literal stream runs out (a literal item with no literal left)
        _header(1, 20, 20) + b"\x80\x00\x00\x00",
        # a match reaching before the start of the output
        _header(3, 20, 22) + b"\x00\x00\x00\x00" + b"\x00\x00",
        _header(31, 0x14, 0x1A) + b"\x68" + HAND_ASSEMBLED[HEADER_SIZE + 1 :],
    ],
)
def test_broken_data_is_rejected(packed):
    with pytest.raises(ClassicRetroError) as caught:
        decompress_mio0(packed)
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
    with pytest.raises(ClassicRetroError):
        mio0_packed_size(packed)


def test_a_header_declaring_four_gigabytes_is_refused_without_allocating():
    with pytest.raises(ClassicRetroError) as caught:
        decompress_mio0(_header(0xFFFFFFFF, HEADER_SIZE, HEADER_SIZE))
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED


def test_offset_outside_the_data_is_refused():
    for offset in (-1, len(HAND_ASSEMBLED) - 3, len(HAND_ASSEMBLED) + 1):
        with pytest.raises(ClassicRetroError) as caught:
            decompress_mio0(HAND_ASSEMBLED, offset)
        assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED


def test_find_mio0_lists_the_blocks_and_skips_false_hits():
    first = b"first block, with some repetition, repetition, repetition"
    second = bytes(range(64)) * 3
    image = (
        b"\x00" * 12
        + compress_mio0(first)
        + b"MIO0 not a block"
        + b"\xff" * 5
        + compress_mio0(second)
        + b"trailing bytes MIO0"
    )
    first_offset = 12
    second_offset = first_offset + len(compress_mio0(first)) + 16 + 5

    blocks = find_mio0(image)

    assert blocks == [
        Mio0Block(first_offset, len(compress_mio0(first)), len(first)),
        Mio0Block(second_offset, len(compress_mio0(second)), len(second)),
    ]
    for block in blocks:
        assert decompress_mio0(image, block.offset) == (first if block is blocks[0] else second)
        assert mio0_packed_size(image, block.offset) == block.packed_size
    assert find_mio0(b"") == []
    assert find_mio0(b"MIO0") == []
