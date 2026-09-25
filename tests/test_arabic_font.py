from __future__ import annotations

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image, features

from classic_retro.core.errors import ClassicRetroError
from classic_retro.engines import pokemon_gen3_arabic as arabic


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: logical Arabic cmap + OpenType forms, no FE8x cmap."""
    names = [".notdef", "space", "beh", "beh.init", "beh.medi", "beh.fina"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x628: "beh"})
    glyphs = {}
    for index, name in enumerate(names):
        pen = TTGlyphPen(None)
        if name != "space":
            pen.moveTo((0, 0))
            pen.lineTo((100 + index * 60, 0))
            pen.lineTo((100 + index * 60, 500))
            pen.lineTo((0, 500))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(dict.fromkeys(names, (500, 0)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Classic Retro Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "contextual.ttf"
    builder.save(path)
    return path


def test_opentype_font_without_presentation_cmap_renders_four_distinct_forms(
    contextual_font, tmp_path, monkeypatch
):
    monkeypatch.setattr(features, "check_feature", lambda feature: False)
    characters = ("\ufe8f", "\ufe90", "\ufe91", "\ufe92")
    glyphs = arabic.firered_glyph_codes(characters)
    atlas_path = tmp_path / "font.png"
    widths_path = tmp_path / "widths.bin"
    result = arabic.build_arabic_font_atlas(
        contextual_font, atlas_path, widths_path, glyph_map=glyphs
    )
    atlas = Image.open(atlas_path)
    cells = [atlas.crop((index * 16, 0, index * 16 + 16, 16)) for index in range(4)]
    assert len({cell.tobytes() for cell in cells}) == 4
    assert result.glyphs == 4
    for character, cell, width in zip(characters, cells, widths_path.read_bytes(), strict=True):
        arabic._validate_fire_red_glyph_bounds(cell, width, character)
        ink = [(x, y) for y in range(16) for x in range(16) if cell.getpixel((x, y)) == 1]
        if character in ("\ufe91", "\ufe92"):
            assert min(x for x, _ in ink) == 0
        if character in ("\ufe90", "\ufe92"):
            assert max(x for x, _ in ink) == width - 1


def test_font_missing_arabic_letters_is_rejected_before_writing(contextual_font, tmp_path):
    atlas = tmp_path / "font.png"
    with pytest.raises(ClassicRetroError, match="has no Arabic glyph"):
        arabic.build_arabic_font_atlas(contextual_font, atlas, tmp_path / "widths.bin")
    assert not atlas.exists()


def test_context_font_does_not_modify_original_file(contextual_font):
    before = contextual_font.read_bytes()
    data = arabic._contextual_font_data(contextual_font, ("\ufe91",))
    assert data != before
    assert contextual_font.read_bytes() == before


def test_invalid_font_has_an_actionable_error(tmp_path):
    path = tmp_path / "invalid.ttf"
    path.write_bytes(b"not a font")
    with pytest.raises(ClassicRetroError, match="Invalid TTF/OTF"):
        arabic.build_arabic_font_atlas(path, tmp_path / "font.png", tmp_path / "widths.bin")
