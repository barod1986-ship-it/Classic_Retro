from __future__ import annotations

import random

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
