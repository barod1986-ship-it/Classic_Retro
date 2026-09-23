from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.model import (
    ByteOrder,
    IntegerReferenceCodec,
    ReferenceBaseKind,
)


def test_gba_style_absolute_pointer_affine_mapping():
    codec = IntegerReferenceCodec(
        size_bytes=4,
        byte_order=ByteOrder.LITTLE,
        base_kind=ReferenceBaseKind.CONSTANT,
        base_value=-0x08000000,
    )

    encoded = codec.encode(0x1234, site_offset=0x100)

    assert encoded == bytes.fromhex("34120008")
    assert codec.decode(encoded, site_offset=0x100) == 0x1234


def test_constant_relative_pointer():
    codec = IntegerReferenceCodec(
        size_bytes=2,
        byte_order=ByteOrder.LITTLE,
        base_kind=ReferenceBaseKind.CONSTANT,
        base_value=0x1000,
    )

    assert codec.encode(0x1234, site_offset=0) == bytes.fromhex("3402")
    assert codec.decode(bytes.fromhex("3402"), site_offset=0) == 0x1234


def test_pc_relative_pointer_uses_reference_site():
    codec = IntegerReferenceCodec(
        size_bytes=2,
        byte_order=ByteOrder.LITTLE,
        base_kind=ReferenceBaseKind.SITE,
    )

    assert codec.encode(0x250, site_offset=0x200) == bytes.fromhex("5000")
    assert codec.decode(bytes.fromhex("5000"), site_offset=0x200) == 0x250


def test_scaled_reference_rejects_unrepresentable_target():
    codec = IntegerReferenceCodec(
        size_bytes=2,
        byte_order=ByteOrder.LITTLE,
        scale=2,
    )

    with pytest.raises(ClassicRetroError) as caught:
        codec.encode(3, site_offset=0)

    assert caught.value.code is ErrorCode.REFERENCE_ALIGNMENT_ERROR
