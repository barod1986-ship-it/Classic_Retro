from __future__ import annotations

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines import mlss_arabic
from classic_retro.engines.mlss import MlssFont, glyph_bytes, parse_notation
from classic_retro.engines.mlss_arabic import (
    ARABIC_CODES,
    ARABIC_PREFIX,
    BASELINE,
    BOX_EXTRA_TILES,
    CELL_HEIGHT,
    CELL_WIDTH,
    LATIN_COPIES,
    LEFT_MARGIN,
    PREVIEW_COLOURS,
    RIGHT_MARGIN,
    RTL_LATIN_WIDTHS,
    SOFT,
    SPACE_ADVANCE,
    TEXT,
    MlssArabicEncoder,
    MlssArabicGlyphMap,
    MlssRtlFont,
    MlssRtlGlyph,
    build_mlss_arabic_glyph_map,
    build_mlss_rtl_font,
    font_preview,
    latin_rtl_glyphs,
    message_preview,
    messages_sheet,
    placeholder_latin_glyphs,
    validate_command_skeleton,
)

EMPTY = tuple((0,) * CELL_WIDTH for _ in range(CELL_HEIGHT))


def _fake_font(width: int = 5) -> MlssRtlFont:
    glyph_map = build_mlss_arabic_glyph_map()
    ink = tuple(
        tuple(TEXT if x < 4 and 2 <= y < 9 else 0 for x in range(CELL_WIDTH))
        for y in range(CELL_HEIGHT)
    )
    glyphs = {code: MlssRtlGlyph(width, ink) for code in glyph_map.all_codes()}
    glyphs[glyph_map.space] = MlssRtlGlyph(SPACE_ADVANCE, EMPTY)
    return MlssRtlFont(
        glyphs=glyphs, codes=dict(glyph_map.codes), space=glyph_map.space, font_size=10
    )


def _codes(data: bytes) -> list[int]:
    """Right-to-left codes of an encoded text, commands dropped."""
    codes = []
    index = 0
    while index < len(data):
        if data[index] == ARABIC_PREFIX:
            codes.append(data[index + 1])
            index += 2
        else:
            index += 3 if data[index + 1] in (0x01, *range(0x0B, 0x12)) else 2
    return codes


def _code(character: str) -> int:
    return build_mlss_arabic_glyph_map().codes[character]


def test_glyph_map_uses_printable_codes_below_the_font_prefixes():
    glyph_map = build_mlss_arabic_glyph_map()
    codes = glyph_map.all_codes()

    assert len(codes) == len(set(codes))
    assert all(code in ARABIC_CODES for code in codes)
    assert min(ARABIC_CODES) == 0x21 and max(ARABIC_CODES) < 0xFA
    assert glyph_map.space == 0x21
    assert set(LATIN_COPIES) <= set(glyph_map.codes)
    assert {"٠", "٩", "؟", "،", "؛", "ﺃ", "ﻲ"} <= set(glyph_map.codes)


def test_text_is_stored_in_right_to_left_paint_order():
    encoder = MlssArabicEncoder(_fake_font())
    result = encoder.encode(parse_notation("{FF 0B 01}اب يا{FF 11 01}{FF 0A}"))

    # Logical order is paint order: alef, beh, space, yeh (initial), alef (final).
    assert _codes(result.body) == [
        _code("ﺍ"), _code("ﺏ"), 0x21, _code("ﻳ"), _code("ﺎ"),
    ]  # fmt: skip
    assert result.body.startswith(b"\xff\x0b\x01\xfe")
    assert result.body.endswith(b"\xff\x11\x01\xff\x0a")


def test_digits_keep_their_order_inside_arabic():
    encoder = MlssArabicEncoder(_fake_font())
    result = encoder.encode(parse_notation("عام 12{FF 0A}"))

    codes = _codes(result.body)
    # The number is painted from its right end: 2 then 1.
    assert codes[-2:] == [_code("2"), _code("1")]


def test_commands_keep_their_place_and_split_segments():
    encoder = MlssArabicEncoder(_fake_font())
    result = encoder.encode(parse_notation("{FF 0B 01}ب{FF 2D}ب\nب{FF 20}{FF 0A}"))

    isolated = _code("ﺏ")
    assert result.body == (
        b"\xff\x0b\x01"
        + bytes((ARABIC_PREFIX, isolated))
        + b"\xff\x2d"
        + bytes((ARABIC_PREFIX, isolated))
        + b"\xff\x00"
        + bytes((ARABIC_PREFIX, isolated))
        + b"\xff\x20\xff\x0a"
    )


@pytest.mark.parametrize(
    ("notation", "code"),
    [
        ("(ب){FF 0A}", ErrorCode.UNENCODABLE_TEXT),
        ("بَ{FF 0A}", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("abc{FF 0A}", ErrorCode.UNENCODABLE_TEXT),
        ("بب", ErrorCode.MISSING_TERMINATOR),
        ("بب{FF 11 01}", ErrorCode.MISSING_TERMINATOR),
    ],
)
def test_unsupported_input_is_rejected(notation, code):
    with pytest.raises(ClassicRetroError) as caught:
        MlssArabicEncoder(_fake_font()).encode(parse_notation(notation))
    assert caught.value.code is code


def test_lines_are_measured_into_the_header():
    encoder = MlssArabicEncoder(_fake_font(width=5))
    result = encoder.encode(parse_notation("{FF 0B 01}ببب\nب{FF 11 01}{FF 0A}"))

    assert result.layout is not None
    assert result.layout.line_widths == (15, 5)
    assert result.header() == (2, 3)

    doubled = encoder.encode(parse_notation("{FF 0B 01}{FF 33}ببب{FF 0C 1E}{FF 0A}"))
    assert doubled.header() == (4, 3)

    with pytest.raises(ClassicRetroError) as caught:
        MlssArabicEncoder(_fake_font(width=16)).encode(parse_notation("ب" * 13 + "{FF 0A}"))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW

    unmeasured = MlssArabicEncoder().encode(parse_notation("بب{FF 0A}"))
    assert unmeasured.layout is None
    with pytest.raises(ClassicRetroError) as caught:
        unmeasured.header()
    assert caught.value.code is ErrorCode.INLINE_WIDTH_UNKNOWN


def test_skeleton_lets_line_ends_after_text_move_only():
    source = ("{FF 0B 01}", "\n", "{FF 35}", "{FF 0A}")
    validate_command_skeleton(source, parse_notation("{FF 0B 01}\n{FF 35}أ\nب{FF 0A}"))
    for notation in (
        "{FF 0B 01}{FF 35}أ{FF 0A}",
        "{FF 0B 01}\n{FF 36}أ{FF 0A}",
        "{FF 0B 01}\n{FF 35}أ{FF 11 01}{FF 0A}",
    ):
        with pytest.raises(ClassicRetroError) as caught:
            validate_command_skeleton(source, parse_notation(notation))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef and beh with OpenType forms."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "alef.fina": [(0, 0, 129, 760), (0, 0, 250, 90)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x627: "alef", 0x628: "beh"})
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
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro MLSS Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; sub alef by alef.fina; } fina;",
    )
    path = tmp_path / "contextual.ttf"
    builder.save(path)
    return path


def _small_map() -> MlssArabicGlyphMap:
    full = build_mlss_arabic_glyph_map()
    characters = (*LATIN_COPIES, "ﺃ", "ﺄ", "ﺏ", "ﺐ", "ﺑ", "ﺒ")
    return MlssArabicGlyphMap(
        space=full.space, codes={character: full.codes[character] for character in characters}
    )


def _ink(glyph: MlssRtlGlyph) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, value in enumerate(row) if value}


def test_font_fits_the_cell_and_joins(contextual_font):
    glyph_map = _small_map()
    font = build_mlss_rtl_font(contextual_font, glyph_map=glyph_map)

    assert font.glyphs[glyph_map.space].width == SPACE_ADVANCE
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= CELL_WIDTH
        assert all(value in (0, TEXT, SOFT) for row in glyph.pixels for value in row)
        # Nothing is drawn past the advance: a glyph never paints over its neighbour.
        assert all(x < glyph.width for x, _ in _ink(glyph)), code
    # Right-joining forms (medial/final) reach their right edge with ink.
    for character in ("ﺐ", "ﺒ"):
        glyph = font.glyphs[font.codes[character]]
        assert max(x for x, _ in _ink(glyph)) == glyph.width - 1
    # Letters sit on the row-9 baseline (they end on row 8) and their dots below it.
    beh = _ink(font.glyphs[font.codes["ﺏ"]])
    assert max(y for _, y in beh if y < BASELINE) == BASELINE - 1
    assert any(y >= BASELINE for _, y in beh)
    assert all(0 <= y < CELL_HEIGHT for _, y in beh)

    packed = font.game_font()
    assert (packed.cell_width, packed.cell_height) == (CELL_WIDTH, CELL_HEIGHT)
    assert packed.widths[glyph_map.space] == SPACE_ADVANCE and packed.widths[0xF9] == 1
    assert packed.glyphs[font.codes["ﺏ"]] == font.glyphs[font.codes["ﺏ"]].data()


def test_hamza_on_alef_keeps_an_empty_row_above_the_stroke(contextual_font):
    font = build_mlss_rtl_font(contextual_font, glyph_map=_small_map())

    for composed in ("ﺃ", "ﺄ"):
        rows = sorted({y for _, y in _ink(font.glyphs[font.codes[composed]])})
        assert rows[0] == 0 and 1 in rows and 2 not in rows and 3 in rows
        assert max(rows) <= BASELINE - 1


def test_raised_forms_move_up_and_keep_their_join():
    values = {(0, 12): TEXT, (3, 12): TEXT, (5, 8): TEXT, (5, 5): TEXT, (0, 10): TEXT}
    final, width = mlss_arabic._raised("ﻲ", (values, 6))
    assert width == 6 and max(y for _, y in final) == CELL_HEIGHT - 1
    assert (5, BASELINE - 1) in final and (5, 7) in final
    isolated, _ = mlss_arabic._raised("ﻱ", (values, 6))
    assert (5, BASELINE - 1) not in isolated
    # A form that already fits is left alone.
    inside = {(0, 3): TEXT}
    assert mlss_arabic._raised("ﻱ", (inside, 4)) == (inside, 4)


def _latin_font(**changes: int) -> MlssFont:
    widths = [5] * 256
    glyphs = [bytes(24)] * 256
    pixels = [[TEXT if x == 1 and 2 <= y <= 8 else 0 for x in range(8)] for y in range(12)]
    for character, code in LATIN_COPIES.items():
        widths[code] = changes.get(character, RTL_LATIN_WIDTHS[character])
        glyphs[code] = glyph_bytes(pixels, 8, 12)
    return MlssFont(8, 12, tuple(widths), tuple(glyphs))


def test_latin_copies_keep_the_game_rows_and_a_free_column():
    glyphs = latin_rtl_glyphs(_latin_font())

    assert {character: glyph.width for character, glyph in glyphs.items()} == RTL_LATIN_WIDTHS
    ink = _ink(glyphs["!"])
    assert min(y for _, y in ink) == 2 and max(y for _, y in ink) == BASELINE - 1
    assert set(placeholder_latin_glyphs()) == set(LATIN_COPIES)
    assert {c: g.width for c, g in placeholder_latin_glyphs().items()} == RTL_LATIN_WIDTHS
    with pytest.raises(ClassicRetroError) as caught:
        latin_rtl_glyphs(_latin_font(**{"!": 9}))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    empty = _latin_font()
    glyphs_data = list(empty.glyphs)
    glyphs_data[LATIN_COPIES["."]] = bytes(24)
    with pytest.raises(ClassicRetroError) as caught:
        latin_rtl_glyphs(MlssFont(8, 12, empty.widths, tuple(glyphs_data)))
    assert caught.value.code is ErrorCode.MISSING_GLYPH


def _ink_columns(image, colour=PREVIEW_COLOURS[TEXT]) -> list[int]:
    return [
        x
        for x in range(image.width)
        for y in range(image.height)
        if image.getpixel((x, y)) == colour
    ]


def test_previews_show_every_glyph_and_right_aligned_lines(contextual_font):
    font = build_mlss_rtl_font(contextual_font, glyph_map=_small_map())
    atlas = font_preview(font)
    assert atlas.width == 16 * (CELL_WIDTH + 2) and atlas.height >= CELL_HEIGHT + 2

    encoder = MlssArabicEncoder(font)
    left = encoder.encode(parse_notation("{FF 0B 01}ب{FF 11 01}{FF 0A}"))
    image = message_preview(font, left.header(), left.body)
    width = (left.header()[0] + BOX_EXTRA_TILES) * 8
    assert image.width == width
    columns = _ink_columns(image)
    # A left-aligned line starts at the right margin: the glyph's cell ends there.
    beh = font.glyphs[font.codes["ﺏ"]]
    ink_right = max(x for x, y in _ink(beh) if beh.pixels[y][x] == TEXT)
    assert columns and max(columns) == width - RIGHT_MARGIN - beh.width + ink_right

    centred = encoder.encode(parse_notation("{FF 0B 01}{FF 35}ب{FF 11 01}{FF 0A}"))
    image = message_preview(font, (10, 2), centred.body)
    columns = _ink_columns(image)
    area_middle = LEFT_MARGIN + (image.width - LEFT_MARGIN - RIGHT_MARGIN) / 2
    assert abs((min(columns) + max(columns)) / 2 - area_middle) <= 3

    paged = encoder.encode(parse_notation("{FF 0B 01}ب{FF 01 00}{FF 0B 01}بب{FF 0A}"))
    image = message_preview(font, paged.header(), paged.body)
    page = (paged.header()[0] + BOX_EXTRA_TILES) * 8
    assert image.width == 2 * page + 4
    sheet = messages_sheet([("one", image), ("two", atlas)])
    assert sheet.height == image.height + atlas.height + 8
