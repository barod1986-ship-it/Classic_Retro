from __future__ import annotations

import unicodedata

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen3_arabic import (
    ARABIC_SLOT_FIRST,
    ARABIC_SLOT_LAST,
    PokemonGen3ArabicEncoder,
    build_arabic_glyph_map,
)
from classic_retro.text.tokens import TextToken, TokenStream


def test_arabic_glyph_map_uses_only_reserved_extra_symbol_range():
    glyph_map = build_arabic_glyph_map()

    assert glyph_map.first_slot == ARABIC_SLOT_FIRST
    assert glyph_map.last_slot <= ARABIC_SLOT_LAST
    assert len(glyph_map.characters) == len(set(glyph_map.characters))
    assert all(glyph_map.encode(character)[0] == 0xF9 for character in glyph_map.characters)


def test_logical_arabic_encodes_to_rtl_control_and_extra_symbols():
    encoder = PokemonGen3ArabicEncoder()

    data = encoder.encode_message(
        TokenStream((TextToken("مرحبا 123"),)),
        right_x=220,
        terminator=True,
    )

    assert data[:3] == bytes.fromhex("fc19dc")
    assert data[-3:] == bytes.fromhex("fc1aff")
    assert 0xF9 in data


def test_arabic_combining_marks_fail_instead_of_disappearing():
    encoder = PokemonGen3ArabicEncoder()
    assert unicodedata.combining("\u064e")

    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode_message(
            TokenStream((TextToken("مَر"),)),
            right_x=220,
        )

    assert caught.value.code is ErrorCode.UNSUPPORTED_ARABIC_MARK
