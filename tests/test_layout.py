from __future__ import annotations

import pytest

from classic_retro.arabic.pipeline import ArabicBaseDirection, ArabicPipeline, ArabicPipelineConfig
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.measure import InlineLayoutMetric, InlineMetricResolver, TextMeasurer
from classic_retro.font.model import FontProfile, GlyphMetrics
from classic_retro.layout.engine import LayoutBox, LayoutEngine
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    TokenKind,
    TokenMovement,
    TokenStream,
)


def _ascii_font() -> FontProfile:
    characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,!"
    return FontProfile(
        id="ascii",
        line_height_px=8,
        glyphs=tuple(
            GlyphMetrics(id=f"u{ord(character):04x}", sequence=character, advance_px=4)
            for character in characters
        ),
    )


def _ltr_engine(
    *,
    inline_metrics: InlineMetricResolver | None = None,
) -> LayoutEngine:
    return LayoutEngine(
        TextMeasurer(_ascii_font(), inline_metrics),
        arabic=ArabicPipeline(
            ArabicPipelineConfig(base_direction=ArabicBaseDirection.LTR)
        ),
    )


def test_wraps_at_unicode_line_break_opportunities():
    stream = TokenStream((TextToken("Hello world again"),))

    result = _ltr_engine().layout(stream, LayoutBox(max_width_px=44))

    assert result.total_lines == 2
    assert result.pages[0].lines[0].logical.visible_text == "Hello world"
    assert result.pages[0].lines[1].logical.visible_text == "again"
    assert result.max_width_px <= 44


def test_variable_uses_declared_maximum_width_and_can_break_around_object():
    player = InlineToken(
        id="player",
        kind=TokenKind.VARIABLE,
        movement=TokenMovement.FREE,
        name="PLAYER",
    )
    stream = TokenStream((TextToken("Hello "), player, TextToken(" world")))

    metrics = InlineMetricResolver(
        by_name={"PLAYER": InlineLayoutMetric(advance_px=20)}
    )
    result = _ltr_engine(inline_metrics=metrics).layout(
        stream,
        LayoutBox(max_width_px=44),
    )

    assert result.total_lines >= 2
    assert any(
        token.id == "player"
        for line in result.pages[0].lines
        for token in line.logical.inline_tokens
    )


def test_unknown_variable_width_is_rejected():
    player = InlineToken(
        id="player",
        kind=TokenKind.VARIABLE,
        movement=TokenMovement.FREE,
        name="PLAYER",
    )

    with pytest.raises(ClassicRetroError) as caught:
        _ltr_engine().layout(TokenStream((player,)), LayoutBox(max_width_px=80))

    assert caught.value.code is ErrorCode.INLINE_WIDTH_UNKNOWN


def test_unbreakable_word_overflow_is_rejected():
    stream = TokenStream((TextToken("Hello"),))

    with pytest.raises(ClassicRetroError) as caught:
        _ltr_engine().layout(stream, LayoutBox(max_width_px=8))

    assert caught.value.code is ErrorCode.TEXT_OVERFLOW


def test_manual_page_break_resets_line_limit():
    page = InlineToken(
        id="page",
        kind=TokenKind.PAGE_BREAK,
        movement=TokenMovement.ORDERED,
    )
    stream = TokenStream((TextToken("Hello"), page, TextToken("world")))

    result = _ltr_engine().layout(
        stream,
        LayoutBox(max_width_px=40, max_lines=1),
    )

    assert len(result.pages) == 2
    assert all(len(item.lines) == 1 for item in result.pages)
