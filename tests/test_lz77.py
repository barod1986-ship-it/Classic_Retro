from __future__ import annotations

import random

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.lz77 import LZ77_TYPE, compress_lz77, decompress_lz77


def _distances(packed: bytes) -> list[int]:
    """Distances of every back-reference in LZ77 data."""
    size = int.from_bytes(packed[1:4], "little")
    produced = 0
    position = 4
    distances = []
    while produced < size:
        flags = packed[position]
        position += 1
        for bit in range(8):
            if produced >= size:
                break
            if flags & 0x80 >> bit:
                token = int.from_bytes(packed[position : position + 2], "big")
                distances.append((token & 0xFFF) + 1)
                produced += (token >> 12) + 3
                position += 2
            else:
                produced += 1
                position += 1
    return distances


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"a",
        b"abcabcabcabcabcabc" * 40,
        bytes(range(256)) * 9,
        bytes(random.Random(7).randrange(4) for _ in range(5000)),
    ],
)
def test_round_trip(data):
    packed = compress_lz77(data)

    assert packed[0] == LZ77_TYPE
    assert int.from_bytes(packed[1:4], "little") == len(data)
    assert len(packed) % 4 == 0
    assert decompress_lz77(packed) == data


def test_repetitive_data_compresses():
    data = bytes(32) * 64 + b"tile" * 200
    assert len(compress_lz77(data)) < len(data) // 8


def test_vram_safe_output_never_copies_the_previous_byte():
    data = b"\x11" * 300 + bytes(300)

    safe = compress_lz77(data)
    assert min(_distances(safe)) >= 2
    assert decompress_lz77(safe) == data

    unsafe = compress_lz77(data, vram_safe=False)
    assert 1 in _distances(unsafe)
    assert decompress_lz77(unsafe) == data


@pytest.mark.parametrize(
    "packed",
    [
        b"\x11\x04\x00\x00abcd",
        b"\x10\x08\x00\x00\x00ab",
        b"\x10\x08\x00\x00\x80\x00",
        b"\x10\x08\x00\x00\x80\x00\x05",
    ],
)
def test_broken_data_is_rejected(packed):
    with pytest.raises(ClassicRetroError) as caught:
        decompress_lz77(packed)
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
