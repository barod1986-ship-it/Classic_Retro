from __future__ import annotations

import random
import zlib

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.bps import BPS_MAGIC, apply_bps, create_bps


def _random(size: int, seed: int) -> bytes:
    generator = random.Random(seed)
    return bytes(generator.getrandbits(8) for _ in range(size))


def test_identical_image_is_one_source_read():
    source = _random(4096, 1)
    patch = create_bps(source, source)

    assert patch.data.startswith(BPS_MAGIC)
    assert len(patch.data) < 32
    assert apply_bps(patch.data, source) == source


def test_edits_moves_runs_and_growth_round_trip():
    source = _random(200_000, 2)
    target = bytearray(source)
    target[1000:1010] = b"0123456789"
    target += source[5000:60_000]
    target += b"\xff" * 100_000
    target += _random(777, 3)
    target = bytes(target)

    patch = create_bps(source, target, metadata=b"classic-retro")

    assert apply_bps(patch.data, source) == target
    # Moved data and the fill run are copies, not literals.
    assert len(patch.data) < 2_000
    assert patch.source_size == len(source) and patch.target_size == len(target)


def test_moved_data_is_found_only_in_the_ranges_given():
    # A file moved to the end of the image, as a disc overlay moves one.
    source = _random(100_000, 8) + bytes(20_000)
    moved = source[30_000:40_000]
    target = source[:100_000] + moved + bytes(10_000)
    near = create_bps(source, target, copy_from=((30_000, 40_000),))
    elsewhere = create_bps(source, target, copy_from=((0, 16),))
    for patch in (near, elsewhere, create_bps(source, target)):
        assert apply_bps(patch.data, source) == target
    # Only the ranges are indexed: the move is a copy from them, a literal otherwise.
    assert len(near.data) < 100 < len(moved) < len(elsewhere.data)
    # A range may start inside a block and end past the source.
    unaligned = create_bps(source, target, copy_from=((29_990, 1_000_000),))
    assert len(unaligned.data) < 100


def test_shrinking_target_round_trips():
    source = _random(5000, 4)
    target = source[100:3000]
    assert apply_bps(create_bps(source, target).data, source) == target


def test_patch_for_another_source_is_refused():
    source = _random(1024, 5)
    patch = create_bps(source, source[::-1])
    with pytest.raises(ClassicRetroError) as caught:
        apply_bps(patch.data, _random(1024, 6))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


def test_corrupted_patch_is_refused():
    source = _random(1024, 7)
    data = bytearray(create_bps(source, source[::-1]).data)
    data[10] ^= 0x01
    with pytest.raises(ClassicRetroError) as caught:
        apply_bps(bytes(data), source)
    assert caught.value.code is ErrorCode.INVALID_REBUILD_PAYLOAD


# ---------------------------------------------------------------------------
# Reading patches assembled by hand, without the encoder. A BPS number below
# 128 is one byte, 0x80 | value; a command is (length - 1) << 2 | kind, the
# kinds being SourceRead 0, TargetRead 1, SourceCopy 2 and TargetCopy 3; a
# copy's offset is (magnitude << 1) | negative, relative to the last copy's end.


def _number(value: int) -> bytes:
    """A BPS number: 7 bits a byte, low bits first, one less per continuation byte."""
    output = bytearray()
    while value >= 0x80:
        output.append(value & 0x7F)
        value = (value >> 7) - 1
    return bytes(output) + bytes([0x80 | value])


def _hand_made(
    source: bytes, target: bytes, commands: bytes, *, target_size: int | None = None
) -> bytes:
    """The header, the commands and the CRC32 trailer the reader checks.

    ``target_size`` declares a target size other than the real one; the
    target CRC is then whatever the reader never gets to check.
    """
    sizes = _number(len(source)) + _number(len(target) if target_size is None else target_size)
    patch = BPS_MAGIC + sizes + b"\x80" + commands
    patch += zlib.crc32(source).to_bytes(4, "little") + zlib.crc32(target).to_bytes(4, "little")
    return patch + zlib.crc32(patch).to_bytes(4, "little")


def test_an_overlapping_target_copy_repeats_the_pattern():
    # TargetRead of "xyabc", then TargetCopy of 10 bytes from +2 in the output:
    # 3 bytes before its end, so the copy reads what it has just written and
    # repeats "abc" with a period of 3.
    commands = bytes([0x80 | 4 << 2 | 1]) + b"xyabc" + bytes([0x80 | 9 << 2 | 3, 0x80 | 2 << 1])
    target = b"xyabc" + b"abcabcabca"
    assert apply_bps(_hand_made(b"ROM", target, commands), b"ROM") == target


def test_source_copy_offsets_are_relative_and_may_go_backwards():
    source = b"0123456789ABCDEF"
    # SourceCopy of 4 bytes from +10 ("ABCD") leaves the source pointer at 14;
    # the next SourceCopy of 5 bytes from -12 reads "23456" at 2.
    commands = bytes([0x80 | 3 << 2 | 2, 0x80 | 10 << 1, 0x80 | 4 << 2 | 2, 0x80 | 12 << 1 | 1])
    target = b"ABCD" + b"23456"
    assert apply_bps(_hand_made(source, target, commands), source) == target


def _refused(patch: bytes, source: bytes) -> ClassicRetroError:
    with pytest.raises(ClassicRetroError) as caught:
        apply_bps(patch, source)
    return caught.value


@pytest.mark.parametrize("length", [2**44, 2**64])
def test_an_action_longer_than_the_room_left_is_refused_before_it_is_built(length):
    # TargetRead of "A", then a TargetCopy of `length` bytes into a target
    # declared as 2 bytes: refused on the declared size, with nothing built.
    commands = bytes([0x80 | 0 << 2 | 1]) + b"A" + _number((length - 1) << 2 | 3) + b"\x80"
    error = _refused(_hand_made(b"ROM", b"AA", commands), b"ROM")
    assert error.code is ErrorCode.INVALID_REBUILD_PAYLOAD
    assert str(error) == "BPS output overflow"


def test_a_target_copy_builds_exactly_its_length():
    # The 10-byte copy repeats "abc" with a period of 3 (the pattern test above);
    # a copy of 7 bytes from the same period must stop at 7, not at a whole period.
    commands = bytes([0x80 | 4 << 2 | 1]) + b"xyabc" + bytes([0x80 | 6 << 2 | 3, 0x80 | 2 << 1])
    target = b"xyabc" + b"abcabca"
    assert apply_bps(_hand_made(b"ROM", target, commands), b"ROM") == target


@pytest.mark.parametrize("declared", [2**62, 2**64])
def test_a_declared_target_too_large_for_memory_is_refused(declared):
    # The patch honestly declares its target and fills it with one TargetCopy:
    # the output cannot exist, so the reader refuses it instead of crashing.
    commands = bytes([0x80 | 0 << 2 | 1]) + b"A" + _number((declared - 2) << 2 | 3) + b"\x80"
    error = _refused(_hand_made(b"ROM", b"A", commands, target_size=declared), b"ROM")
    assert error.code is ErrorCode.INVALID_REBUILD_PAYLOAD
    assert str(declared) in str(error)


def test_a_number_without_an_end_is_refused_at_once():
    # 200,000 continuation bytes: a well-formed number ends within 10.
    patch = BPS_MAGIC + bytes(200_000)
    patch += zlib.crc32(b"ROM").to_bytes(4, "little") + bytes(4)
    patch += zlib.crc32(patch).to_bytes(4, "little")
    error = _refused(patch, b"ROM")
    assert error.code is ErrorCode.INVALID_REBUILD_PAYLOAD
    assert "number" in str(error).lower()


def test_a_number_is_not_read_out_of_the_footer():
    # Seven continuation bytes run straight into the CRC footer, whose bytes
    # must not be taken for the end of the number.
    patch = BPS_MAGIC + bytes(7)
    patch += zlib.crc32(b"ROM").to_bytes(4, "little") + bytes(4)
    patch += zlib.crc32(patch).to_bytes(4, "little")
    error = _refused(patch, b"ROM")
    assert error.code is ErrorCode.INVALID_REBUILD_PAYLOAD
    assert "number" in str(error).lower()
