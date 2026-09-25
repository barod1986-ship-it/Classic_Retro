from __future__ import annotations

import re

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fire_emblem import PACE, FireEmblemFont, FireEmblemGlyph
from classic_retro.engines.fire_emblem_arabic import (
    ARABIC_CODE_BASE,
    BASELINE,
    CELL_HEIGHT,
    LATIN_ROW_SHIFT,
    LINE_WIDTH,
    PIXEL_INK,
    PIXEL_SHADE,
    RTL_MARKER,
    SPACE,
    SPACE_ADVANCE,
    USA_TALK_ADVANCES,
    WAIT_KEY_ALLOWANCE,
    FireEmblemArabicEncoder,
    TalkBox,
    build_fire_emblem_arabic_glyph_map,
    build_fire_emblem_rtl_font,
    fire_emblem_command,
    fire_emblem_glyph_codes,
    fire_emblem_stream,
    latin_rtl_glyphs,
    validate_command_skeleton,
)
from classic_retro.rom import fire_emblem_arabic as overlay
from classic_retro.rom.fire_emblem_arabic_script import fire_emblem_arabic_messages
from classic_retro.text.tokens import TextToken, TokenStream


def _encoder(width: int = 6) -> FireEmblemArabicEncoder:
    glyph_map = build_fire_emblem_arabic_glyph_map()
    advances = {ord(character): advance for character, advance in USA_TALK_ADVANCES.items()}
    advances.update((ARABIC_CODE_BASE + slot, width) for slot in range(len(glyph_map.characters)))
    advances[SPACE] = SPACE_ADVANCE
    advances[PACE] = 0
    return FireEmblemArabicEncoder(advances=advances)


def _encode(notation: str, box: TalkBox = TalkBox.BUBBLE, width: int = 6) -> bytes:
    return _encoder(width).encode_message(fire_emblem_stream(notation), box).data


def _arabic_slots(data: bytes) -> list[int]:
    return [code - ARABIC_CODE_BASE for code in data if code >= ARABIC_CODE_BASE]


def test_glyph_map_fills_0x82_up_without_arabic_indic_digits():
    glyph_map = build_fire_emblem_arabic_glyph_map()

    assert len(glyph_map.characters) == 123
    assert len(set(glyph_map.characters)) == len(glyph_map.characters)
    assert glyph_map.code("،") == ARABIC_CODE_BASE
    assert max(glyph_map.code(c) for c in glyph_map.characters) <= 0xFE
    assert glyph_map.code("٣") is None
    assert glyph_map.code("A") is None


def test_message_starts_with_the_marker_and_is_stored_in_paint_order():
    glyph_map = build_fire_emblem_arabic_glyph_map()
    data = _encode("بب[A][X]")

    assert data[0] == RTL_MARKER
    assert data[-2:] == b"\x03\x00"
    # Logical beh + beh: the right-hand glyph (initial form) is painted first.
    assert [slot + ARABIC_CODE_BASE for slot in _arabic_slots(data)] == [
        glyph_map.code("ﺑ"),
        glyph_map.code("ﺐ"),
    ]


def test_digits_and_punctuation_keep_their_order_inside_arabic():
    data = _encode("عام 803...[A][X]")
    latin = [code for code in data[1:] if code < ARABIC_CODE_BASE]

    # Painted from the right edge leftwards: the word, the space, "308", "...".
    assert bytes(latin) == b" 308...\x03\x00"


def test_commands_split_segments_but_keep_their_place():
    data = _encode("[OpenMidLeft][LoadFace 51 01][OpenMidLeft]أبي[ToggleMouthMove]...[.][A][X]")

    assert data[:6] == bytes((RTL_MARKER, 0x09, 0x10, 0x51, 0x01, 0x09))
    mouth = data.index(0x16)
    assert all(code >= ARABIC_CODE_BASE for code in data[6:mouth])
    assert data[mouth:] == b"\x16...\x1f\x03\x00"


def test_lines_are_measured_with_the_key_arrow_allowance():
    encoder = _encoder(width=10)
    result = encoder.encode_message(
        fire_emblem_stream("بببب[A][LF]ب[CR][LF]ب[X]"), TalkBox.WORLD_MAP
    )
    assert [line.width for line in result.lines] == [40 + WAIT_KEY_ALLOWANCE, 10, 10]

    speakers = encoder.encode_message(
        fire_emblem_stream("[OpenLeft]بب[A][OpenRight]ب[A][X]"), TalkBox.BUBBLE
    )
    assert [line.width for line in speakers.lines] == [32, 22]

    for box, limit in LINE_WIDTH.items():
        too_wide = "ب" * ((limit - WAIT_KEY_ALLOWANCE) // 10 + 1)
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode_message(fire_emblem_stream(too_wide + "[A][X]"), box)
        assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert LINE_WIDTH[TalkBox.BUBBLE] == 208
    assert LINE_WIDTH[TalkBox.WORLD_MAP] == 216


@pytest.mark.parametrize(
    ("notation", "code"),
    [
        ("لديك [G] قطع[X]", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("يا [Tact][X]", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("هل أنت مستعد؟[Yes][X]", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("قال (نعم)[X]", ErrorCode.UNENCODABLE_TEXT),
        ("مَرحبا[X]", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("عام ٨٠٣[X]", ErrorCode.MISSING_GLYPH),
        ("ب", ErrorCode.MISSING_TERMINATOR),
        ("€[X]", ErrorCode.UNENCODABLE_TEXT),
        ("ب[X]ب", ErrorCode.TOKEN_ORDER_VIOLATION),
        ("ب[0x1E][X]", ErrorCode.UNENCODABLE_TOKEN),
    ],
)
def test_unsupported_input_is_rejected(notation, code):
    with pytest.raises(ClassicRetroError) as caught:
        _encode(notation)
    assert caught.value.code is code


def test_text_with_raw_newlines_is_rejected():
    stream = TokenStream((TextToken("ب\nب"), fire_emblem_command("e", b"\x00")))
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(stream, TalkBox.BUBBLE)
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_skeleton_lets_line_feeds_and_pacing_move():
    source = (b"\x09", b"\x03", b"\x03", b"\x00")
    validate_command_skeleton(source, fire_emblem_stream("[OpenMidLeft]ب[LF]ب[.][A]ب[A][LF]ب[X]"))

    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(source, fire_emblem_stream("[OpenMidLeft]ب[A][X]"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_skeleton_keeps_the_line_feed_after_a_clear():
    source = (b"\x03", b"\x02", b"\x01", b"\x80\x04", b"\x00")
    validate_command_skeleton(source, fire_emblem_stream("ب[A][CR][LF][BreakTalk]ب[X]"))

    # The narration box skips the byte after [CR]: text there would be lost.
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(source, fire_emblem_stream("ب[A][CR]ب[LF][BreakTalk][X]"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_shipped_opening_script_validates_without_the_rom():
    messages = fire_emblem_arabic_messages()
    indices = [message.index for message in messages]

    assert indices == [0x8DB, 0x903, 0x904, 0x905, 0x906]
    assert [message.box for message in messages] == [TalkBox.WORLD_MAP] + [TalkBox.BUBBLE] * 4
    report = overlay.check_fire_emblem_translations()
    assert report["messages"] == [f"{index:#x}" for index in indices]
    assert report["lines_measured"] is False
    for message in messages:
        assert len(message.source_sha256) == 64
        validate_command_skeleton(message.source_skeleton, message.stream)


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


def _talk_font() -> FireEmblemFont:
    glyphs = {}
    for code in range(0x21, 0x7F):
        rows = [0] * CELL_HEIGHT
        top = 1 if code == ord("'") else 3
        for row in range(top, 14):
            rows[row] = PIXEL_INK | PIXEL_SHADE << 2
        glyphs[code] = FireEmblemGlyph(5, tuple(rows))
    return FireEmblemFont(glyphs=glyphs)


def test_font_keeps_ink_and_shade_inside_each_width(contextual_font):
    characters = ("ﺏ", "ﺐ", "ﺑ", "ﺒ", "،")
    glyph_map = fire_emblem_glyph_codes(characters)
    font = build_fire_emblem_rtl_font(contextual_font, _talk_font(), glyph_map=glyph_map)

    assert font.glyphs[SPACE].width == SPACE_ADVANCE
    assert font.glyphs[PACE].width == 0
    for character in characters:
        glyph = font.glyphs[glyph_map.code(character)]
        assert glyph.width == font.arabic_widths[character] <= 16
        pixels = {
            (x, y, glyph.pixel(x, y))
            for y in range(CELL_HEIGHT)
            for x in range(16)
            if glyph.pixel(x, y)
        }
        assert {value for _, _, value in pixels} <= {PIXEL_INK, PIXEL_SHADE}
        # Neither ink nor shade reaches the neighbour painted before it.
        assert all(x < glyph.width for x, _, _ in pixels)
        assert all(1 <= y < CELL_HEIGHT for _, y, _ in pixels)
        # The shade sits right of the ink, as in the game's font.
        ink = {(x, y) for x, y, value in pixels if value == PIXEL_INK}
        assert all((x - 1, y) in ink for x, y, value in pixels if value == PIXEL_SHADE)
    # Right-joining forms (medial/final) reach their right edge with ink.
    for character in ("ﺐ", "ﺒ"):
        glyph = font.glyphs[glyph_map.code(character)]
        ink = {x for y in range(CELL_HEIGHT) for x in range(16) if glyph.pixel(x, y) == PIXEL_INK}
        assert max(ink) == glyph.width - 1
    # The Arabic comma is drawn, ending on the baseline.
    comma = font.glyphs[glyph_map.code("،")]
    rows = {y for y in range(CELL_HEIGHT) for x in range(16) if comma.pixel(x, y) == PIXEL_INK}
    assert max(rows) == BASELINE - 1 and len(rows) == 4

    data = font.data(0x08F01000)
    table = [int.from_bytes(data[4 * code : 4 * code + 4], "little") for code in range(256)]
    assert table[0] == 0
    assert table[glyph_map.code("ﺏ")] >= 0x08F01000 + 0x400
    assert len(data) == 0x400 + 72 * len(font.glyphs)


def test_latin_glyphs_move_onto_the_arabic_baseline():
    glyphs = latin_rtl_glyphs(_talk_font())
    glyph = glyphs[ord("A")]

    ink_rows = {y for y in range(CELL_HEIGHT) for x in range(16) if glyph.pixel(x, y)}
    # Caps end on font row 13; in the cell they end on the Arabic baseline row.
    assert max(ink_rows) == 13 + LATIN_ROW_SHIFT == BASELINE - 1
    # A glyph that would lose ink above the cell is left out.
    assert ord("'") not in glyphs


def test_missing_font_file_is_reported(tmp_path):
    with pytest.raises(ClassicRetroError) as caught:
        build_fire_emblem_rtl_font(tmp_path / "absent.ttf")
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_hook_source_constants_match_the_python_side():
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    equates = {
        name: value
        for name, value in re.findall(
            r"^\s*\.equ\s+(\w+),\s*([^@\n]+?)\s*(?:@.*)?$", source, re.MULTILINE
        )
    }

    assert int(equates["RTL_GLYPHS"], 0) == overlay.RTL_FONT_ADDRESS
    assert int(equates["RTL_MARKER"], 0) == RTL_MARKER
    assert int(equates["STATE_POINTER"], 0) == overlay.TALK_STATE_POINTER
    assert int(equates["SPRITE_AXIS"], 0) == LINE_WIDTH[TalkBox.WORLD_MAP] + 4
    assert int(equates["FALLBACK"].split("*")[0], 0) == ord("?")
