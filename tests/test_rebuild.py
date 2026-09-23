from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.model import (
    ByteOrder,
    ByteRange,
    IntegerReferenceCodec,
    RebuildPlan,
    ReferenceSite,
    ResourceSpec,
    SafeRegion,
)
from classic_retro.rebuild.pipeline import extract_resources, rebuild_resources, verify_round_trip


def _plan() -> RebuildPlan:
    return RebuildPlan(
        id="fixture",
        resources=(ResourceSpec("dialogue", ByteRange(8, 12), alignment=2),),
        references=(
            ReferenceSite(
                id="dialogue_ptr",
                offset=0,
                target_resource_id="dialogue",
                codec=IntegerReferenceCodec(
                    size_bytes=2,
                    byte_order=ByteOrder.LITTLE,
                ),
            ),
        ),
        safe_regions=(
            SafeRegion(
                id="safe",
                span=ByteRange(32, 48),
                expected_fill_byte=0xFF,
            ),
        ),
    )


def _image() -> bytes:
    data = bytearray([0xFF] * 64)
    data[0:2] = (8).to_bytes(2, "little")
    data[8:12] = b"ABCD"
    return bytes(data)


def test_extract_rebuild_unchanged_is_byte_exact():
    result = verify_round_trip(_image(), _plan())

    assert result.image == _image()
    assert result.writes == 0
    assert result.relocated_resources == ()


def test_grown_resource_relocates_and_updates_declared_reference():
    payloads = extract_resources(_image(), _plan())
    payloads["dialogue"] = b"LONGER"

    result = rebuild_resources(_image(), _plan(), payloads)

    assert result.placements["dialogue"].rebuilt == ByteRange(32, 38)
    assert result.relocated_resources == ("dialogue",)
    assert result.image[0:2] == (32).to_bytes(2, "little")
    assert result.image[32:38] == b"LONGER"
    assert result.image[8:12] == b"ABCD"


def test_reference_must_point_to_declared_original_resource():
    image = bytearray(_image())
    image[0:2] = (9).to_bytes(2, "little")

    with pytest.raises(ClassicRetroError) as caught:
        verify_round_trip(bytes(image), _plan())

    assert caught.value.code is ErrorCode.REFERENCE_TARGET_MISMATCH


def test_growth_fails_without_declared_safe_space():
    plan = RebuildPlan(
        id="no-space",
        resources=(ResourceSpec("dialogue", ByteRange(8, 12)),),
    )

    with pytest.raises(ClassicRetroError) as caught:
        rebuild_resources(_image(), plan, {"dialogue": b"TOO-LONG"})

    assert caught.value.code is ErrorCode.ALLOCATION_FAILED
