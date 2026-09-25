from __future__ import annotations

import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.metroid_fusion import (
    ARROW,
    DIALECTS,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    INK,
    NAVIGATION,
    NEW_PAGE,
    NEWLINE,
    OUTLINE,
    QUESTION,
    TILE_ROW_BYTES,
    MfCommand,
    is_command,
    parse_notation,
)
from classic_retro.engines.metroid_fusion_arabic import (
    BASELINE,
    BOTTOM_INK_ROW,
    BRIEFING,
    CODES_PER_ROW,
    LINE_RIGHT,
    LINE_WIDTH,
    LINES_PER_PAGE,
    PAGE,
    PREVIEW_ARROW,
    PREVIEW_COLOURS,
    QUESTION_BOX,
    QUESTION_CURSOR_GAP,
    RTL_CODE_SPAN,
    RTL_FIRST_CODE,
    RTL_GLYPH_CODES,
    SHEET_ROW_BYTES,
    SPACE,
    SPACE_WIDTH,
    STRIP,
    TOP_INK_ROW,
    MfArabicEncoder,
    MfRtlFont,
    MfRtlGlyph,
    build_metroid_fusion_arabic_glyph_map,
    build_metroid_fusion_rtl_font,
    font_preview,
    message_preview,
    messages_sheet,
    outlined_glyph,
    question_cursor_x,
    question_options,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")


def _pixels(glyph: MfRtlGlyph, value: int) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, v in enumerate(row) if v == value}


def _fake_font(width: int = 5) -> MfRtlFont:
    """Every glyph a bar ``width`` pixels wide, with its outline."""
    glyph_map = build_metroid_fusion_arabic_glyph_map()
    bar = {(x, y) for x in range(width - 2) for y in range(4, BASELINE)}
    glyph = outlined_glyph(bar, joins_left=False, joins_right=False)
    glyphs = {code: glyph for code in glyph_map.all_codes() if code != SPACE}
    return MfRtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def test_glyph_codes_fall_in_the_sheet_in_the_padding():
    glyph_map = build_metroid_fusion_arabic_glyph_map()
    codes = glyph_map.all_codes()
    assert len(codes) == len(set(codes))
    # The game's own space, then right-to-left codes: no routine reads one as a command.
    assert glyph_map.code(" ") == SPACE == 0x40
    rtl = set(codes) - {SPACE}
    assert rtl <= set(RTL_GLYPH_CODES)
    assert not any(is_command(code, dialect) for code in RTL_GLYPH_CODES for dialect in DIALECTS)
    assert RTL_FIRST_CODE == 0xB040 and max(RTL_GLYPH_CODES) < 0xC000
    for code in rtl:
        offset = code - RTL_FIRST_CODE
        # A top-half row, and an even slot: the next code's tiles are the right half.
        assert 0 <= offset < RTL_CODE_SPAN and offset % CODES_PER_ROW < 32 and offset % 2 == 0
    assert glyph_map.code(".") == RTL_FIRST_CODE
    assert all(len(glyph_map.sequence(character)) == 1 for character in glyph_map.characters)


def test_outlined_glyphs_keep_their_joining_sides_open():
    ink = {(0, 9), (1, 9), (2, 9), (1, 5), (1, 6), (1, 7), (1, 8)}
    isolated = outlined_glyph(ink, joins_left=False, joins_right=False)
    assert isolated.width == 5
    assert _pixels(isolated, INK) == {(x + 1, y) for x, y in ink}
    outline = _pixels(isolated, OUTLINE)
    # One column of outline on each side, and the eight neighbours of the ink.
    assert {x for x, _ in outline} == {0, 1, 2, 3, 4}
    assert (0, 10) in outline and (4, 8) in outline and (2, 4) in outline
    assert not outline & _pixels(isolated, INK)
    # Joined on both sides: the ink reaches both edges, the outline stays inside.
    medial = outlined_glyph(ink, joins_left=True, joins_right=True)
    assert medial.width == 3
    assert {x for x, _ in _pixels(medial, INK)} == {0, 1, 2}
    assert all(0 <= x < medial.width for x, _ in _pixels(medial, OUTLINE))


@pytest.mark.parametrize(
    "ink",
    [
        {(x, 8) for x in range(16)},
        {(0, TOP_INK_ROW - 1), (0, 5)},
        {(0, BOTTOM_INK_ROW + 1), (0, 5)},
    ],
)
def test_glyphs_leaving_the_cell_do_not_fit(ink):
    with pytest.raises(FormDoesNotFit):
        outlined_glyph(ink, joins_left=False, joins_right=False)


def test_tiles_and_sheet_place_every_glyph_where_draw_character_reads_it():
    pixels = tuple(
        tuple(
            INK if (x, y) == (1, 2) else OUTLINE if (x, y) == (9, 12) else 0
            for x in range(GLYPH_COLUMNS)
        )
        for y in range(GLYPH_ROWS)
    )
    glyph = MfRtlGlyph(10, pixels)
    top_left, top_right, bottom_left, bottom_right = glyph.tiles()
    assert struct.unpack_from("<I", top_left, 8)[0] == INK << 4
    assert struct.unpack_from("<I", bottom_right, 16)[0] == OUTLINE << 4
    assert set(top_right) == set(bottom_left) == {0}
    code = RTL_FIRST_CODE + CODES_PER_ROW + 6
    font = MfRtlFont(glyphs={code: glyph}, sequences={"x": (code,)}, font_size=11)
    sheet = font.sheet()
    assert len(sheet) == 2 * SHEET_ROW_BYTES
    start = (code - RTL_FIRST_CODE) * 32
    assert sheet[start : start + 32] == top_left
    assert sheet[start + TILE_ROW_BYTES + 32 : start + TILE_ROW_BYTES + 64] == bottom_right
    widths = font.width_table()
    assert len(widths) == RTL_CODE_SPAN and widths[code - RTL_FIRST_CODE] == 10
    assert sum(widths) == 10
    assert font.width(SPACE) == SPACE_WIDTH and font.width(code) == 10


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef, beh and a wide seen, with OpenType forms."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
        "seen": [(0, 0, 1200, 300)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x627: "alef", 0x628: "beh", 0x633: "seen"})
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        for left, bottom, right, top in shapes.get(name, []):
            pen.moveTo((left, bottom))
            pen.lineTo((left, top))
            pen.lineTo((right, top))
            pen.lineTo((right, bottom))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics["alef"] = (329, 100)
    metrics["seen"] = (1200, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro MF Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
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


def _small_map() -> GlyphCodes:
    full = build_metroid_fusion_arabic_glyph_map()
    characters = (" ", ".", "!", *BEH.values(), SEEN)
    return GlyphCodes(
        characters, {character: full.sequences[character] for character in characters}
    )


def test_font_draws_outlined_forms_that_join(contextual_font):
    glyph_map = _small_map()
    font = build_metroid_fusion_rtl_font(contextual_font, glyph_map=glyph_map)

    assert SPACE not in font.glyphs and font.sequences[" "] == (SPACE,)
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= GLYPH_COLUMNS, code
        values = {value for row in glyph.pixels for value in row}
        assert values <= {0, INK, OUTLINE}, code
        ink = _pixels(glyph, INK)
        assert ink and all(TOP_INK_ROW <= y <= BOTTOM_INK_ROW for _, y in ink), code
        assert all(x < glyph.width for x, _ in ink | _pixels(glyph, OUTLINE)), code
    # The letters sit on the baseline: their ink ends on the row above it.
    beh = font.glyphs[glyph_map.code(BEH["ISOLATED"])]
    assert max(y for _, y in _pixels(beh, INK) if y < BASELINE) == BASELINE - 1
    # A medial form's ink reaches both edges; an isolated form has an outline
    # column on both sides.
    medial = font.glyphs[glyph_map.code(BEH["MEDIAL"])]
    medial_columns = {x for x, _ in _pixels(medial, INK)}
    assert min(medial_columns) == 0 and max(medial_columns) == medial.width - 1
    isolated_columns = {x for x, _ in _pixels(beh, INK)}
    assert min(isolated_columns) == 1 and max(isolated_columns) == beh.width - 2
    # The wide seen stays one glyph, wider than a tile.
    seen = font.glyphs[glyph_map.code(SEEN)]
    assert 8 < seen.width <= GLYPH_COLUMNS
    # The drawn full stop: a 2x2 dot on the baseline, outlined.
    stop = font.glyphs[glyph_map.code(".")]
    assert _pixels(stop, INK) == {(1, BASELINE - 2), (2, BASELINE - 2), (1, BASELINE - 1),
                                  (2, BASELINE - 1)}  # fmt: skip
    assert stop.width == 4


def _code(character: str) -> int:
    code = build_metroid_fusion_arabic_glyph_map().code(character)
    assert code is not None
    return code


def test_text_is_encoded_in_right_to_left_paint_order():
    encoding = MfArabicEncoder().encode(parse_notation("بب ب\nب.{FC00}{FD00}ب{FC00}"))
    units = encoding.units
    # The first glyph painted is the rightmost: the first letter of the line.
    assert units[:5] == (
        _code(BEH["INITIAL"]),
        _code(BEH["FINAL"]),
        SPACE,
        _code(BEH["ISOLATED"]),
        NEWLINE,
    )
    # The full stop ends the sentence on its left, so it is painted last.
    assert units[5:9] == (_code(BEH["ISOLATED"]), _code("."), ARROW, NEW_PAGE)
    assert units[-1] == ARROW
    assert encoding.line_widths is None


def test_lines_are_measured_and_limited():
    encoder = MfArabicEncoder(_fake_font(8))
    encoding = encoder.encode(parse_notation("ب ب\nب{FC00}{FD00}ب{FC00}"))
    assert encoding.line_widths == (8 + SPACE_WIDTH + 8, 8, 8)
    too_wide = " ".join(["بببب"] * 7)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation(too_wide + "{FC00}"))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert str(LINE_WIDTH) in str(caught.value)


def test_pages_hold_two_lines_in_the_strip_and_nine_on_a_monologue_page():
    encoder = MfArabicEncoder()
    three = "ب\nب\nب{FC00}"
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation(three), STRIP)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert encoder.encode(parse_notation(three), PAGE).units[-1] == ARROW
    nine = "\n".join(["ب"] * LINES_PER_PAGE[PAGE])
    encoder.encode(parse_notation(nine + "{FC00}{FD00}" + nine + "{FC00}"), PAGE)
    with pytest.raises(ClassicRetroError):
        encoder.encode(parse_notation(nine + "\nب{FC00}"), PAGE)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("(ب)", ErrorCode.UNENCODABLE_TEXT),
        ("بَ", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("ب%", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_what_the_font_cannot_draw_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as caught:
        MfArabicEncoder().encode(parse_notation(text))
    assert caught.value.code is code


def test_translations_keep_the_originals_control_units():
    source = ("{FC00}", "{FD00}", "{E132}", "{FC00}")
    validate_command_skeleton(source, parse_notation("ب\nب{FC00}{FD00}{E132}ب{FC00}"))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(source, parse_notation("ب{FC00}{FD00}ب{FC00}"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_previews_draw_pages_from_the_right():
    font = _fake_font(6)
    units = MfArabicEncoder(font).encode(parse_notation("ب ب\nب{FC00}{FD00}ب{FC00}")).units
    strip = message_preview(font, units)
    assert strip.size == (2 * 240 + 4, 2 * GLYPH_ROWS + 8)
    page = message_preview(font, units, PAGE)
    assert page.size == (2 * 240 + 4, 9 * GLYPH_ROWS + 8)
    # The first page is on the right, its first glyph at the right edge of its line.
    first_page = strip.crop((244, 0, 484, strip.height))
    assert first_page.getpixel((8 + LINE_WIDTH - 2, 4 + 6)) == (248, 248, 248)
    assert first_page.getpixel((8 + LINE_WIDTH + 2, 4 + 6)) != (248, 248, 248)
    assert font_preview(font).size[0] == 16 * (GLYPH_COLUMNS + 2)
    sheet = messages_sheet([("one", strip), ("two", page)])
    assert sheet.height == strip.height + page.height + 8


# ---------------------------------------------------------------------------
# The briefings and their question


def _briefing(text: str) -> tuple:
    return parse_notation(text, NAVIGATION)


def _question(text: str) -> tuple:
    return parse_notation(text, QUESTION)


def test_a_briefing_keeps_its_colours_around_their_words():
    units = MfArabicEncoder().encode(_briefing("في {8102}بب{8100} ب."), BRIEFING).units
    # Painted from the right: the first word, then the coloured one, then the last.
    first = units.index(0x8102)
    assert units[first - 1] == SPACE and units[first + 3] == 0x8100
    assert units[first + 1 : first + 3] == (_code(BEH["INITIAL"]), _code(BEH["FINAL"]))


def test_a_briefing_box_scrolls_only_when_the_reader_presses_a():
    encoder = MfArabicEncoder()
    for fine in ("ب\nب{FD00}ب", "ب\nب{FC00}ب{FC00}ب", "ب{FB00}ب\nب"):
        encoder.encode(_briefing(fine), BRIEFING)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(_briefing("ب\nب\nب"), BRIEFING)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError):
        encoder.encode(_briefing("ب{FC00}ب\nب"), BRIEFING)


def test_commands_of_another_routine_are_refused():
    with pytest.raises(ClassicRetroError) as caught:
        MfArabicEncoder().encode((MfCommand(0x8102), "ب"), STRIP)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    with pytest.raises(ClassicRetroError) as caught:
        MfArabicEncoder().encode((MfCommand(0xFD00), "ب"), QUESTION_BOX)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_a_question_ends_with_a_glyph_and_places_its_options():
    font = _fake_font(5)
    encoder = MfArabicEncoder(font)
    encoding = encoder.encode(_question("{8040}ب\n{8057}{8340}بب {83A0}ب"), QUESTION_BOX)
    assert encoding.line_widths == (0x40 + 5, 0x90 + 5)
    options = question_options(encoding.units, font.width)
    assert options == ((0x40, 0x40 + 10), (0x90, 0x90 + 5))
    # Left of the option's mirrored place on the screen.
    assert question_cursor_x(options[0]) == LINE_RIGHT - 0x4A - QUESTION_CURSOR_GAP
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(_question("{8040}ب\n{8340}ب {83A0}"), QUESTION_BOX)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_glyphs_put_over_others_are_refused():
    encoder = MfArabicEncoder(_fake_font(5))
    crowded = "{8040}ب\n{8340}" + "ب" * 17 + " {83A0}ب"
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(_question(crowded), QUESTION_BOX)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert "overlap" in str(caught.value)


def test_previews_show_a_briefing_in_colour_and_the_question_with_its_cursor():
    font = _fake_font(6)
    briefing = MfArabicEncoder(font).encode(_briefing("{8102}ب{8100}\nب{FD00}ب"), BRIEFING)
    image = message_preview(font, briefing.units, BRIEFING)
    assert image.size == (2 * 240 + 4, 2 * GLYPH_ROWS + 8)
    first = image.crop((244, 0, 484, image.height))
    colours = {first.getpixel((x, y)) for x in range(240) for y in range(first.height)}
    assert PREVIEW_COLOURS[INK + 4] in colours and PREVIEW_ARROW in colours
    question = MfArabicEncoder(font).encode(
        _question("{8040}ب\n{8057}{8340}ب {83A0}ب"), QUESTION_BOX
    )
    box = message_preview(font, question.units, QUESTION_BOX)
    x = question_cursor_x(question_options(question.units, font.width)[0])
    assert box.getpixel((x + 2, 4 + GLYPH_ROWS + 8)) == PREVIEW_ARROW
