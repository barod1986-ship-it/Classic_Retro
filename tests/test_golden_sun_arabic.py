from __future__ import annotations

import re
import struct

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.golden_sun import (
    CHARACTER_NAME,
    DASH,
    FONT_FIRST,
    FONT_GLYPH_BYTES,
    FONT_GLYPHS,
    KEY_END,
    KEY_PAGE,
    NEWLINE,
    NUMBER,
    PAUSE,
    QUESTION,
    SPACE,
    STORE_INDEX_END,
    STORE_INDEX_OFFSET,
    GoldenSunFont,
)
from classic_retro.engines.golden_sun_arabic import (
    ARABIC_CODE_BASE,
    BASELINE,
    CELL_HEIGHT,
    LATIN_ROW_SHIFT,
    LINES_PER_PAGE,
    MAX_LINE_WIDTH,
    NAME_WIDTH_BUDGET,
    PAIR_WIDTH,
    RTL_MARKER,
    RTL_TAG,
    SPACE_ADVANCE,
    USA_LATIN_ADVANCES,
    GoldenSunArabicEncoder,
    build_golden_sun_arabic_glyph_map,
    build_golden_sun_rtl_font,
    golden_sun_command,
    golden_sun_glyph_codes,
    golden_sun_newline,
    latin_rtl_glyphs,
    validate_command_skeleton,
)
from classic_retro.rom import golden_sun_arabic as overlay
from classic_retro.rom.golden_sun_arabic_script import golden_sun_arabic_messages
from classic_retro.text.tokens import TextToken, TokenStream


def _encoder(width: int = 6) -> GoldenSunArabicEncoder:
    glyph_map = build_golden_sun_arabic_glyph_map()
    advances = {ord(character): advance for character, advance in USA_LATIN_ADVANCES.items()}
    advances.update((ARABIC_CODE_BASE + slot, width) for slot in range(len(glyph_map.characters)))
    advances[SPACE] = SPACE_ADVANCE
    return GoldenSunArabicEncoder(advances=advances)


def _stream(*parts) -> TokenStream:
    tokens = []
    for number, part in enumerate(parts):
        if isinstance(part, str):
            tokens.append(TextToken(part))
        elif part == NEWLINE:
            tokens.append(golden_sun_newline(f"t{number}"))
        elif isinstance(part, tuple):
            tokens.append(golden_sun_command(f"t{number}", *part))
        else:
            tokens.append(golden_sun_command(f"t{number}", part))
    return TokenStream(tuple(tokens))


def _arabic_slots(codes: tuple[int, ...]) -> list[int]:
    return [code - ARABIC_CODE_BASE for code in codes if code >= ARABIC_CODE_BASE]


def test_glyph_map_uses_twelve_bit_codes_from_0x100():
    glyph_map = build_golden_sun_arabic_glyph_map()

    assert len(glyph_map.characters) <= 0x100
    assert len(set(glyph_map.characters)) == len(glyph_map.characters)
    assert glyph_map.code("ﺑ") == ARABIC_CODE_BASE + glyph_map.characters.index("ﺑ")
    assert glyph_map.code("A") is None
    assert glyph_map.code(" ") is None


def test_message_starts_with_the_rtl_marker_and_ends_with_a_terminator():
    result = _encoder().encode_message(_stream("مرحبا", KEY_END))

    assert result.codes[0] == RTL_MARKER
    assert result.codes[-1] == KEY_END
    assert len(_arabic_slots(result.codes)) == 5

    question = _encoder().encode_message(_stream("هل أنت بخير؟", QUESTION))
    assert question.codes[-1] == QUESTION


def test_text_is_stored_in_right_to_left_paint_order():
    glyph_map = build_golden_sun_arabic_glyph_map()
    result = _encoder().encode_message(_stream("بب", KEY_END))

    # Logical beh + beh: the right-hand glyph (initial form) is painted first.
    assert result.codes[1:3] == (glyph_map.code("ﺑ"), glyph_map.code("ﺐ"))


def test_numbers_and_game_punctuation_keep_their_order_inside_arabic():
    result = _encoder().encode_message(_stream("رقم 12!", KEY_END))
    latin = [code for code in result.codes if code < ARABIC_CODE_BASE and code != RTL_MARKER]

    # Painted from the right edge leftwards: the word, the space, "21", then "!".
    assert latin == [SPACE, ord("2"), ord("1"), ord("!"), KEY_END]


def test_the_hero_name_stays_an_ordered_runtime_command():
    result = _encoder().encode_message(_stream("هيا يا ", (CHARACTER_NAME, 1), ".", KEY_END))
    name = result.codes.index(CHARACTER_NAME)

    assert result.codes[name + 1] == 1
    # The words before the name are painted first (on its right), the period last.
    assert all(code >= ARABIC_CODE_BASE or code == SPACE for code in result.codes[1:name])
    assert result.codes[name + 2 :] == (ord("."), KEY_END)
    assert result.lines[0].names == 1
    assert result.lines[0].width >= NAME_WIDTH_BUDGET


def test_lines_and_pages_are_measured():
    encoder = _encoder(width=10)
    result = encoder.encode_message(_stream("بببب", NEWLINE, "ب", KEY_PAGE, "بب", KEY_END))
    assert [(line.page, line.width) for line in result.lines] == [(0, 40), (0, 10), (1, 20)]

    too_wide = "ب" * (MAX_LINE_WIDTH // 10 + 1)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode_message(_stream(too_wide, KEY_END))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW

    parts: list = []
    for _ in range(LINES_PER_PAGE):
        parts += ["ب", NEWLINE]
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode_message(_stream(*parts, "ب", KEY_END))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


@pytest.mark.parametrize(
    ("parts", "code"),
    [
        (("لديك ", NUMBER, " قطعة", KEY_END), ErrorCode.UNSUPPORTED_CONTROL_CODE),
        (("الآن", DASH, "هيا", KEY_END), ErrorCode.UNSUPPORTED_CONTROL_CODE),
        (("قال (نعم)", KEY_END), ErrorCode.UNENCODABLE_TEXT),
        (("مَرحبا", KEY_END), ErrorCode.UNSUPPORTED_ARABIC_MARK),
        (("ب",), ErrorCode.MISSING_TERMINATOR),
        (("€", KEY_END), ErrorCode.UNENCODABLE_TEXT),
        (("ب", KEY_END, "ب"), ErrorCode.TOKEN_ORDER_VIOLATION),
        (("ب", (CHARACTER_NAME,), KEY_END), ErrorCode.UNENCODABLE_TOKEN),
        (("ب", RTL_MARKER, KEY_END), ErrorCode.UNENCODABLE_TOKEN),
    ],
)
def test_unsupported_input_is_rejected(parts, code):
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(_stream(*parts))
    assert caught.value.code is code


def test_skeleton_allows_moved_newlines_inserted_pages_and_dropped_dashes():
    source = (CHARACTER_NAME, 0x01, DASH, PAUSE, KEY_END)
    translation = TokenStream(
        (
            golden_sun_command("n", CHARACTER_NAME, 0x01),
            TextToken("، هيا"),
            golden_sun_newline("l"),
            TextToken("ب"),
            golden_sun_command("i", KEY_PAGE, inserted=True),
            TextToken("ب"),
            golden_sun_command("p", PAUSE),
            TextToken("ب"),
            golden_sun_command("e", KEY_END),
        )
    )
    validate_command_skeleton(source, translation)
    result = _encoder().encode_message(translation)
    assert [line.page for line in result.lines] == [0, 0, 1]


def test_skeleton_rejects_changed_commands_and_other_insertions():
    changed = TokenStream((TextToken("ب"), golden_sun_command("e", QUESTION)))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton((KEY_END,), changed)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION

    smuggled = TokenStream(
        (
            TextToken("ب"),
            golden_sun_command("x", PAUSE, inserted=True),
            golden_sun_command("e", KEY_END),
        )
    )
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(smuggled)
    assert caught.value.code is ErrorCode.TOKEN_DEFINITION_MISMATCH


def test_shipped_opening_script_validates_without_the_rom():
    messages = golden_sun_arabic_messages()
    indices = [message.index for message in messages]

    assert indices == list(range(3666, 3687))
    report = overlay.check_golden_sun_translations()
    assert report["strings"] == indices
    assert report["lines_measured"] is False
    for message in messages:
        assert len(message.source_sha256) == 64
        assert message.speaker in {"Dora", "Kyle"}
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


def _latin_font() -> GoldenSunFont:
    data = bytearray(FONT_GLYPHS * FONT_GLYPH_BYTES)
    for code in range(FONT_FIRST + 1, FONT_FIRST + FONT_GLYPHS):
        glyph = (code - FONT_FIRST) * FONT_GLYPH_BYTES
        struct.pack_into("<H", data, glyph, 5)
        for row in range(3, 11):
            struct.pack_into("<H", data, glyph + 2 + 2 * row, 0b1100 << 12)
    return GoldenSunFont.parse(bytes(data), 0)


def test_font_uses_16_rows_with_a_shadow_inside_the_advance(contextual_font):
    characters = ("ﺏ", "ﺐ", "ﺑ", "ﺒ")
    glyph_map = golden_sun_glyph_codes(characters)
    font = build_golden_sun_rtl_font(contextual_font, _latin_font(), glyph_map=glyph_map)

    assert font.glyphs[SPACE].advance == SPACE_ADVANCE
    assert len(font.widths_data) == 0x200
    assert len(font.bitmap_data) == 0x200 * CELL_HEIGHT * 4
    assert len(font.data) == len(font.widths_data) + len(font.bitmap_data)
    for character in characters:
        code = glyph_map.code(character)
        glyph = font.glyphs[code]
        assert glyph.advance == font.arabic_widths[character] <= PAIR_WIDTH
        assert font.widths_data[code] == glyph.advance
        pixels = {
            (x, y, glyph.pixel(x, y))
            for y in range(CELL_HEIGHT)
            for x in range(16)
            if glyph.pixel(x, y)
        }
        assert {value for _, _, value in pixels} == {1, 2}
        # Neither ink nor shadow reaches the neighbour painted before it.
        assert all(x < glyph.advance for x, _, _ in pixels)
        # Row 15 is only ever shadow; the shadow is one pixel right and down.
        assert all(value == 2 for _, y, value in pixels if y == CELL_HEIGHT - 1)
        ink = {(x, y) for x, y, value in pixels if value == 1}
        assert all((x - 1, y - 1) in ink for x, y, value in pixels if value == 2)
    # Right-joining forms (medial/final) reach their right edge with ink.
    for character in ("ﺐ", "ﺒ"):
        glyph = font.glyphs[glyph_map.code(character)]
        ink_columns = {x for y in range(CELL_HEIGHT) for x in range(16) if glyph.pixel(x, y) == 1}
        assert max(ink_columns) == glyph.advance - 1


def test_latin_glyphs_move_onto_the_arabic_baseline():
    glyphs = latin_rtl_glyphs(_latin_font())
    glyph = glyphs[ord("A")]

    ink_rows = {y for y in range(CELL_HEIGHT) for x in range(16) if glyph.pixel(x, y) == 1}
    # Caps end on font row 10; in the cell they end just above the baseline.
    assert max(ink_rows) == 10 + LATIN_ROW_SHIFT == BASELINE - 1
    assert glyph.advance == 5
    assert SPACE not in glyphs


def test_missing_font_file_is_reported(tmp_path):
    with pytest.raises(ClassicRetroError) as caught:
        build_golden_sun_rtl_font(tmp_path / "absent.ttf")
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_hook_source_constants_match_the_python_side():
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    equates = {
        name: value
        for name, value in re.findall(r"^\s*\.equ\s+(\w+),\s*(.+?)\s*$", source, re.MULTILINE)
    }

    assert int(equates["HOOK_CODE"], 0) == overlay.HOOK_CODE_ADDRESS
    assert int(equates["ARABIC_STORE"], 0) == overlay.ARABIC_STORE_ADDRESS
    assert equates["ARABIC_INDEX"] == f"ARABIC_STORE + {STORE_INDEX_OFFSET}"
    assert int(equates["STORE_INDEX_END"], 0) == STORE_INDEX_END
    assert int(equates["DECODER_TREES"], 0) == overlay.DECODER_TREES
    assert int(equates["RTL_FONT"], 0) == overlay.RTL_FONT_ADDRESS
    assert int(equates["RTL_MARKER"], 0) == RTL_MARKER
    assert int(equates["RTL_TAG"], 0) == RTL_TAG
    assert int(equates["PAIR_WIDTH"], 0) == PAIR_WIDTH
    assert int(equates["LATIN_FONT"], 0) == overlay.LATIN_FONT_ADDRESS
    assert equates["RTL_BITMAPS"] == "RTL_FONT + 0x200"


def test_stored_hook_bytes_carry_the_font_pointer_and_return_addresses():
    code = overlay.HOOK_CODE
    words = {int.from_bytes(code[i : i + 4], "little") for i in range(0, len(code) - 3, 2)}
    font_pointer = overlay.HOOK_SYMBOLS["rtl_font_pointer"]

    assert len(code) == font_pointer + 4
    assert int.from_bytes(code[font_pointer:], "little") == overlay.RTL_FONT_ADDRESS
    # Thumb calls and returns into the decoder, typewriter, Latin renderer and measurers.
    for address in (
        0x08019BAD,
        0x08018615,
        0x08002DD9,
        0x08016E3F,
        0x080178B1,
        0x080188B1,
        0x08018ACD,
    ):
        assert address in words
    assert overlay.RTL_FONT_ADDRESS + 0x200 in words
    assert overlay.ARABIC_STORE_ADDRESS in words
    assert overlay.ARABIC_STORE_ADDRESS + STORE_INDEX_OFFSET in words
    assert overlay.TREE_TABLE_REFERENCES[0] == overlay.ARM_DECODER_ADDRESS + overlay.DECODER_TREES
    assert sorted(overlay.HOOK_SYMBOLS.values()) == list(overlay.HOOK_SYMBOLS.values())


def test_hook_sites_become_bl_calls_or_literal_jumps():
    for site in overlay.HOOK_SITES:
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        patched = site.replacement(target)
        assert len(patched) == len(site.original)
        if site.kind == "bl":
            high, low = struct.unpack("<HH", patched)
            assert high >> 11 == 0b11110 and low >> 11 == 0b11111
            offset = (high & 0x7FF) << 12 | (low & 0x7FF) << 1
            offset -= (offset & 0x400000) << 1
            assert site.address + 4 + offset == target
        else:
            assert site.address % 4 == 0
            assert patched[:4] == bytes.fromhex("004b1847")
            assert int.from_bytes(patched[4:], "little") == target | 1
