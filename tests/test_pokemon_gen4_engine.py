"""The fourth-generation Pokémon text engine: banks, notation, fonts and layout.

Every bank, string and font here is invented; none holds game data.
"""

from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen4 import (
    CLEAR,
    COMPRESSED,
    EOS,
    FORMAT,
    NEWLINE,
    QUESTION,
    SCROLL,
    SPACE,
    YESNO,
    Gen4Command,
    Gen4Font,
    MessageBank,
    command_skeleton,
    encode_text,
    lay_out,
    notation_skeleton,
    pack_2bpp,
    parse_notation,
    pieces_codes,
    split_text,
    text_notation,
    unpack_2bpp,
)


def _codes(text: str) -> tuple[int, ...]:
    return pieces_codes(parse_notation(text))


def test_a_bank_is_encrypted_as_the_game_reads_it():
    bank = MessageBank(0x1234, ((0x0121, EOS),))
    # The entry XORed with 0x6564 (0x1234 * 765, 16 bits) in both halves; the
    # characters with 596947 (16 bits: 0x1BD3), then 0x1BD3 + 18749.
    assert bank.build() == bytes.fromhex("010034126865646566656465f21aef9a")
    assert MessageBank.read(bank.build()) == bank


def test_a_bank_is_read_back_and_its_strings_replaced():
    strings = (_codes("Hi!"), _codes("{STRVAR_1 3, 0, 0}\nOK"), (EOS,))
    bank = MessageBank(0xBEEF, strings)
    data = bank.build()
    assert MessageBank.read(data) == bank
    # The second string's first character is XORed with 2 * 596947 (16 bits).
    body = 4 + 8 * 3 + 2 * len(strings[0])
    assert int.from_bytes(data[body : body + 2], "little") == FORMAT ^ 0x37A6
    replaced = bank.replaced({1: (0x0145, EOS)})
    assert replaced.strings == (strings[0], (0x0145, EOS), strings[2])
    assert MessageBank.read(replaced.build()) == replaced
    for strings_, code in (
        ({3: (EOS,)}, ErrorCode.INVALID_REFERENCE),
        ({0: (0x0121,)}, ErrorCode.MISSING_TERMINATOR),
        ({0: (EOS, 0x0121, EOS)}, ErrorCode.MISSING_TERMINATOR),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            bank.replaced(strings_)
        assert caught.value.code is code
    for broken in (data[:2], data[:12], data[:-2]):
        with pytest.raises(ClassicRetroError) as caught:
            MessageBank.read(broken)
        assert caught.value.code is ErrorCode.CONTAINER_REBUILD_FAILED


def test_the_notation_writes_every_code_and_reads_it_back():
    text = (
        "Hello, {STRVAR_1 3, 0, 0}!\rAre you ready?{YESNO 0}\n"
        "{COLOR 1}Go…{CMD_0207 1, 2}\fé{char 01FE}"
    )
    codes = _codes(text)
    assert text_notation(codes) == text
    assert codes[:3] == (0x012B + 7, 0x0145 + 4, 0x0145 + 11)
    # "," then the space, then the player's name.
    assert codes[5:7] == (0x019F + 14, SPACE)
    assert codes[7:12] == (FORMAT, 0x0103, 2, 0, 0)
    assert CLEAR in codes and NEWLINE in codes and SCROLL in codes
    assert (FORMAT, YESNO, 1, 0) == codes[codes.index(YESNO) - 1 : codes.index(YESNO) + 3]
    assert codes[-4:] == (SCROLL, 0x0188, 0x01FE, EOS)
    assert encode_text("?0aZ ") == (QUESTION, 0x0121, 0x0145, 0x012B + 25, SPACE)
    assert encode_text("…é{char 01FE}") == (0x01AF, 0x0188, 0x01FE)
    pieces = split_text(codes)
    assert pieces[0] == "Hello, " and pieces[1] == Gen4Command(0x0103, (0, 0))
    assert pieces[1].is_string_variable and not pieces[1].is_break
    assert Gen4Command(0xFF00, (1,)).notation == "{COLOR 1}"
    assert Gen4Command(0x0207, (1, 2)).notation == "{CMD_0207 1, 2}"
    assert Gen4Command(0x0134, (1,)).notation == "{STRVAR_1 52, 1}"
    assert parse_notation("{STRVAR_34 1, 0}") == (Gen4Command(0x3401, (0,)),)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{JUMP 1}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{CMD_XYZ1 1}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{STRVAR_2 1}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{STRVAR_1}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("a}b", ErrorCode.UNENCODABLE_TEXT),
        ("ж", ErrorCode.UNENCODABLE_TEXT),
        ("{char E000}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
    ],
)
def test_the_notation_refuses_what_the_game_cannot_show(text, code):
    with pytest.raises(ClassicRetroError) as caught:
        _codes(text)
    assert caught.value.code is code


def test_codes_the_engine_does_not_read_are_refused():
    for codes, code in (
        ((COMPRESSED, 0x1234, EOS), ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ((FORMAT, 0x0103, 2, 0), ErrorCode.TOKEN_ORDER_VIOLATION),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            split_text(codes)
        assert caught.value.code is code
    for command in ((NEWLINE, (1,)), (YESNO, (0x10000,))):
        with pytest.raises(ClassicRetroError) as caught:
            Gen4Command(*command)
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_the_skeleton_keeps_every_command_but_the_line_ends_after_text():
    text = "A\nB\rC{STRVAR_1 3, 0, 0}\nD\fE"
    # The line end after the name still follows the text of its line.
    assert notation_skeleton(parse_notation(text)) == ("\r", "{STRVAR_1 3, 0, 0}", "\f")
    assert command_skeleton(_codes(text)) == ("\r", "{STRVAR_1 3, 0, 0}", "\f")
    # A line end with no text before it on its line (a blank row, a line that is
    # only a name) stays.
    assert notation_skeleton(parse_notation("\nA\r\nB")) == ("\n", "\r", "\n")
    assert notation_skeleton(parse_notation("{STRVAR_1 3, 0, 0}\nA")) == (
        "{STRVAR_1 3, 0, 0}",
        "\n",
    )


# ---------------------------------------------------------------------------
# Fonts


def _pixels(value: int, x: int, y: int) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(value if (px, py) == (x, y) else 0 for px in range(16)) for py in range(16))


def _font(count: int = QUESTION) -> Gen4Font:
    """``count`` glyphs of 16x16, each with one pixel; widths 1 to 16 in turn."""
    glyphs = b"".join(
        pack_2bpp(_pixels(1 + n % 3, n % 16, n // 16 % 16), 2, 2) for n in range(count)
    )
    return Gen4Font(16, 16, 2, 2, glyphs, bytes(1 + n % 16 for n in range(count)))


def test_2bpp_tiles_hold_pixel_0_in_the_top_bits_of_a_little_endian_row():
    row = (1, 2, 3, 0, 0, 0, 0, 1)
    tile = (row, *((0,) * 8 for _ in range(7)))
    assert pack_2bpp(tile, 1, 1)[:2] == bytes.fromhex("016c")
    assert unpack_2bpp(pack_2bpp(tile, 1, 1), 1, 1) == tile
    # The second tile of a 16x16 glyph is its top right.
    data = pack_2bpp(_pixels(3, 9, 0), 2, 2)
    assert data[16:18] == (3 << 12).to_bytes(2, "little") and data.count(0) == 63
    assert unpack_2bpp(data, 2, 2) == _pixels(3, 9, 0)
    for pixels in (((0,) * 8,) * 7, (((4,) + (0,) * 7),) + ((0,) * 8,) * 7):
        with pytest.raises(ClassicRetroError) as caught:
            pack_2bpp(pixels, 1, 1)
        assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_a_font_is_read_built_and_extended():
    font = _font()
    data = font.build()
    assert data[:16] == (16).to_bytes(4, "little") + (16 + 64 * QUESTION).to_bytes(
        4, "little"
    ) + QUESTION.to_bytes(4, "little") + bytes((16, 16, 2, 2))
    assert Gen4Font.read(data) == font and font.count == QUESTION
    assert font.width(1) == 1 and font.width(16) == 16 and font.width(17) == 1
    # A code past the last glyph (or 0) draws '?', with its width.
    assert font.width(QUESTION + 1) == font.width(0) == font.width(QUESTION) == font.widths[-1]
    assert font.glyph(18) == _pixels(1 + 17 % 3, 1, 1)
    extended = font.with_glyphs([(_pixels(1, 3, 4), 9), (_pixels(2, 0, 0), 16)])
    assert extended.count == QUESTION + 2 and extended.width(QUESTION + 2) == 16
    assert extended.glyph(QUESTION + 1) == _pixels(1, 3, 4)
    assert Gen4Font.read(extended.build()) == extended
    with pytest.raises(ClassicRetroError) as caught:
        font.with_glyphs([(_pixels(1, 0, 0), 17)])
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED
    for broken in (data[:12], b"\x20" + data[1:], data[: 16 + 64 * QUESTION]):
        with pytest.raises(ClassicRetroError) as caught:
            Gen4Font.read(broken)
        assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


# ---------------------------------------------------------------------------
# Layout


def test_lines_follow_rows_scrolls_and_pages():
    codes = _codes("AB\nC\fD\rE{STRVAR_1 3, 0, 0}F{YESNO 0}")
    lines = lay_out(codes, lambda code: 6, rows=2, name_width=48)
    assert [(line.page, line.row, line.scrolled, line.icon) for line in lines] == [
        (0, 0, False, False),
        (0, 1, False, False),
        (0, 1, True, False),
        (1, 0, False, True),
    ]
    assert [line.width for line in lines] == [12, 6, 6, 60]
    name = lines[3].places[1]
    assert (name.code, name.pen, name.width, name.end) == (None, 6, 48, 54)
    assert lines[3].places[2].pen == 54


@pytest.mark.parametrize(
    ("text", "message"),
    [("A\nB\nC", "needs row 3"), ("A\fB", "scrolls from the window's last row")],
)
def test_a_string_that_leaves_its_window_is_refused(text, message):
    with pytest.raises(ClassicRetroError, match=message) as caught:
        lay_out(_codes(text), lambda code: 6, rows=2, name_width=48)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError) as caught:
        lay_out((FORMAT, 0x0103), lambda code: 6, rows=2, name_width=48)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
