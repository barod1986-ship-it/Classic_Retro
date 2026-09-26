from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.sotn import LINE_BREAK, parse_notation
from classic_retro.engines.sotn_arabic import (
    ARABIC_CODES,
    BASELINE,
    GLYPH_BYTES,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    INK,
    LINE_PIXELS,
    LINE_RIGHT,
    LINE_WIDTH,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    SIZES,
    SOFT,
    SPACE_WIDTH,
    TOP_ROW,
    SotnArabicEncoder,
    SotnFont,
    build_sotn_font,
    font_preview,
    glyph_characters,
    lay_out,
    message_preview,
    messages_sheet,
    painted_characters,
    sotn_glyph,
    sotn_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
ALEF = unicodedata.lookup("ARABIC LETTER ALEF ISOLATED FORM")
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")


def _map(text: str = "بب ب. ا س! بببب:") -> GlyphCodes:
    return sotn_glyph_codes(painted_characters(parse_notation(text)))


def _fake_font(glyph_map: GlyphCodes, width: int = 6) -> SotnFont:
    """Every glyph a bar ``width`` pixels wide on the baseline; the space is the real one."""
    bar = sotn_glyph(
        dict.fromkeys(((x, y) for x in range(width) for y in range(8, BASELINE)), INK), width
    )
    glyphs = {
        codes[0]: sotn_glyph({}, SPACE_WIDTH) if character == " " else bar
        for character, codes in glyph_map.sequences.items()
    }
    return SotnFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def _codes(glyph_map: GlyphCodes, *characters: str) -> bytes:
    return bytes(code for character in characters for code in glyph_map.sequence(character) or ())


def test_codes_follow_the_font_order_from_0x80():
    assert ARABIC_CODES == tuple(range(0x80, 0x100))
    assert glyph_characters()[:4] == (" ", ".", "!", ":")
    glyph_map = sotn_glyph_codes({BEH["MEDIAL"], ".", " ", ALEF, SEEN})
    assert glyph_map.characters == (" ", ".", ALEF, BEH["MEDIAL"], SEEN)
    # One code a form: the hook draws a glyph up to 16 pixels wide, the seen too.
    assert glyph_map.sequence(SEEN) == (0x84,)
    assert tuple(glyph_map.all_codes()) == ARABIC_CODES[:5]


@pytest.mark.parametrize("character", ["A", "ڤ"])
def test_characters_without_a_glyph_are_refused(character):
    with pytest.raises(ClassicRetroError) as caught:
        sotn_glyph_codes({character})
    assert caught.value.code in (ErrorCode.UNENCODABLE_TEXT, ErrorCode.MISSING_GLYPH)


def test_a_line_is_stored_in_paint_order_its_first_letter_on_the_right():
    glyph_map = _map()
    encoded = SotnArabicEncoder(glyph_map).encode(parse_notation("بب ب.\nا"))
    assert encoded.lines is None and encoded.line_widths is None
    assert encoded.data == (
        _codes(glyph_map, BEH["INITIAL"], BEH["FINAL"], " ", BEH["ISOLATED"], ".")
        + bytes((LINE_BREAK,))
        + _codes(glyph_map, ALEF)
    )
    # Every glyph is one the hook draws: none is the game's space or font.
    assert all(code in ARABIC_CODES for code in encoded.data if code != LINE_BREAK)


def test_commands_keep_their_places_between_the_letters():
    glyph_map = _map()
    encoded = SotnArabicEncoder(glyph_map).encode(parse_notation("ب{wait 4} بب{flag 2}."))
    assert encoded.data == (
        _codes(glyph_map, BEH["ISOLATED"])
        + b"\x03\x04"
        + _codes(glyph_map, " ", BEH["INITIAL"], BEH["FINAL"])
        + b"\x11\x02"
        + _codes(glyph_map, ".")
    )


def test_lines_are_measured_against_the_box():
    glyph_map = _map()
    encoder = SotnArabicEncoder(glyph_map, _fake_font(glyph_map, width=6))
    encoded = encoder.encode(parse_notation("بب ب\n{wait 4}\nب{flag 3}ب"))
    assert encoded.line_widths == (6 + 6 + SPACE_WIDTH + 6, 0, 6 + 6)
    # The English lines' room: from column 8 to 160, 19 letters of 8 pixels.
    assert LINE_WIDTH == LINE_RIGHT - 8 == 19 * 8
    assert encoder.encode(parse_notation("ب" * 25)).line_widths == (150,)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation("ب" * 26))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_the_hook_draws_each_glyph_left_of_the_one_before():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=6)
    data = SotnArabicEncoder(glyph_map, font).encode(parse_notation("بب \n{wait 2}ب")).data
    first, second = lay_out(data, {code: glyph.width for code, glyph in font.glyphs.items()})
    assert [place.pen for place in first.places] == [0, 6, 12]
    assert [place.left for place in first.places] == [
        LINE_RIGHT - 6,
        LINE_RIGHT - 12,
        LINE_RIGHT - 12 - SPACE_WIDTH,
    ]
    assert (second.places[0].left, second.width) == (LINE_RIGHT - 6, 6)
    # Without widths, only the glyphs' order.
    assert [place.code for place in lay_out(data)[0].places] == list(data[:3])


def test_a_name_is_one_line_of_text():
    glyph_map = _map()
    encoder = SotnArabicEncoder(glyph_map, _fake_font(glyph_map))
    name = encoder.encode_name("بب")
    assert name.data == _codes(glyph_map, BEH["INITIAL"], BEH["FINAL"])
    assert name.line_widths == (12,)
    for text in ("", "ب\nب", "ب{wait 2}"):
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode_name(text)
        assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_brackets_vowel_marks_and_latin_letters_are_refused():
    for text, code in (
        ("(ب)", ErrorCode.UNENCODABLE_TEXT),
        ("بَ", ErrorCode.UNSUPPORTED_ARABIC_MARK),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            painted_characters(parse_notation(text))
        assert caught.value.code is code
    with pytest.raises(ClassicRetroError) as caught:
        sotn_glyph_codes(painted_characters(parse_notation("ب R")))
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_commands_must_match_the_original_and_line_ends_are_free():
    source = ("{speed 4}", "{wait 28}", "{wait 48}")
    validate_command_skeleton(source, parse_notation("{speed 4}ب\nب{wait 28} ب\n\n{wait 48}"))
    for text in (
        "{speed 4}ب{wait 48}{wait 28}",
        "{speed 4}ب{wait 28}",
        "{speed 2}ب{wait 28}{wait 48}",
    ):
        with pytest.raises(ClassicRetroError) as caught:
            validate_command_skeleton(source, parse_notation(text))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_a_glyph_keeps_its_ink_inside_its_width_and_off_the_top_row():
    glyph = sotn_glyph({(0, 3): INK, (1, 3): SOFT, (5, 15): INK}, 6)
    assert glyph.width == 6 and len(glyph.pixels) == GLYPH_ROWS
    assert all(len(row) == GLYPH_COLUMNS for row in glyph.pixels)
    assert glyph.pixels[3][:3] == (INK, SOFT, 0) and glyph.pixels[15][5] == INK
    # Stored as the hook reads it: 8 bytes a row, the even pixel in the low nibble.
    stored = glyph.stored()
    assert len(stored) == GLYPH_BYTES == 128
    assert stored[3 * 8] == INK | SOFT << 4 and stored[15 * 8 + 2] == INK << 4
    for pixels, width in (({(6, 3): INK}, 6), ({(0, TOP_ROW - 1): INK}, 4), ({}, 0), ({}, 17)):
        with pytest.raises(FormDoesNotFit):
            sotn_glyph(pixels, width)


def test_the_tables_hold_every_code_from_0x80():
    glyph_map = _map()
    font = _fake_font(glyph_map)
    widths = font.width_table()
    assert len(widths) == len(ARABIC_CODES) == 128
    assert widths[0] == SPACE_WIDTH and widths[1] == 6
    assert set(widths[len(font.glyphs) :]) == {0}
    table = font.glyph_table()
    assert len(table) == GLYPH_BYTES * (max(font.glyphs) - 0x7F)
    assert table[:GLYPH_BYTES] == bytes(GLYPH_BYTES)


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef, beh and a wide seen, with OpenType forms."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
        "seen": [(0, 0, 1500, 300)],
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
    metrics["seen"] = (1500, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro SOTN Test", "styleName": "Regular"})
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


def _ink(glyph) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, v in enumerate(row) if v == INK}


def test_the_font_draws_every_form_on_row_12_at_the_largest_size_that_fits(contextual_font):
    glyph_map = sotn_glyph_codes({" ", ".", "!", ":", ALEF, SEEN, *BEH.values()})
    forms = (ALEF, SEEN, *BEH.values())
    font = build_sotn_font(contextual_font, glyph_map, sizing=forms)

    # The seen, 1.5 em wide, limits the size: 15 pixels at 10, 16.5 at 11.
    assert font.font_size == 10 and font.font_size in SIZES
    assert set(font.glyphs) == set(glyph_map.all_codes())
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= GLYPH_COLUMNS, code
        assert all(x < glyph.width and y >= TOP_ROW for x, y in _ink(glyph)), code
    # The body of beh sits on the baseline, its dot below it.
    beh = font.glyphs[glyph_map.code(BEH["ISOLATED"])]
    body = {(x, y) for y, row in enumerate(beh.pixels) for x, v in enumerate(row) if v}
    assert max(y for _, y in body if y < BASELINE) == BASELINE - 1
    assert any(y > BASELINE for _, y in _ink(beh))
    # The seen fills the cell: 15 pixels of ink, and the gap a form that does
    # not join the next one keeps after it.
    seen = font.glyphs[glyph_map.code(SEEN)]
    assert seen.width == GLYPH_COLUMNS and {x for x, _ in _ink(seen)} == set(range(15))
    space = font.glyphs[glyph_map.code(" ")]
    assert space.width == SPACE_WIDTH and not _ink(space)
    # The punctuation the reference font lacks, drawn on the baseline.
    stop = font.glyphs[glyph_map.code(".")]
    assert _ink(stop) == {(0, BASELINE - 2), (1, BASELINE - 2), (0, BASELINE - 1),
                          (1, BASELINE - 1)}  # fmt: skip
    assert stop.width == 3
    bang = font.glyphs[glyph_map.code("!")]
    assert max(y for _, y in _ink(bang)) == BASELINE - 1 and (0, BASELINE - 3) not in _ink(bang)


def test_a_font_without_a_form_is_refused(contextual_font):
    glyph_map = sotn_glyph_codes({unicodedata.lookup("ARABIC LETTER TEH ISOLATED FORM")})
    with pytest.raises(ClassicRetroError) as caught:
        build_sotn_font(contextual_font, glyph_map, sizing=(ALEF,))
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_previews_end_every_line_at_the_line_right_edge():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=6)
    encoder = SotnArabicEncoder(glyph_map, font)
    name = encoder.encode_name("ب").data
    data = encoder.encode(parse_notation("بب\nب\nب\n{wait 2}ب")).data
    image = message_preview(font, name, data)
    # The name, then four lines 16 rows apart.
    assert image.size == (LINE_PIXELS + 2 * PREVIEW_MARGIN, 2 * PREVIEW_MARGIN + GLYPH_ROWS * 5)
    ink = PREVIEW_COLOURS[INK]
    for line in range(5):
        row = PREVIEW_MARGIN + GLYPH_ROWS * line + BASELINE - 1
        lit = [x for x in range(image.width) if image.getpixel((x, row)) == ink]
        assert lit[-1] == PREVIEW_MARGIN + LINE_RIGHT - 1, line
    first = PREVIEW_MARGIN + GLYPH_ROWS + BASELINE - 1
    assert image.getpixel((PREVIEW_MARGIN + LINE_RIGHT - 12, first)) == ink
    assert image.getpixel((PREVIEW_MARGIN + LINE_RIGHT - 13, first)) != ink
    assert font_preview(font).size[0] > 0
    sheet = messages_sheet([("one", image), ("two", image)])
    assert sheet.height >= 2 * image.height
