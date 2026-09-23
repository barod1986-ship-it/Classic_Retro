from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.model import FontProfile, GlyphMetrics


def test_font_uses_longest_sequence_match():
    font = FontProfile(
        id="fixture",
        line_height_px=8,
        glyphs=(
            GlyphMetrics(id="a", sequence="a", advance_px=4),
            GlyphMetrics(id="ab", sequence="ab", advance_px=6),
            GlyphMetrics(id="b", sequence="b", advance_px=4),
        ),
    )

    resolved = font.resolve_text("ab")

    assert [item.glyph.id for item in resolved] == ["ab"]
    assert sum(item.glyph.advance_px for item in resolved) == 6


def test_missing_glyph_fails_closed():
    font = FontProfile(
        id="fixture",
        line_height_px=8,
        glyphs=(GlyphMetrics(id="a", sequence="a", advance_px=4),),
    )

    with pytest.raises(ClassicRetroError) as caught:
        font.resolve_text("ab")

    assert caught.value.code is ErrorCode.MISSING_GLYPH


def test_duplicate_sequence_is_rejected():
    with pytest.raises(ClassicRetroError) as caught:
        FontProfile(
            id="fixture",
            line_height_px=8,
            glyphs=(
                GlyphMetrics(id="a1", sequence="a", advance_px=4),
                GlyphMetrics(id="a2", sequence="a", advance_px=5),
            ),
        )

    assert caught.value.code is ErrorCode.DUPLICATE_GLYPH_SEQUENCE
