from __future__ import annotations

import re

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pmd import GLYPH_COLUMNS, GLYPH_ROWS, parse_notation
from classic_retro.engines.pmd_arabic import (
    ARABIC_LEAD,
    BASELINE,
    LATIN_COPIES,
    LINE_WIDTH,
    SPACE_ADVANCE,
    USA_LATIN_WIDTHS,
    PmdArabicEncoder,
    PmdArabicGlyphMap,
    PmdRtlFont,
    PmdRtlGlyph,
    PmdTextBox,
    build_pmd_arabic_glyph_map,
    build_pmd_rtl_font,
    font_preview,
    latin_rtl_glyphs,
    placeholder_latin_glyphs,
    string_preview,
    strings_sheet,
    validate_command_skeleton,
)
from classic_retro.rom import pmd_arabic as overlay
from classic_retro.rom.pmd_arabic_script import pmd_arabic_strings

EMPTY = tuple((0,) * GLYPH_COLUMNS for _ in range(GLYPH_ROWS))


def _fake_font(width: int = 5) -> PmdRtlFont:
    glyph_map = build_pmd_arabic_glyph_map()
    glyphs = {code: PmdRtlGlyph(width, EMPTY) for code in glyph_map.all_codes()}
    glyphs[glyph_map.space] = PmdRtlGlyph(SPACE_ADVANCE, EMPTY)
    sequences = {character: codes[:1] for character, codes in glyph_map.codes.items()}
    sequences[" "] = (glyph_map.space,)
    return PmdRtlFont(glyphs=glyphs, sequences=sequences, space=glyph_map.space, font_size=9)


def _codes(data: bytes) -> list[int]:
    """Two-byte glyph codes of an encoded string, commands and terminator dropped."""
    codes = []
    index = 0
    while index < len(data):
        if data[index] == ARABIC_LEAD:
            codes.append(data[index] << 8 | data[index + 1])
            index += 2
        else:
            index += 2 if data[index] == ord("#") else 1
    return codes


def _code(character: str) -> int:
    return build_pmd_arabic_glyph_map().codes[character][0]


def test_glyph_map_uses_free_0x84_codes_and_two_for_wide_forms():
    glyph_map = build_pmd_arabic_glyph_map()
    codes = glyph_map.all_codes()

    assert len(codes) == len(set(codes))
    assert all(code >> 8 == ARABIC_LEAD for code in codes)
    assert not {code & 0xFF for code in codes} & {0x7E, 0x7F, 0x86, 0x87}
    assert all(0x40 <= code & 0xFF <= 0xFC for code in codes)
    assert glyph_map.space == 0x8440
    assert len(glyph_map.codes["ﺲ"]) == 2 and len(glyph_map.codes["ﺏ"]) == 1
    assert set(LATIN_COPIES) <= set(glyph_map.codes)
    # Arabic-Indic digits, the question mark and the comma all have glyphs.
    assert {"٠", "٩", "؟", "،", "؛"} <= set(glyph_map.codes)


def test_strings_are_stored_in_right_to_left_paint_order():
    encoder = PmdArabicEncoder(_fake_font())
    data = encoder.encode(parse_notation("بب ب"), PmdTextBox.DIALOGUE).data

    # The first painted glyph is the rightmost one: the initial beh.
    assert _codes(data) == [_code("ﺑ"), _code("ﺐ"), 0x8440, _code("ﺏ")]
    assert data[-1] == 0
    # Spaces are right-to-left glyphs too, never the game's 0x20.
    assert b" " not in data


def test_digits_keep_their_order_inside_arabic():
    encoder = PmdArabicEncoder(_fake_font())
    data = encoder.encode(parse_notation("عام 803"), PmdTextBox.DIALOGUE).data
    digits = [code for code in _codes(data) if code in {_code(d) for d in "0123456789"}]

    # Painted from the right: 3, then 0, then 8 (the number reads 803).
    assert digits == [_code("3"), _code("0"), _code("8")]


def test_commands_keep_their_place_and_split_segments():
    encoder = PmdArabicEncoder(_fake_font())
    result = encoder.encode(
        parse_notation("{CENTER_ALIGN}حسنا...{WAIT_PRESS}\n{CENTER_ALIGN}بب"),
        PmdTextBox.FLOATING,
    )

    assert result.data.startswith(b"#+")
    assert b"#W\n#+" in result.data
    assert result.widths == (5 * 7, 10)


@pytest.mark.parametrize(
    ("notation", "box", "code"),
    [
        ("{COLOR:07}ب", PmdTextBox.DIALOGUE, ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{CENTER_ALIGN}ب", PmdTextBox.MENU, ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("ب\nب", PmdTextBox.MENU, ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("ب\nب\nب\nب", PmdTextBox.DIALOGUE, ErrorCode.TEXT_BOX_OVERFLOW),
        ("بَ", PmdTextBox.DIALOGUE, ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("(ب)", PmdTextBox.DIALOGUE, ErrorCode.UNENCODABLE_TEXT),
        ("Hi", PmdTextBox.DIALOGUE, ErrorCode.UNENCODABLE_TEXT),
        ("ڤ", PmdTextBox.DIALOGUE, ErrorCode.MISSING_GLYPH),
    ],
)
def test_unsupported_input_is_rejected(notation, box, code):
    with pytest.raises(ClassicRetroError) as caught:
        PmdArabicEncoder(_fake_font()).encode(parse_notation(notation), box)
    assert caught.value.code is code


def test_pages_reset_the_line_count_and_lines_are_measured():
    encoder = PmdArabicEncoder(_fake_font(width=10))
    result = encoder.encode(parse_notation("ب\nب\nب{EXTRA_MSG}ب\nب\nب"), PmdTextBox.DIALOGUE)
    assert result.widths == (10,) * 6

    wide = "ب" * (LINE_WIDTH[PmdTextBox.DIALOGUE] // 10 + 1)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation(wide), PmdTextBox.DIALOGUE)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    # Without a font the structure is checked but widths are unknown.
    assert PmdArabicEncoder().encode(parse_notation(wide), PmdTextBox.DIALOGUE).widths == (0,)


def test_skeleton_lets_line_ends_move_only():
    source = ("{CENTER_ALIGN}", "{WAIT_PRESS}", "{CENTER_ALIGN}")
    validate_command_skeleton(
        source, parse_notation("{CENTER_ALIGN}أ{WAIT_PRESS}\n{CENTER_ALIGN}ب")
    )
    validate_command_skeleton((), parse_notation("أ\nب\nج"))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(source, parse_notation("{CENTER_ALIGN}أ\n{CENTER_ALIGN}ب"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef, beh with OpenType forms and a wide seen."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "alef.fina": [(0, 0, 129, 760), (0, 0, 250, 90)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
        "seen": [(0, 0, 1600, 130), (0, 0, 100, 400), (700, 0, 800, 400), (1500, 0, 1600, 400)],
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
    metrics["seen"] = (1650, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro PMD Test", "styleName": "Regular"})
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


def _small_map() -> PmdArabicGlyphMap:
    full = build_pmd_arabic_glyph_map()
    characters = (*LATIN_COPIES, "ﺍ", "ﺎ", "ﺃ", "ﺄ", "ﺏ", "ﺐ", "ﺑ", "ﺒ", "ﺱ", "،")
    return PmdArabicGlyphMap(
        space=full.space, codes={character: full.codes[character] for character in characters}
    )


def _ink(glyph: PmdRtlGlyph) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, value in enumerate(row) if value}


def test_font_fits_the_cell_joins_and_splits_wide_forms(contextual_font):
    glyph_map = _small_map()
    font = build_pmd_rtl_font(contextual_font, glyph_map=glyph_map)

    assert font.glyphs[glyph_map.space].width == SPACE_ADVANCE
    for character, codes in font.sequences.items():
        for code in codes:
            glyph = font.glyphs[code]
            assert 0 < glyph.width <= GLYPH_COLUMNS or character == " "
            assert all(value in (0, 0xF) for row in glyph.pixels for value in row)
    # Right-joining forms (medial/final) reach their right edge with ink.
    for character in ("ﺐ", "ﺒ"):
        glyph = font.glyphs[font.sequences[character][0]]
        assert max(x for x, _ in _ink(glyph)) == glyph.width - 1
    # Letters sit above the Arabic baseline and their dots below it.
    beh = _ink(font.glyphs[font.sequences["ﺏ"][0]])
    assert any(y < BASELINE for _, y in beh) and any(y >= BASELINE for _, y in beh)
    assert all(0 <= y < GLYPH_ROWS for _, y in beh)
    # The wide seen becomes its right part, then its left part.
    right, left = (font.glyphs[code] for code in font.sequences["ﺱ"])
    assert right.width == GLYPH_COLUMNS and 0 < left.width < GLYPH_COLUMNS
    assert all(x < left.width for x, _ in _ink(left))
    # The Arabic comma is drawn, ending on the baseline.
    comma = font.glyphs[font.sequences["،"][0]]
    assert max(y for _, y in _ink(comma)) == BASELINE - 1


def test_hamza_on_alef_keeps_an_empty_row_above_the_stroke(contextual_font):
    font = build_pmd_rtl_font(contextual_font, glyph_map=_small_map())

    for composed, plain in (("ﺃ", "ﺍ"), ("ﺄ", "ﺎ")):
        ink = _ink(font.glyphs[font.sequences[composed][0]])
        rows = sorted({y for _, y in ink})
        assert rows[0] == 0 and 2 not in rows and 1 in rows and 3 in rows
        assert max(rows) == max(y for _, y in _ink(font.glyphs[font.sequences[plain][0]]))


def test_latin_copies_move_one_row_up():
    pixels = {
        character: tuple(
            tuple(0xF if x == 1 and 1 <= y <= 8 else 0 for x in range(GLYPH_COLUMNS))
            for y in range(GLYPH_ROWS)
        )
        for character in LATIN_COPIES
    }
    glyphs = latin_rtl_glyphs(pixels, USA_LATIN_WIDTHS)

    ink = _ink(glyphs["!"])
    assert min(y for _, y in ink) == 0 and max(y for _, y in ink) == BASELINE - 1
    assert glyphs["0"].width == 6
    assert set(placeholder_latin_glyphs()) == set(LATIN_COPIES)
    with pytest.raises(ClassicRetroError):
        latin_rtl_glyphs({}, USA_LATIN_WIDTHS)


def test_previews_show_every_glyph_and_right_aligned_lines(contextual_font):
    font = build_pmd_rtl_font(contextual_font, glyph_map=_small_map())
    atlas = font_preview(font)
    assert atlas.width == 16 * 14 and atlas.height >= 14

    encoder = PmdArabicEncoder(font)
    dialogue = encoder.encode(parse_notation("بب{WAIT_PRESS}\nب{EXTRA_MSG}ب"), PmdTextBox.DIALOGUE)
    image = string_preview(font, dialogue.data, PmdTextBox.DIALOGUE)
    # Two boxes of 26 tiles side by side, the first one on the right.
    assert image.width == 2 * 208 + 4
    first = [
        x
        for x in range(212, image.width)
        for y in range(image.height)
        if image.getpixel((x, y)) == (255, 255, 255)
    ]
    # Right-aligned inside the typewriter's 4-pixel margin.
    assert first and image.width - 12 <= max(first) <= image.width - 5
    grey = [
        x
        for x in range(212, image.width)
        for y in range(image.height)
        if image.getpixel((x, y)) == (150, 150, 150)
    ]
    assert grey and max(grey) < min(first)

    centred = encoder.encode(parse_notation("{CENTER_ALIGN}بب"), PmdTextBox.FLOATING)
    image = string_preview(font, centred.data, PmdTextBox.FLOATING)
    ink = [
        x
        for x in range(image.width)
        for y in range(image.height)
        if image.getpixel((x, y)) == (255, 255, 255)
    ]
    assert abs((min(ink) + max(ink)) / 2 - image.width / 2) <= 3

    menu = encoder.encode(parse_notation("ب"), PmdTextBox.MENU)
    assert string_preview(font, menu.data, PmdTextBox.MENU).width == 16
    sheet = strings_sheet([("a", image), ("b", atlas)])
    assert sheet.width >= image.width and sheet.height == image.height + atlas.height + 8


def test_missing_font_file_is_reported(tmp_path):
    with pytest.raises(ClassicRetroError) as caught:
        build_pmd_rtl_font(tmp_path / "absent.ttf")
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_shipped_personality_test_validates_without_the_rom():
    strings = pmd_arabic_strings()
    report = overlay.check_pmd_translations()

    assert report["strings"] == len(strings) == 158
    assert report["pointers"] == 206
    assert len({string.key for string in strings}) == len(strings)
    references = [reference for string in strings for reference in string.references]
    assert len(references) == len(set(references))
    for string in strings:
        assert len(string.source_sha256) == 64
        validate_command_skeleton(string.source_skeleton, string.pieces)
    boxes = {string.key: string.box for string in strings}
    assert boxes["intro.welcome"] is PmdTextBox.FLOATING
    assert boxes["hardy.1"] is PmdTextBox.DIALOGUE and boxes["yes"] is PmdTextBox.MENU
    # "Yes." and "No." are shared by most questions.
    shared = {string.key: len(string.references) for string in strings}
    assert shared["yes"] == 24 and shared["no"] == 23


def test_hook_source_constants_match_the_python_side():
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    equates = {
        name: int(value, 0)
        for name, value in re.findall(
            r"^\s*\.equ\s+(\w+),\s*([^@\n]+?)\s*(?:@.*)?$", source, re.MULTILINE
        )
    }

    assert equates["GLYPH_FLAGS"] == 8 and equates["RTL_ROWS"] == GLYPH_ROWS
    # The hooks call the functions the replaced BL instructions called.
    calls = {
        site.symbol: overlay.bl_target(site.address, site.original[:4])
        for site in overlay.HOOK_SITES
        if site.resume is None
    }
    assert calls["hook_draw"] == equates["DRAW_CHAR_ON_WINDOW_INTERNAL"]
    assert calls["hook_cursor_sprite"] == equates["ADD_SPRITE"]
    assert f"{overlay.HOOK_CODE_ADDRESS:#010X}".replace("0X", "0x") in source
