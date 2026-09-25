from __future__ import annotations

import re

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ff6a import (
    CENTER,
    CHOICE,
    END,
    KEY_PAGE,
    NEWLINE,
    PAGE,
    PAUSE,
    encode_code,
)
from classic_retro.engines.ff6a_arabic import (
    ARABIC_CODE_BASE,
    GLYPH_HEIGHT,
    RIGHT_EDGE,
    RTL_MARKER,
    USA_LATIN_GLYPHS,
    Ff6aArabicEncoder,
    Ff6aLayout,
    build_ff6a_arabic_font,
    build_ff6a_arabic_glyph_map,
    ff6a_command,
    ff6a_glyph_codes,
    ff6a_newline,
    validate_command_skeleton,
)
from classic_retro.rom import ff6a_arabic as overlay
from classic_retro.rom.ff6a_arabic_script import ff6a_arabic_messages
from classic_retro.text.tokens import TextToken, TokenStream


def _encoder(width: int = 6) -> Ff6aArabicEncoder:
    glyph_map = build_ff6a_arabic_glyph_map()
    return Ff6aArabicEncoder(arabic_widths=dict.fromkeys(glyph_map.characters, width))


def _stream(*parts) -> TokenStream:
    tokens = []
    for number, part in enumerate(parts):
        if isinstance(part, str):
            tokens.append(TextToken(part))
        elif part == NEWLINE:
            tokens.append(ff6a_newline(f"t{number}"))
        elif isinstance(part, tuple):
            tokens.append(ff6a_command(f"t{number}", *part))
        else:
            tokens.append(ff6a_command(f"t{number}", part))
    return TokenStream(tuple(tokens))


def _arabic_slots(codes: tuple[int, ...]) -> list[int]:
    return [code - ARABIC_CODE_BASE for code in codes if code >= ARABIC_CODE_BASE]


def test_glyph_map_uses_codes_from_0x600():
    glyph_map = build_ff6a_arabic_glyph_map()

    assert len(glyph_map.characters) <= 0x100
    assert len(set(glyph_map.characters)) == len(glyph_map.characters)
    assert " " in glyph_map.characters
    assert glyph_map.code("\ufe91") == ARABIC_CODE_BASE + glyph_map.characters.index("\ufe91")
    assert glyph_map.code("A") is None


def test_message_starts_with_the_rtl_marker_and_ends_with_end():
    result = _encoder().encode_message(_stream("مرحبا", END), layout=Ff6aLayout.DIALOGUE)

    assert result.codes[0] == RTL_MARKER
    assert result.data.startswith(encode_code(RTL_MARKER))
    assert result.codes[-1] == END
    assert len(_arabic_slots(result.codes)) == 5


def test_text_is_stored_in_right_to_left_paint_order():
    glyph_map = build_ff6a_arabic_glyph_map()
    result = _encoder().encode_message(_stream("بب", END), layout=Ff6aLayout.DIALOGUE)

    # Logical beh + beh: the right-hand glyph (initial form) is painted first.
    assert [code + ARABIC_CODE_BASE for code in _arabic_slots(result.codes)] == [
        glyph_map.code("\ufe91"),
        glyph_map.code("\ufe90"),
    ]


def test_numbers_and_game_punctuation_keep_their_order_inside_arabic():
    result = _encoder().encode_message(_stream("رقم 12!", END), layout=Ff6aLayout.DIALOGUE)
    latin = [code for code in result.codes if code < ARABIC_CODE_BASE and code != RTL_MARKER]

    # Painted from the right edge leftwards: the word, the space, "21", then "!".
    one, two = USA_LATIN_GLYPHS["1"][0], USA_LATIN_GLYPHS["2"][0]
    assert latin == [two, one, USA_LATIN_GLYPHS["!"][0], END]


def test_lines_are_measured_against_the_window_and_page():
    encoder = _encoder(width=10)
    result = encoder.encode_message(
        _stream("بببب", NEWLINE, "ب", (PAGE, NEWLINE), "بب", END), layout=Ff6aLayout.DIALOGUE
    )
    assert [(line.page, line.width) for line in result.lines] == [(0, 40), (0, 10), (1, 20)]

    too_wide = "ب" * (RIGHT_EDGE // 10 + 1)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode_message(_stream(too_wide, END), layout=Ff6aLayout.DIALOGUE)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_windows_hold_two_arabic_lines_and_the_narration_band_four():
    three_lines = _stream("ب", NEWLINE, "ب", NEWLINE, "ب", END)
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(three_lines, layout=Ff6aLayout.DIALOGUE)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW

    result = _encoder().encode_message(three_lines, layout=Ff6aLayout.NARRATION)
    assert len(result.lines) == 3


def test_key_page_starts_a_new_page():
    result = _encoder().encode_message(
        _stream("ب", NEWLINE, "ب", KEY_PAGE, "ب", NEWLINE, "ب", END), layout=Ff6aLayout.DIALOGUE
    )
    assert [line.page for line in result.lines] == [0, 0, 1, 1]


def test_page_needs_the_newline_the_engine_skips():
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(_stream("ب", PAGE, "ب", END), layout=Ff6aLayout.DIALOGUE)
    assert caught.value.code is ErrorCode.UNENCODABLE_TOKEN


def test_center_must_start_a_line():
    ok = _encoder().encode_message(_stream(CENTER, "ب", END), layout=Ff6aLayout.DIALOGUE)
    assert ok.lines[0].centered

    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(_stream("ب", CENTER, "ب", END), layout=Ff6aLayout.DIALOGUE)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


@pytest.mark.parametrize(
    ("parts", "code"),
    [
        (("اسم ", 0x127, END), ErrorCode.UNSUPPORTED_CONTROL_CODE),
        (("نعم", CHOICE, END), ErrorCode.UNSUPPORTED_CONTROL_CODE),
        (("قال (نعم)", END), ErrorCode.UNENCODABLE_TEXT),
        (("مَرحبا", END), ErrorCode.UNSUPPORTED_ARABIC_MARK),
        (("ب",), ErrorCode.MISSING_TERMINATOR),
        (("€", END), ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_unsupported_input_is_rejected(parts, code):
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(_stream(*parts), layout=Ff6aLayout.DIALOGUE)
    assert caught.value.code is code


def test_skeleton_allows_moved_layout_and_inserted_pages():
    source = (PAUSE, 0x14C, PAGE, END)
    translation = TokenStream(
        (
            ff6a_command("c", CENTER),
            TextToken("ب"),
            ff6a_command("p", PAUSE, 0x14C),
            ff6a_command("g", PAGE, NEWLINE),
            TextToken("ب"),
            ff6a_command("i", PAUSE, 0x154, PAGE, NEWLINE, inserted=True),
            TextToken("ب"),
            ff6a_newline("n"),
            TextToken("ب"),
            ff6a_command("e", END),
        )
    )
    validate_command_skeleton(source, translation)
    result = _encoder().encode_message(translation, layout=Ff6aLayout.DIALOGUE)
    assert [line.page for line in result.lines] == [0, 1, 2, 2]


def test_skeleton_rejects_changed_commands_and_other_insertions():
    changed = TokenStream((TextToken("ب"), ff6a_command("p", PAUSE, 0x154), ff6a_command("e", END)))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton((PAUSE, 0x14C, END), changed)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION

    smuggled = TokenStream(
        (TextToken("ب"), ff6a_command("x", 0x136, 0x150, inserted=True), ff6a_command("e", END))
    )
    with pytest.raises(ClassicRetroError) as caught:
        _encoder().encode_message(smuggled, layout=Ff6aLayout.DIALOGUE)
    assert caught.value.code is ErrorCode.TOKEN_DEFINITION_MISMATCH


def test_shipped_opening_script_validates_without_the_rom():
    messages = ff6a_arabic_messages()
    indices = [message.index for message in messages]

    assert len(indices) == len(set(indices))
    assert set(indices) == {*range(1, 10), *range(11, 21)}
    report = overlay.check_ff6a_translations()
    assert report["messages"] == sorted(indices)
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


def test_font_uses_the_game_format_with_a_shadow_inside_the_advance(contextual_font):
    characters = ("\ufe8f", "\ufe90", "\ufe91", "\ufe92", " ")
    glyph_map = ff6a_glyph_codes(characters)
    result = build_ff6a_arabic_font(contextual_font, glyph_map=glyph_map)
    font = result.font

    assert font.height == GLYPH_HEIGHT
    assert len(font.glyphs) == len(characters)
    assert type(font).parse(font.build()) == font
    for character, glyph in zip(characters, font.glyphs, strict=True):
        assert glyph.advance == result.widths[character]
        assert 1 <= glyph.row_bytes <= 4
        pixels = {
            (x, y, glyph.pixel(x, y))
            for y in range(GLYPH_HEIGHT)
            for x in range(glyph.row_bytes * 4)
            if glyph.pixel(x, y)
        }
        assert {value for _, _, value in pixels} <= {1, 2}
        # Neither ink nor shadow reaches the neighbour painted before it.
        assert all(x < glyph.advance for x, _, _ in pixels)
        # Row 15 is only ever shadow.
        assert all(value == 2 for _, y, value in pixels if y == GLYPH_HEIGHT - 1)
        if character != " ":
            assert any(value == 1 for _, _, value in pixels)
            assert any(value == 2 for _, _, value in pixels)
    # Right-joining forms (medial/final) reach their right edge with ink.
    for character in ("\ufe90", "\ufe92"):
        glyph = font.glyphs[characters.index(character)]
        ink_columns = {
            x
            for y in range(GLYPH_HEIGHT)
            for x in range(glyph.row_bytes * 4)
            if glyph.pixel(x, y) == 1
        }
        assert max(ink_columns) == glyph.advance - 1


def test_missing_font_file_is_reported(tmp_path):
    with pytest.raises(ClassicRetroError) as caught:
        build_ff6a_arabic_font(tmp_path / "absent.ttf")
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_hook_source_constants_match_the_python_side():
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    equates = {
        name: int(value, 0)
        for name, value in re.findall(r"^\s*\.equ\s+(\w+),\s*(\S+)$", source, re.MULTILINE)
    }
    marker = encode_code(RTL_MARKER)

    assert equates["ARABIC_CODE"] == overlay.HOOK_CODE_ADDRESS
    assert equates["ARABIC_FONT"] == overlay.ARABIC_FONT_ADDRESS
    assert equates["ARABIC_BASE"] == ARABIC_CODE_BASE
    assert (equates["RTL_MARKER_LEAD"], equates["RTL_MARKER_TRAIL"]) == (marker[0], marker[1])
    assert equates["RTL_RIGHT"] == RIGHT_EDGE
    assert equates["LINE_STEP_ARABIC"] == GLYPH_HEIGHT
    assert equates["LAST_LATIN_GLYPH"] == 0x10C


def test_stored_hook_bytes_carry_the_font_object_and_return_addresses():
    code = overlay.HOOK_CODE
    words = {int.from_bytes(code[i : i + 4], "little") for i in range(0, len(code) - 3, 2)}
    font_object = overlay.HOOK_SYMBOLS["arabic_font_object"]

    assert len(code) == font_object + 4
    assert int.from_bytes(code[font_object:], "little") == overlay.ARABIC_FONT_ADDRESS
    # Thumb returns into the original text loop, measurement loop and HBlank table code.
    for address in (0x081514D3, 0x081514F1, 0x081513D5, 0x08150EFF, 0x081519EF, 0x0813BFCB):
        assert address in words
    assert sorted(overlay.HOOK_SYMBOLS.values()) == list(overlay.HOOK_SYMBOLS.values())


def test_hook_sites_become_literal_jumps():
    for site in overlay.HOOK_SITES:
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        patched = site.replacement(target)
        assert len(patched) == len(site.original)
        ldr, bx = int.from_bytes(patched[:2], "little"), int.from_bytes(patched[2:4], "little")
        assert ldr >> 11 == 0b01001 and (ldr >> 8) & 7 == site.register
        assert bx == 0x4700 | site.register << 3
        literal = (site.address + 4 & ~3) + 4 * (ldr & 0xFF)
        assert literal % 4 == 0 and literal >= site.address + 4
        start = literal - site.address
        assert int.from_bytes(patched[start : start + 4], "little") == target | 1
