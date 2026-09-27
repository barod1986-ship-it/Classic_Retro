from __future__ import annotations

import random
import struct
from functools import cache

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.gtzip import (
    FAR_BITS,
    LITERAL_BITS,
    MAX_MATCH,
    MIN_MATCH,
    NEAR,
    NEAR_BITS,
    WINDOW,
    compress_gtzip,
    decode_items,
    decompress_gtzip,
    parse_items,
    read_items,
    repack_gtzip,
    repack_items,
    stream_size,
    write_items,
)
from classic_retro.rebuild.pslz import (
    EXE_HEADER,
    pack_pslz,
    read_pslz,
    repack_pslz,
    unpack_in_place,
    unpack_pslz,
    unpacks_in_place,
)

LOAD = 0x80010000


def _data(seed: int = 3, size: int = 6000) -> bytes:
    """Code-like words from a small set, runs and a table: what the game's files hold."""
    rng = random.Random(seed)
    words = [rng.randrange(1 << 32) for _ in range(48)]
    body = b"".join(struct.pack("<I", rng.choice(words)) for _ in range(size // 8))
    return rng.randbytes(300) + body + bytes(500) + b"invented table " * 30


@pytest.mark.parametrize(
    "data",
    [b"", b"a", b"abcabcabcabc" * 30, bytes(range(256)) * 3, bytes(1000), _data()],
)
def test_gtzip_round_trips(data):
    packed = compress_gtzip(data)
    assert decompress_gtzip(packed, len(data)) == data
    items, end = read_items(packed, len(data))
    assert end == len(packed) and stream_size(items) == len(packed)


def test_a_stream_is_flags_from_the_low_bit_and_items_of_one_two_or_three_bytes():
    # Flags 0b0110: a literal, a near match, a far match (distance 0x81, written
    # 0x80 | 0x00, 0x80), then a literal.
    data = bytes((0b0110, 0x41, 2, 0, 0, 0x80, 0x80, 0x42))
    prefix = bytes(0x80) + b"A"
    items, end = read_items(data, 1 + 5 + 3 + 1)
    assert items == [(1, 0, 0x41), (5, 1, 1), (3, 0x81, 2), (1, 0, 0x42)]
    assert end == len(data)
    # The near match runs on into what it makes: five copies of the byte before.
    assert decode_items(items[:2]) == b"A" * 6
    assert write_items(items) == data
    with pytest.raises(ClassicRetroError) as caught:
        decode_items(items)  # the far match reaches 0x81 back into nothing
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
    assert decode_items([(1, 0, byte) for byte in prefix] + items[2:3])[-3:] == bytes(3)


def test_a_near_distance_may_be_written_in_two_bytes():
    items = [(1, 0, 7), (4, 1, 2)]
    stream = write_items(items)
    assert stream == bytes((0b10, 7, 1, 0x80, 0x00))
    assert read_items(stream, 5) == (items, len(stream))
    assert decode_items(items) == bytes([7] * 5)


def test_broken_streams_are_refused():
    with pytest.raises(ClassicRetroError) as caught:
        decompress_gtzip(bytes((0b1, 5)), 8)
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
    with pytest.raises(ClassicRetroError):
        decompress_gtzip(bytes((0b1, 0, 3)), 3)  # a match with nothing behind it
    with pytest.raises(ClassicRetroError):
        decompress_gtzip(compress_gtzip(b"abcd" * 20), 81)


def _cheapest_bits(data: bytes) -> int:
    """Every match at every distance, by brute force."""
    cost = [0] * (len(data) + 1)
    for position in range(len(data) - 1, -1, -1):
        best = cost[position + 1] + LITERAL_BITS
        for distance in range(1, min(position, WINDOW) + 1):
            length = 0
            while (
                length < MAX_MATCH
                and position + length < len(data)
                and data[position + length] == data[position - distance + length]
            ):
                length += 1
                if length >= MIN_MATCH:
                    bits = NEAR_BITS if distance <= NEAR else FAR_BITS
                    best = min(best, cost[position + length] + bits)
        cost[position] = best
    return cost[0]


@pytest.mark.parametrize("seed", range(6))
def test_the_parse_is_the_cheapest(seed):
    rng = random.Random(seed)
    data = bytes(rng.choice(b"ab\x00") for _ in range(rng.randrange(60, 400)))
    if seed % 2:
        data = rng.randbytes(150) + data + data[:200]  # far matches past 0x80
    items = parse_items(data)
    bits = sum(LITERAL_BITS if not distance else NEAR_BITS if width == 1 else FAR_BITS
               for _, distance, width in items)  # fmt: skip
    assert bits == _cheapest_bits(data)
    assert decode_items(items) == data


def _packed_like_the_game(data: bytes) -> bytes:
    """A stream a little dearer than the cheapest, as the game's packers make: every
    match of 6 or more split in two."""
    items: list[tuple[int, int, int]] = []
    for length, distance, width in parse_items(data):
        if distance and length >= 2 * MIN_MATCH:
            items += [(MIN_MATCH, distance, width), (length - MIN_MATCH, distance, width)]
        else:
            items.append((length, distance, width))
    return write_items(items)


def test_a_repacked_stream_keeps_its_length_and_its_bytes_away_from_the_change():
    data = _data(5, 12000)
    original = _packed_like_the_game(data) + b"\x5a" * 7
    changed = bytearray(data)
    changed[4000:4040] = bytes(range(40))
    repacked = repack_gtzip(original, bytes(changed))
    assert len(repacked) == len(original) and repacked.endswith(b"\x5a" * 7)
    assert decompress_gtzip(repacked, len(changed)) == bytes(changed)
    # The items that make the data before the change stay byte for byte.
    differ = [index for index in range(len(original)) if original[index] != repacked[index]]
    assert differ and min(differ) > len(original) // 4
    # Unchanged data gives the original back.
    assert repack_gtzip(original, data) == original


@pytest.mark.parametrize(("size", "at", "count"), [(12000, 4000, 40), (8000, 5200, 30)])
def test_a_change_that_packs_worse_takes_in_its_neighbours(size, at, count):
    # Random bytes in the middle, whose groups take the next ones in, and near the
    # end, whose groups take the ones before.
    data = _data(8, size)
    items = read_items(_packed_like_the_game(data), len(data))[0]
    changed = bytearray(data)
    changed[at : at + count] = random.Random(2).randbytes(count)
    repacked = repack_items(items, bytes(changed))
    assert decode_items(repacked) == bytes(changed)
    assert stream_size(repacked) == stream_size(items)
    assert repacked[: at // 8] == items[: at // 8]
    # Past what can be saved anywhere, the change is refused; so is any change that
    # costs more to a stream already as cheap as it gets.
    with pytest.raises(ClassicRetroError) as caught:
        repack_items(items, random.Random(4).randbytes(len(data)))
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
    with pytest.raises(ClassicRetroError) as caught:
        repack_items(parse_items(data), bytes(changed))
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
    with pytest.raises(ClassicRetroError):
        repack_items(items, bytes(changed) + b"\x00")


# ---------------------------------------------------------------------------
# PSLZ


def _executable(image: bytes, stored: int, stream: bytes) -> bytes:
    """A PS-X EXE packed like GTMAIN: the stored part, the stream, the header, a stub."""
    stub = bytes(range(0x40))
    text = bytearray(image[:stored] + stream)
    text += bytes(-len(text) % 4)
    header = LOAD + len(text)
    text += struct.pack(
        "<4s6I", b"PSLZ", LOAD + len(image) - 1, len(image), LOAD + stored + len(stream) - 1,
        LOAD + len(image), len(stub), LOAD,
    )  # fmt: skip
    text += stub + bytes(-(len(text) + len(stub)) % 0x800)
    exe = bytearray(EXE_HEADER)
    exe[:8] = b"PS-X EXE"
    struct.pack_into("<IIII", exe, 0x10, header + 0x1C, 0, LOAD, len(text))
    return bytes(exe + text)


@cache
def _image() -> bytes:
    """Its start random (it stays stored), then what packs."""
    return random.Random(9).randbytes(700) + _data(11, 16000) + bytes(3000)


@cache
def _packed() -> bytes:
    image = _image()
    return _executable(image, *pack_pslz(image))


def test_the_stub_unpacks_the_image_above_its_stored_start():
    image, exe = _image(), _packed()
    info = read_pslz(exe)
    assert (info.load, info.image_size, info.entry) == (LOAD, len(image), LOAD)
    stored, _ = pack_pslz(image)
    assert 900 <= stored <= 1000
    assert exe[EXE_HEADER : EXE_HEADER + stored] == image[:stored]
    assert unpack_pslz(exe) == image
    # In one buffer, reading the stream it writes over.
    assert unpack_in_place(exe) == image


def test_other_executables_are_refused():
    exe = bytearray(_packed())
    for broken in (b"not an exe" + bytes(0x800), bytes(exe[:0x800])):
        with pytest.raises(ClassicRetroError) as caught:
            read_pslz(broken)
        assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED
    info = read_pslz(bytes(exe))
    exe[info.offset(info.header) : info.offset(info.header) + 4] = b"PSLY"
    with pytest.raises(ClassicRetroError, match="not packed with PSLZ"):
        read_pslz(bytes(exe))


def test_a_stream_the_stub_would_stop_early_in_is_told_apart():
    # Random bytes decoded last (the image's start) cost more than they make: the
    # saving peaks before the end, and the stub would stop there.
    image = random.Random(1).randbytes(600) + bytes(4000)
    items = parse_items(image[::-1])
    assert not unpacks_in_place(items)
    exe = _executable(image, 0, write_items(items)[::-1])
    assert unpack_in_place(exe) != image
    stored, stream = pack_pslz(image)
    assert stored >= 600 and unpack_in_place(_executable(image, stored, stream)) == image
    with pytest.raises(ClassicRetroError, match="Nothing in the image packs"):
        pack_pslz(random.Random(2).randbytes(300))


def test_a_repacked_executable_keeps_its_layout_and_the_bytes_away_from_the_change():
    image, exe = _image(), _packed()
    changed = bytearray(image)
    changed[5000:5064] = bytes(64)  # decoded late, near the start; it packs cheaper
    changed[100] ^= 0xFF  # in the stored part
    repacked = repack_pslz(exe, bytes(changed))
    assert len(repacked) == len(exe)
    assert unpack_in_place(repacked) == bytes(changed)
    assert read_pslz(repacked) == read_pslz(exe)
    differ = [index for index in range(len(exe)) if exe[index] != repacked[index]]
    # The stored byte, then the stream from the change on; the stream's top,
    # which the image's end (decoded first) comes from, stays.
    assert differ[0] == EXE_HEADER + 100
    info = read_pslz(exe)
    top = info.offset(info.stream_end)
    stream_start = EXE_HEADER + pack_pslz(image)[0]
    assert max(differ) < top - (top - stream_start) // 3
    assert repack_pslz(exe, image) == exe
    with pytest.raises(ClassicRetroError):
        repack_pslz(exe, bytes(changed[:-1]))
