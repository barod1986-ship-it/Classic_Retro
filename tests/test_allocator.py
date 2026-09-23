from __future__ import annotations

from classic_retro.rebuild.allocator import RegionAllocator
from classic_retro.rebuild.model import ByteRange, SafeRegion


def test_allocator_uses_deterministic_best_fit_with_alignment():
    original = bytes([0xFF] * 128)
    allocator = RegionAllocator(
        (
            SafeRegion("large", ByteRange(32, 96), expected_fill_byte=0xFF),
            SafeRegion("small", ByteRange(100, 120), expected_fill_byte=0xFF),
        ),
        original,
    )

    allocation = allocator.allocate(12, alignment=4)

    assert allocation.region_id == "small"
    assert allocation.span == ByteRange(100, 112)
