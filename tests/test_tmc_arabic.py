from __future__ import annotations

import re

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tmc import glyph_advance, tmc_jump, tmc_line, tmc_player
from classic_retro.engines.tmc_arabic import (
    BASELINE_PUNCTUATION,
    GLYPH_BYTES,
    RTL_OFF_NOTATION,
    RTL_ON_NOTATION,
    TmcArabicEncoder,
    TmcArabicGlyphMap,
    build_tmc_arabic_font,
    build_tmc_arabic_glyph_map,
)
from classic_retro.text.tokens import TextToken, TokenStream

_GLYPH = re.compile(r"\{04:18:([0-9A-F]{2})\}")


def _encoder(width: int = 6) -> TmcArabicEncoder:
    glyph_map = build_tmc_arabic_glyph_map()
    return TmcArabicEncoder(
        arabic_widths=dict.fromkeys(glyph_map.characters, width),
        latin_widths={" ": 4, "!": 3, ".": 5, "A": 6},
        player_width=48,
    )


def _slots(notation: str) -> list[int]:
    return [int(value, 16) for value in _GLYPH.findall(notation)]


def test_glyph_map_fits_the_arabic_font_page():
    glyph_map = build_tmc_arabic_glyph_map()

    assert len(glyph_map.characters) <= 0x100
    assert len(set(glyph_map.characters)) == len(glyph_map.characters)
    assert set(BASELINE_PUNCTUATION) <= set(glyph_map.characters)
    beh_initial = glyph_map.slots["\ufe91"]
    assert glyph_map.notation("\ufe91") == "{04:18:" + format(beh_initial, "02X") + "}"
    assert glyph_map.notation("A") is None


def test_message_is_wrapped_in_rtl_on_and_off():
    notation = _encoder().encode_message(TokenStream((TextToken("مرحبا"),)))

    assert notation.startswith(RTL_ON_NOTATION)
    assert notation.endswith(RTL_OFF_NOTATION)
    assert len(_slots(notation)) == 5


def test_text_is_stored_in_right_to_left_paint_order():
    glyph_map = build_tmc_arabic_glyph_map()
    notation = _encoder().encode_message(TokenStream((TextToken("بب"),)))

    # Logical beh + beh: the right-hand glyph (initial form) is painted first.
    assert _slots(notation) == [glyph_map.slots["\ufe91"], glyph_map.slots["\ufe90"]]


def test_numbers_and_latin_keep_their_reading_order_inside_arabic():
    notation = _encoder().encode_message(TokenStream((TextToken("رقم 12"),)))
    body = notation[len(RTL_ON_NOTATION) : -len(RTL_OFF_NOTATION)]

    # Painted from the right edge leftwards: the Arabic word first, then "21".
    assert body.endswith(" 21")


def test_runtime_player_name_keeps_execution_order():
    notation = _encoder().encode_message(
        TokenStream((TextToken("أين "), tmc_player("p"), TextToken("؟")))
    )
    player = notation.index("{Player}")
    question = build_tmc_arabic_glyph_map().notation("؟")

    assert notation.index(question) > player
    assert len(_slots(notation[:player])) == 3


def test_rtl_is_switched_off_before_continuing_with_another_text():
    notation = _encoder().encode_message(
        TokenStream((TextToken("نعم"), tmc_line("l"), tmc_jump("j", 0x10, 0x05)))
    )

    assert notation.endswith("\n" + RTL_OFF_NOTATION + "{07:10:05}" + RTL_OFF_NOTATION)


def test_sentence_punctuation_uses_arabic_baseline_glyphs():
    glyph_map = build_tmc_arabic_glyph_map()
    notation = _encoder().encode_message(TokenStream((TextToken("نعم."),)))

    assert _slots(notation)[-1] == glyph_map.slots["."]


@pytest.mark.parametrize("text", ["مَرحبا", "قال (نعم)"])
def test_marks_and_mirrored_brackets_are_rejected(text):
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(TokenStream((TextToken(text),)))
    assert caught.value.code in {ErrorCode.UNSUPPORTED_ARABIC_MARK, ErrorCode.UNENCODABLE_TEXT}


def test_line_measurement_bounds_runtime_names_and_rejects_overflow():
    encoder = _encoder(width=10)
    stream = TokenStream((TextToken("بببب "), tmc_player("p"), tmc_line("l"), TextToken("ب")))

    lines = encoder.line_widths(stream)
    assert [line.width for line in lines] == [4 * 10 + 4 + 48, 10]
    assert lines[0].dynamic == ("PLAYER",)

    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode_message(stream, line_width=80)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


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


def _ink_columns(glyph: bytes) -> set[int]:
    columns = set()
    for half in range(2):
        for row in range(16):
            for column in range(8):
                value = glyph[half * 64 + row * 4 + column // 2]
                nibble = value & 0xF if column % 2 == 0 else value >> 4
                if nibble == 0xE:
                    columns.add(half * 8 + column)
    return columns


def test_font_matches_engine_width_markers_and_joining_edges(contextual_font):
    characters = ("\ufe8f", "\ufe90", "\ufe91", "\ufe92", ".", "!")
    glyph_map = TmcArabicGlyphMap(
        characters=characters,
        slots={character: index for index, character in enumerate(characters)},
    )
    result = build_tmc_arabic_font(contextual_font, glyph_map=glyph_map)

    assert result.glyphs == len(characters)
    assert len(result.data) == len(characters) * GLYPH_BYTES
    assert 1 <= result.baseline <= 16
    for index, character in enumerate(characters):
        glyph = result.data[index * GLYPH_BYTES : (index + 1) * GLYPH_BYTES]
        first, second = glyph_advance(glyph[:64]), glyph_advance(glyph[64:])
        width = result.widths[character]
        # The engine adds both halves; a glyph wider than 8px fills the first half.
        assert first + second == width
        assert second == 0 or first == 8
        ink = _ink_columns(glyph)
        assert ink and max(ink) < width and min(ink) == 0
        # Row 0 is the engine's width marker: never ink.
        marker_nibbles = [
            nibble
            for half in range(2)
            for value in glyph[half * 64 : half * 64 + 4]
            for nibble in (value & 0xF, value >> 4)
        ]
        assert 0xE not in marker_nibbles
    # Right-joining forms (medial/final) reach their right edge.
    for character in ("\ufe90", "\ufe92"):
        index = characters.index(character)
        glyph = result.data[index * GLYPH_BYTES : (index + 1) * GLYPH_BYTES]
        assert max(_ink_columns(glyph)) == result.widths[character] - 1
    # Non-joining right sides keep a gap towards the previous glyph.
    for character in ("\ufe8f", "\ufe91", "."):
        index = characters.index(character)
        glyph = result.data[index * GLYPH_BYTES : (index + 1) * GLYPH_BYTES]
        assert max(_ink_columns(glyph)) < result.widths[character] - 1


def test_missing_font_file_is_reported(tmp_path):
    with pytest.raises(ClassicRetroError) as caught:
        build_tmc_arabic_font(tmp_path / "absent.ttf")
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED
