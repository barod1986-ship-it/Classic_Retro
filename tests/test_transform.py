from __future__ import annotations

import zlib

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.transform.base import TransformPipeline
from classic_retro.transform.builtin import DeflateTransform, IdentityTransform
from classic_retro.transform.profile import TransformProfile, TransformStageSpec, build_pipeline
from classic_retro.transform.registry import build_transform_registry


def test_unchanged_payload_reuses_original_encoded_bytes():
    original = zlib.compress(b"HELLO HELLO HELLO", level=1)
    pipeline = TransformPipeline(
        "zlib-fixture",
        (DeflateTransform("zlib", wbits=15, level=9),),
    )

    payload, snapshot = pipeline.extract(original)
    rebuilt = pipeline.rebuild(snapshot, payload)

    assert rebuilt == original


def test_changed_payload_is_reencoded_and_verified():
    original = zlib.compress(b"HELLO", level=1)
    pipeline = TransformPipeline(
        "zlib-fixture",
        (DeflateTransform("zlib", wbits=15, level=9),),
    )
    _, snapshot = pipeline.extract(original)

    rebuilt = pipeline.rebuild(snapshot, b"HELLO WORLD")

    assert rebuilt != original
    assert zlib.decompress(rebuilt) == b"HELLO WORLD"


def test_transform_chain_round_trips_in_reverse_order():
    inner = zlib.compress(b"CHAIN", level=9)
    original = zlib.compress(inner, level=9)
    pipeline = TransformPipeline(
        "double-zlib",
        (
            DeflateTransform("outer", wbits=15),
            DeflateTransform("inner", wbits=15),
        ),
    )

    payload, snapshot = pipeline.extract(original)
    rebuilt = pipeline.rebuild(snapshot, b"CHAIN CHANGED")

    assert payload == b"CHAIN"
    decoded_outer = zlib.decompress(rebuilt)
    assert zlib.decompress(decoded_outer) == b"CHAIN CHANGED"


def test_output_limit_blocks_excessive_decompression():
    data = zlib.compress(b"A" * 1024)
    pipeline = TransformPipeline(
        "limited",
        (DeflateTransform("zlib", wbits=15, max_output_bytes=100),),
    )

    with pytest.raises(ClassicRetroError) as caught:
        pipeline.extract(data)

    assert caught.value.code is ErrorCode.TRANSFORM_OUTPUT_LIMIT


def test_profile_builds_builtin_pipeline():
    profile = TransformProfile(
        id="fixture",
        stages=(
            TransformStageSpec(codec="identity"),
            TransformStageSpec(codec="zlib", options={"level": 6}),
        ),
    )
    registry = build_transform_registry(load_external=False)

    pipeline = build_pipeline(profile, registry)

    assert [transform.id for transform in pipeline.transforms] == ["identity", "zlib"]


def test_snapshot_cannot_be_used_with_another_pipeline():
    pipeline = TransformPipeline("first", (IdentityTransform(),))
    payload, snapshot = pipeline.extract(b"ABC")
    other = TransformPipeline("second", (IdentityTransform(),))

    with pytest.raises(ClassicRetroError) as caught:
        other.rebuild(snapshot, payload)

    assert caught.value.code is ErrorCode.TRANSFORM_SNAPSHOT_MISMATCH
