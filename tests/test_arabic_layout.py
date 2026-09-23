from __future__ import annotations

from classic_retro.arabic.pipeline import ArabicPipeline
from classic_retro.font.measure import TextMeasurer
from classic_retro.font.model import FontProfile, GlyphMetrics
from classic_retro.layout.engine import LayoutBox, LayoutEngine
from classic_retro.text.tokens import TextToken, TokenStream


def _font_for_visual_text(text: str) -> FontProfile:
    unique = tuple(dict.fromkeys(text))
    return FontProfile(
        id="arabic-fixture",
        line_height_px=12,
        glyphs=tuple(
            GlyphMetrics(
                id=f"u{ord(character):04x}",
                sequence=character,
                advance_px=5,
            )
            for character in unique
        ),
    )


def test_arabic_lines_are_shaped_and_reordered_per_line():
    logical = TokenStream((TextToken("مرحبا بكم مرحبا بكم"),))
    pipeline = ArabicPipeline()

    whole_visual = pipeline.process(logical).visual.visible_text
    font = _font_for_visual_text(whole_visual)

    engine = LayoutEngine(TextMeasurer(font), arabic=pipeline)
    result = engine.layout(logical, LayoutBox(max_width_px=45))

    assert result.total_lines >= 2
    assert all(line.width_px <= 45 for line in result.pages[0].lines)
    assert all(line.visual.visible_text for line in result.pages[0].lines)
