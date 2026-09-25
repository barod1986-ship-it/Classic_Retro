from __future__ import annotations

import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.advance_wars import (
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    AwFont,
    parse_notation,
)
from classic_retro.engines.advance_wars_arabic import (
    ARABIC_CODES,
    BASELINE,
    CHOICE_CURSORS,
    INK,
    LATIN_COPIES,
    LATIN_WIDTHS,
    LINE_WIDTH,
    NAME_WIDTH,
    PAGE_END_WIDTH,
    SOFT,
    SPACE,
    SPACE_ADVANCE,
    SPLIT_FORMS,
    THIN_SPACE,
    AwArabicEncoder,
    AwRtlFont,
    AwRtlGlyph,
    build_advance_wars_arabic_glyph_map,
    build_advance_wars_rtl_font,
    font_preview,
    latin_rtl_glyphs,
    message_preview,
    messages_sheet,
    placeholder_latin_glyphs,
    validate_command_skeleton,
)

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")
EMPTY = tuple((0,) * GLYPH_COLUMNS for _ in range(GLYPH_ROWS))


def _glyph(width: int) -> AwRtlGlyph:
    return AwRtlGlyph(
        width,
        tuple(tuple(INK if x == 0 and 4 <= y < 12 else 0 for x in range(8)) for y in range(16)),
    )


def _fake_font(width: int = 5) -> AwRtlFont:
    """Every glyph ``width`` pixels wide; the space and thin space as the game's."""
    glyph_map = build_advance_wars_arabic_glyph_map()
    glyphs = {code: _glyph(width) for code in glyph_map.all_codes()}
    glyphs[SPACE] = AwRtlGlyph(SPACE_ADVANCE, EMPTY)
    glyphs[glyph_map.code(THIN_SPACE)] = AwRtlGlyph(1, EMPTY)
    return AwRtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=10)


def _code(character: str) -> int:
    code = build_advance_wars_arabic_glyph_map().code(character)
    assert code is not None
    return code


def test_glyph_map_keeps_to_the_printers_glyph_codes():
    glyph_map = build_advance_wars_arabic_glyph_map()
    codes = glyph_map.all_codes()

    assert len(codes) == len(set(codes))
    assert glyph_map.code(" ") == SPACE == 0x20
    assert all(glyph_map.code(character) == code for character, code in LATIN_COPIES.items())
    # No control code, no colour, no zero.
    assert not set(codes) & {*range(0x18), *range(0x80, 0x84)}
    assert set(codes) - {SPACE, *LATIN_COPIES.values()} <= set(ARABIC_CODES)
    # Each wide form takes two codes, painted right part first.
    assert len(SPLIT_FORMS) == 37
    for character in SPLIT_FORMS:
        assert len(glyph_map.sequence(character)) == 2
    assert len(glyph_map.sequence(BEH["MEDIAL"])) == 1
    assert glyph_map.code(THIN_SPACE) is not None


def test_stored_glyphs_are_flipped_inside_their_advance():
    pixels = tuple(
        tuple({0: INK, 2: SOFT}.get(x, 0) if y == 3 else 0 for x in range(8)) for y in range(16)
    )
    stored = AwRtlGlyph(3, pixels).stored()
    assert len(stored) == 64
    rows = struct.unpack("<16I", stored)
    # x = 0 becomes x = 2 and x = 2 becomes x = 0: pixel x is nibble x.
    assert rows[3] == INK << 8 | SOFT
    assert rows[0] == 0


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
    builder.setupNameTable({"familyName": "Classic Retro AW Test", "styleName": "Regular"})
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
    full = build_advance_wars_arabic_glyph_map()
    characters = (" ", ".", THIN_SPACE, *BEH.values(), SEEN)
    return GlyphCodes(
        characters, {character: full.sequences[character] for character in characters}
    )


def _ink(glyph: AwRtlGlyph) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, value in enumerate(row) if value}


def test_font_fits_eight_by_sixteen_glyphs_and_splits_wide_forms(contextual_font):
    glyph_map = _small_map()
    font = build_advance_wars_rtl_font(contextual_font, glyph_map=glyph_map)

    assert font.glyphs[SPACE].width == SPACE_ADVANCE
    assert font.glyphs[glyph_map.code(THIN_SPACE)].width == 1
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= GLYPH_COLUMNS
        assert all(value in (0, INK, SOFT) for row in glyph.pixels for value in row), code
        assert all(x < glyph.width for x, _ in _ink(glyph)), code
    # The game's baseline: ink ends on row 12, dots go below it.
    beh = font.glyphs[glyph_map.code(BEH["ISOLATED"])]
    assert max(y for _, y in _ink(beh) if y < BASELINE) == BASELINE - 1
    # Medial and final forms reach their right edge (they join the glyph painted before).
    for form in ("MEDIAL", "FINAL"):
        glyph = font.glyphs[glyph_map.code(BEH[form])]
        assert max(x for x, _ in _ink(glyph)) == glyph.width - 1
    # The seen is two glyphs: its right part, 8 pixels, first; then the rest.
    right, left = (font.glyphs[code] for code in glyph_map.sequence(SEEN))
    assert right.width == GLYPH_COLUMNS and 1 <= left.width <= GLYPH_COLUMNS
    assert font.width(SEEN) == right.width + left.width > GLYPH_COLUMNS
    # A split form keeps its rows: both parts have ink on the same rows.
    assert {y for _, y in _ink(right)} == {y for _, y in _ink(left)}


def test_font_tables_point_at_every_glyph(contextual_font):
    font = build_advance_wars_rtl_font(contextual_font, glyph_map=_small_map())
    address = 0x083F8800
    data = font.tables(address)
    pointers = struct.unpack_from("<256I", data)
    widths = data[1024:1280]
    assert len(data) == 1280 + 64 * len(font.glyphs)
    for code, glyph in font.glyphs.items():
        assert widths[code] == glyph.width
        start = pointers[code] - address
        assert data[start : start + 64] == glyph.stored()
    assert widths[0x7F] == 0 and 0x7F not in font.glyphs


def _game_font(**changes: int) -> AwFont:
    widths = [0] * 256
    glyphs: list[tuple[tuple[int, ...], ...]] = [()] * 256
    for character, code in LATIN_COPIES.items():
        width = changes.get(character, LATIN_WIDTHS[character])
        widths[code] = width
        glyphs[code] = tuple(
            tuple(INK if x == width - 1 and 5 <= y <= 12 else 0 for x in range(width))
            for y in range(16)
        )
    return AwFont(tuple(widths), tuple(glyphs))


def test_latin_copies_take_the_games_glyphs_and_a_free_column():
    copies = latin_rtl_glyphs(_game_font())
    for character, glyph in copies.items():
        assert glyph.width == LATIN_WIDTHS[character] + 1
        assert max(x for x, _ in _ink(glyph)) == LATIN_WIDTHS[character] - 1
    assert set(placeholder_latin_glyphs()) == set(LATIN_COPIES)
    with pytest.raises(ClassicRetroError) as error:
        latin_rtl_glyphs(_game_font(**{"!": 4}))
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_text_is_encoded_in_right_to_left_paint_order():
    encoder = AwArabicEncoder()
    # Logical "ببب!": the first letter is painted first, on the right; "!" last.
    result = encoder.encode(parse_notation("ببب!{0F}"))
    assert result.body == bytes(
        (_code(BEH["INITIAL"]), _code(BEH["MEDIAL"]), _code(BEH["FINAL"]), 0x21, 0x0F)
    )
    assert result.line_widths is None
    result = encoder.encode(parse_notation("ب س\nب{0F}ب {15}.{0F}"))
    seen = build_advance_wars_arabic_glyph_map().sequence(SEEN)
    assert result.body == bytes(
        (_code(BEH["ISOLATED"]), 0x20, *seen, 0x0D, _code(BEH["ISOLATED"]), 0x0F)
        + (_code(BEH["ISOLATED"]), 0x20, 0x15, 0x2E, 0x0F)
    )


def test_lines_are_measured_with_the_name_and_limited():
    encoder = AwArabicEncoder(_fake_font(5))
    result = encoder.encode(parse_notation("بب\n{15}.{0F}"))
    assert result.line_widths == (10, NAME_WIDTH + 5, 0)
    too_wide = "ب" * (LINE_WIDTH // 5 + 1)
    with pytest.raises(ClassicRetroError) as error:
        encoder.encode(parse_notation(too_wide + "\nب{0F}"))
    assert error.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    # The last line of a page leaves room for the key arrow.
    page_end = "ب" * (PAGE_END_WIDTH // 5 + 1)
    with pytest.raises(ClassicRetroError) as error:
        encoder.encode(parse_notation(page_end + "{0F}"))
    assert error.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    encoder.encode(parse_notation(page_end + "\nب{0F}"))
    with pytest.raises(ClassicRetroError) as error:
        encoder.encode(parse_notation("ب\nب\nب{0F}"))
    assert error.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_a_question_gets_its_answers_around_the_cursor():
    font = _fake_font(5)
    encoder = AwArabicEncoder(font)
    result = encoder.encode(parse_notation("ب؟\n{16}"))
    first, second = result.body.split(b"\x0d")
    assert first == bytes((_code(BEH["ISOLATED"]), _code(chr(0x061F))))
    assert second[-1] == 0x16
    # Each answer starts a pixel past its cursor's tile: spaces, then thin spaces.
    thin = _code(THIN_SPACE)
    pen = 0
    starts = []
    blank = True
    for code in second[:-1]:
        if code not in (SPACE, thin) and blank:
            starts.append(pen)
        blank = code in (SPACE, thin)
        pen += font.glyphs[code].width
    assert starts == [cursor + 8 + 1 for cursor in CHOICE_CURSORS]
    assert result.line_widths[1] == pen
    # Without a font the answers are still there, spaced roughly.
    assert AwArabicEncoder().encode(parse_notation("ب\n{17}")).body.endswith(b"\x17")


def test_a_question_needs_a_line_of_its_own():
    with pytest.raises(ClassicRetroError) as error:
        AwArabicEncoder().encode(parse_notation("ب؟{16}"))
    assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    wide = _fake_font(8)
    with pytest.raises(ClassicRetroError) as error:
        AwArabicEncoder(wide).encode(parse_notation("ب\n{16}"))
    assert error.value.code is ErrorCode.TEXT_BOX_OVERFLOW


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{80}ب{0F}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{09 01}ب{0F}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("بَ{0F}", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("(ب){0F}", ErrorCode.UNENCODABLE_TEXT),
        ("ب%{0F}", ErrorCode.UNENCODABLE_TEXT),
        (THIN_SPACE + "ب{0F}", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_what_the_font_cannot_draw_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as error:
        AwArabicEncoder().encode(parse_notation(text))
    assert error.value.code is code


def test_translations_keep_the_originals_control_codes():
    validate_command_skeleton(("{15}", "{0F}"), parse_notation("أهلا\n{15}.{0F}"))
    with pytest.raises(ClassicRetroError) as error:
        validate_command_skeleton(("{15}", "{0F}"), parse_notation("أهلا.{0F}"))
    assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_previews_draw_pages_from_the_right():
    font = _fake_font(5)
    encoder = AwArabicEncoder(font)
    body = encoder.encode(parse_notation("بب\n{15}.{0F}ب؟\n{16}")).body
    image = message_preview(font, body)
    # Two pages, 240 pixels wide, four apart; the text starts at the right edge.
    assert image.size == (2 * 240 + 4, 2 * GLYPH_ROWS + 8)
    atlas = font_preview(font)
    assert atlas.width == 16 * (GLYPH_COLUMNS + 2)
    sheet = messages_sheet([("a", image), ("b", image)])
    assert sheet.height == 2 * (image.height + 4)
