from __future__ import annotations

import zlib

from classic_retro.rebuild.model import (
    ByteOrder,
    ByteRange,
    IntegerReferenceCodec,
    RebuildPlan,
    ReferenceSite,
    ResourceSpec,
    SafeRegion,
)
from classic_retro.rebuild.transformed import (
    extract_transformed_resources,
    rebuild_transformed_resources,
)
from classic_retro.transform.base import TransformPipeline
from classic_retro.transform.builtin import DeflateTransform


def _fixture():
    packed = zlib.compress(b"HELLO", level=1)
    data = bytearray([0xFF] * 128)
    start = 16
    data[0:2] = start.to_bytes(2, "little")
    data[start : start + len(packed)] = packed

    plan = RebuildPlan(
        id="compressed",
        resources=(
            ResourceSpec(
                "dialogue",
                ByteRange(start, start + len(packed)),
                alignment=4,
            ),
        ),
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
                span=ByteRange(64, 112),
                expected_fill_byte=0xFF,
            ),
        ),
    )
    pipeline = TransformPipeline(
        "zlib-dialogue",
        (DeflateTransform("zlib", wbits=15, level=9),),
    )
    return bytes(data), plan, pipeline


def test_unchanged_transformed_resource_keeps_entire_image_exact():
    original, plan, pipeline = _fixture()
    extraction = extract_transformed_resources(
        original,
        plan,
        {"dialogue": pipeline},
    )

    result = rebuild_transformed_resources(
        original,
        plan,
        extraction,
        extraction.payloads,
        {"dialogue": pipeline},
    )

    assert result.image == original
    assert result.writes == 0


def test_changed_compressed_resource_can_relocate_and_update_reference():
    original, plan, pipeline = _fixture()
    extraction = extract_transformed_resources(
        original,
        plan,
        {"dialogue": pipeline},
    )
    edited = dict(extraction.payloads)
    edited["dialogue"] = b"THIS IS A MUCH LONGER TRANSLATED RESOURCE" * 2

    result = rebuild_transformed_resources(
        original,
        plan,
        extraction,
        edited,
        {"dialogue": pipeline},
    )

    placement = result.placements["dialogue"]
    assert placement.relocated is True
    assert placement.rebuilt.start == 64
    assert int.from_bytes(result.image[0:2], "little") == 64
    assert zlib.decompress(result.image[placement.rebuilt.start : placement.rebuilt.end]) == edited[
        "dialogue"
    ]
