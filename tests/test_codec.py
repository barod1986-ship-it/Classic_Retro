from __future__ import annotations

import pytest

from classic_retro.codec.model import (
    CodecProfile,
    GlyphCode,
    InlineCode,
    TerminatorCode,
    UnknownDecodePolicy,
)
from classic_retro.codec.table import TableTextCodec
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenMovement, TokenStream


def _profile(*, unknown: UnknownDecodePolicy = UnknownDecodePolicy.ERROR) -> CodecProfile:
    return CodecProfile(
        id="fixture",
        glyphs=(
            GlyphCode("H", b"\x01"),
            GlyphCode("i", b"\x02"),
            GlyphCode("!", b"\x03"),
        ),
        inline_codes=(
            InlineCode(
                kind=TokenKind.VARIABLE,
                movement=TokenMovement.FREE,
                name="PLAYER",
                data=b"\xf0\x01",
            ),
            InlineCode(
                kind=TokenKind.CONTROL,
                movement=TokenMovement.ORDERED,
                name="WAIT",
                args={"frames": 30},
                data=b"\xf0\x02",
            ),
        ),
        terminators=(TerminatorCode("end", b"\xff"),),
        unknown_decode=unknown,
    )


def test_fixed_codec_decodes_and_round_trips_exactly():
    codec = TableTextCodec(_profile())
    data = b"\x01\x02\xf0\x01\x03\xf0\x02\xffTRAILING"

    decoded = codec.verify_round_trip(data, require_terminator=True)

    assert decoded.consumed_bytes == 9
    assert decoded.terminator_id == "end"
    assert decoded.stream.visible_text == "Hi!"
    assert [token.name for token in decoded.stream.inline_tokens] == ["PLAYER", "WAIT"]


def test_encode_uses_longest_unicode_sequence():
    profile = CodecProfile(
        id="longest",
        glyphs=(
            GlyphCode("a", b"\x01"),
            GlyphCode("ab", b"\x10"),
            GlyphCode("b", b"\x02"),
        ),
    )

    assert TableTextCodec(profile).encode(TokenStream((TextToken("ab"),))) == b"\x10"


def test_static_byte_codes_must_be_prefix_free():
    with pytest.raises(ClassicRetroError) as caught:
        CodecProfile(
            id="ambiguous",
            glyphs=(
                GlyphCode("a", b"\x01"),
                GlyphCode("b", b"\x01\x02"),
            ),
        )

    assert caught.value.code is ErrorCode.AMBIGUOUS_CODEC_PREFIX


def test_unknown_byte_fails_in_strict_mode():
    codec = TableTextCodec(_profile())

    with pytest.raises(ClassicRetroError) as caught:
        codec.decode(b"\x01\x99")

    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE


def test_unknown_bytes_can_be_preserved_as_opaque_for_research():
    codec = TableTextCodec(_profile(unknown=UnknownDecodePolicy.OPAQUE))
    data = b"\x01\x99\x98\x02"

    decoded = codec.verify_round_trip(data)

    opaque = decoded.stream.inline_tokens[0]
    assert opaque.kind is TokenKind.OPAQUE
    assert opaque.data_hex == "9998"


def test_unconfigured_dynamic_control_is_not_silently_encoded():
    codec = TableTextCodec(_profile())
    stream = TokenStream(
        (
            InlineToken(
                id="wait",
                kind=TokenKind.CONTROL,
                movement=TokenMovement.ORDERED,
                name="WAIT",
                args={"frames": 60},
            ),
        )
    )

    with pytest.raises(ClassicRetroError) as caught:
        codec.encode(stream)

    assert caught.value.code is ErrorCode.UNENCODABLE_TOKEN


def test_required_terminator_is_enforced():
    codec = TableTextCodec(_profile())

    with pytest.raises(ClassicRetroError) as caught:
        codec.decode(b"\x01\x02", require_terminator=True)

    assert caught.value.code is ErrorCode.MISSING_TERMINATOR
