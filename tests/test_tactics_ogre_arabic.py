from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.arabic.repertoire import arabic_presentation_repertoire
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tactics_ogre import (
    GLYPH_ROWS,
    INK,
    LAST_WAIT,
    NEW_PAGE,
    NEWLINE,
    PAGE_WAIT,
    SOFT,
    parse_notation,
)
from classic_retro.engines.tactics_ogre_arabic import (
    BASELINE,
    LINE_WIDTH,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    RTL_GLYPH_BYTES,
    RTL_GLYPH_CODES,
    RTL_GLYPH_COLUMNS,
    SPACE_WIDTH,
    TOP_ROW,
    ToArabicEncoder,
    ToRtlFont,
    ToRtlGlyph,
    build_tactics_ogre_rtl_font,
    font_preview,
    glyph_characters,
    message_preview,
    messages_sheet,
    painted_characters,
    rtl_glyph,
    stored_glyph_rows,
    tactics_ogre_glyph_codes,
    validate_command_skeleton,
    window_width,
    written_names,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
ALEF = unicodedata.lookup("ARABIC LETTER ALEF ISOLATED FORM")
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")
# An invented name for name 9 of the list: "بب".
NAMES = {9: "بب"}


def _pixels(glyph: ToRtlGlyph, value: int) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, v in enumerate(row) if v == value}


def _map(text: str = "بب ب. !ا بببب") -> GlyphCodes:
    return tactics_ogre_glyph_codes(painted_characters(parse_notation(text), NAMES))


def _fake_font(glyph_map: GlyphCodes, width: int = 5) -> ToRtlFont:
    """Every glyph a bar ``width`` pixels wide; the space is the real one."""
    bar = rtl_glyph({(x, y): INK for x in range(width - 1) for y in range(4, BASELINE)}, width)
    glyphs = {
        codes[0]: rtl_glyph({}, SPACE_WIDTH) if character == " " else bar
        for character, codes in glyph_map.sequences.items()
    }
    return ToRtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def test_codes_go_to_the_characters_a_script_uses_in_a_fixed_order():
    glyph_map = tactics_ogre_glyph_codes({BEH["MEDIAL"], ".", " ", ALEF, "!"})
    assert glyph_map.characters == (" ", ".", "!", ALEF, BEH["MEDIAL"])
    assert glyph_map.all_codes() == (2, 3, 4, 5, 6)
    assert RTL_GLYPH_CODES == tuple(range(2, 0x80))
    # The same characters in another order get the same codes.
    again = tactics_ogre_glyph_codes([ALEF, "!", BEH["MEDIAL"], " ", "."])
    assert again.sequences == glyph_map.sequences
    assert glyph_characters()[:4] == (" ", ".", "!", ":")


def test_what_the_font_cannot_draw_gets_no_code():
    with pytest.raises(ClassicRetroError) as caught:
        tactics_ogre_glyph_codes({ALEF, "x"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
    # Every form of the repertoire and the punctuation need more than 126 codes.
    with pytest.raises(ClassicRetroError) as caught:
        tactics_ogre_glyph_codes(glyph_characters())
    assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED
    assert len(glyph_characters()) > len(RTL_GLYPH_CODES)
    assert len(arabic_presentation_repertoire()) < len(RTL_GLYPH_CODES) + 10


@pytest.mark.parametrize(
    ("values", "width"),
    [({(3, 5): INK}, 3), ({(0, TOP_ROW - 1): INK}, 4), ({}, 0), ({}, RTL_GLYPH_COLUMNS + 1)],
)
def test_glyphs_keep_their_pixels_inside_their_advance_and_off_the_top_row(values, width):
    with pytest.raises(FormDoesNotFit):
        rtl_glyph(values, width)


def test_a_glyph_is_stored_as_two_columns_of_sixteen_rows():
    glyph = rtl_glyph({(1, 2): INK, (9, 15): SOFT, (15, 3): INK}, 16)
    stored = glyph.stored()
    assert len(stored) == RTL_GLYPH_BYTES == 128
    rows = stored_glyph_rows(stored)
    assert rows[2] == (INK << 4, 0)
    assert rows[15] == (0, SOFT << 4)
    assert rows[3] == (0, INK << 28)
    assert sum(1 for left, right in rows if left or right) == 3


def test_tables_give_every_code_its_glyph_and_width():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=6)
    widths = font.width_table()
    assert len(widths) == 0x80 and widths[0] == widths[1] == 0
    assert widths[glyph_map.code(" ")] == SPACE_WIDTH
    assert widths[glyph_map.code(BEH["INITIAL"])] == 6
    table = font.glyph_table()
    assert len(table) == RTL_GLYPH_BYTES * (max(font.glyphs) + 1)
    assert table[:RTL_GLYPH_BYTES] == bytes(RTL_GLYPH_BYTES)
    start = RTL_GLYPH_BYTES * glyph_map.code(ALEF)
    assert table[start : start + RTL_GLYPH_BYTES] == font.glyphs[glyph_map.code(ALEF)].stored()


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
    builder.setupNameTable({"familyName": "Classic Retro TO Test", "styleName": "Regular"})
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


def test_font_draws_forms_that_join_in_the_games_two_inks(contextual_font):
    glyph_map = tactics_ogre_glyph_codes({" ", ".", ALEF, SEEN, *BEH.values()})
    forms = (ALEF, SEEN, *BEH.values())
    font = build_tactics_ogre_rtl_font(contextual_font, glyph_map, sizing=forms)

    assert set(font.glyphs) == set(glyph_map.all_codes())
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= RTL_GLYPH_COLUMNS, code
        assert {value for row in glyph.pixels for value in row} <= {0, INK, SOFT}, code
        pixels = _pixels(glyph, INK) | _pixels(glyph, SOFT)
        assert all(x < glyph.width and y >= TOP_ROW for x, y in pixels), code
    # The letters sit on the baseline: their ink ends on the row above it.
    beh = font.glyphs[glyph_map.code(BEH["ISOLATED"])]
    assert max(y for _, y in _pixels(beh, INK) if y < BASELINE) == BASELINE - 1
    # A medial form's ink reaches both edges of its advance.
    medial = font.glyphs[glyph_map.code(BEH["MEDIAL"])]
    columns = {x for x, _ in _pixels(medial, INK)}
    assert min(columns) == 0 and max(columns) == medial.width - 1
    # The wide seen stays one glyph, wider than a column of the game.
    assert 8 < font.glyphs[glyph_map.code(SEEN)].width <= RTL_GLYPH_COLUMNS
    # The space is blank; the full stop a 2x2 dot on the letters' last row.
    space = font.glyphs[glyph_map.code(" ")]
    assert space.width == SPACE_WIDTH and not _pixels(space, INK)
    stop = font.glyphs[glyph_map.code(".")]
    assert _pixels(stop, INK) == {(0, BASELINE - 2), (1, BASELINE - 2), (0, BASELINE - 1),
                                  (1, BASELINE - 1)}  # fmt: skip
    assert stop.width == 3


def test_a_font_without_a_form_is_refused(contextual_font):
    glyph_map = tactics_ogre_glyph_codes({ALEF, BEH["ISOLATED"]})
    with pytest.raises(ClassicRetroError) as caught:
        build_tactics_ogre_rtl_font(contextual_font, glyph_map)
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_text_is_encoded_in_right_to_left_paint_order():
    glyph_map = _map()
    encoding = ToArabicEncoder(glyph_map).encode(
        parse_notation("بب ب\nب.{8E}{8A}ب{8D}{8A}"), NAMES, 3
    )
    data = encoding.data

    def code(character: str) -> int:
        value = glyph_map.code(character)
        assert value is not None
        return value

    # The first glyph painted is the rightmost: the first letter of the line.
    assert data[:5] == bytes(
        (code(BEH["INITIAL"]), code(BEH["FINAL"]), code(" "), code(BEH["ISOLATED"]), NEWLINE)
    )
    # The full stop ends the sentence on its left, so it is painted last.
    assert data[5:9] == bytes((code(BEH["ISOLATED"]), code("."), PAGE_WAIT, NEW_PAGE))
    assert data[-2:] == bytes((LAST_WAIT, NEW_PAGE))
    assert encoding.lines is None and encoding.line_widths is None
    assert all(value < 0x80 or value in (NEWLINE, NEW_PAGE, PAGE_WAIT, LAST_WAIT) for value in data)


def test_a_name_of_the_list_is_written_out_in_its_line():
    pieces = parse_notation("{8B}{8709}{8C}\nب {8709}.{8D}{8A}")
    written = written_names(pieces, NAMES)
    assert written[1] == "بب" and written[4] == "ب بب."
    glyph_map = _map()
    data = ToArabicEncoder(glyph_map).encode(pieces, NAMES, 3).data
    assert 0x87 not in data
    # The name joins like any word: initial then final beh.
    assert data[1:3] == bytes((glyph_map.code(BEH["INITIAL"]), glyph_map.code(BEH["FINAL"])))
    with pytest.raises(ClassicRetroError) as caught:
        ToArabicEncoder(glyph_map).encode(parse_notation("{8705}"), NAMES, 3)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    assert "name 5" in str(caught.value)


@pytest.mark.parametrize("text", ["{8001}ب", "{8102}ب", "{8300}ب", "{8600}ب"])
def test_runtime_names_icons_and_unknown_commands_are_refused(text):
    with pytest.raises(ClassicRetroError) as caught:
        ToArabicEncoder(_map()).encode(parse_notation(text), NAMES, 3)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("(ب)", ErrorCode.UNENCODABLE_TEXT),
        ("بَ", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("بx", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_what_the_font_cannot_draw_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as caught:
        ToArabicEncoder(_map()).encode(parse_notation(text), NAMES, 3)
    assert caught.value.code is code


def test_pages_hold_the_lines_of_their_window():
    encoder = ToArabicEncoder(_map())
    three = "ب\nب\nب{8D}{8A}"
    assert encoder.encode(parse_notation(three), NAMES, 3).data
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation(three), NAMES, 2)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    encoder.encode(parse_notation("ب\nب{8E}{8A}ب\nب{8D}{8A}"), NAMES, 2)


def test_lines_are_measured_and_limited():
    glyph_map = _map()
    encoder = ToArabicEncoder(glyph_map, _fake_font(glyph_map, width=8))
    encoding = encoder.encode(parse_notation("ب ب\nب{8E}{8A}ب{8D}{8A}"), NAMES, 3)
    assert encoding.line_widths == (8 + SPACE_WIDTH + 8, 8, 8, 0)
    too_wide = " ".join(["بببب"] * 6)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation(too_wide), NAMES, 3)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert str(LINE_WIDTH) in str(caught.value)


def test_translations_keep_the_originals_commands():
    source = ("{8B}", "{8C}", "{8705}", "{8E}", "{8A}", "{8D}", "{8A}")
    validate_command_skeleton(source, parse_notation("{8B}ب{8C}\nب {8705}.{8E}{8A}ب{8D}{8A}"))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(source, parse_notation("{8B}ب{8C}\nب.{8E}{8A}ب{8D}{8A}"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_the_window_is_its_longest_line_in_whole_columns():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=5)
    lines = ToArabicEncoder(glyph_map, font).encode(parse_notation("بب\nب"), NAMES, 3).lines
    assert lines is not None
    assert window_width(lines) == 16


def test_previews_draw_pages_from_the_right_against_the_window_edge():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=5)
    encoder = ToArabicEncoder(glyph_map, font)
    data = encoder.encode(parse_notation("بب\nب{8E}{8A}ب{8D}{8A}"), NAMES, 3).data
    image = message_preview(font, data, 3)
    # Two pages (the empty one after the last page break is not drawn), each the
    # window (16 pixels) and its margins.
    page_width = 16 + 2 * PREVIEW_MARGIN
    assert image.height == 3 * GLYPH_ROWS + 2 * PREVIEW_MARGIN
    assert image.width >= 2 * page_width
    ink = PREVIEW_COLOURS[INK]
    first_page = image.width - page_width
    # The first page is on the right; its lines end at the window's right edge.
    right_edge = first_page + PREVIEW_MARGIN + 16
    row = PREVIEW_MARGIN + 6
    assert image.getpixel((right_edge - 2, row)) == ink
    assert image.getpixel((right_edge, row)) == PREVIEW_COLOURS[0]
    assert image.getpixel((right_edge - 11, row)) != ink
    sheet = messages_sheet([("a", image), ("b", image)])
    assert sheet.height >= 2 * image.height
    atlas = font_preview(font)
    assert atlas.width >= RTL_GLYPH_COLUMNS and atlas.height >= GLYPH_ROWS
