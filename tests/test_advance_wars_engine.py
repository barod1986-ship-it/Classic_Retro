from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines import advance_wars as aw
from classic_retro.engines.advance_wars import (
    AwCommand,
    AwFont,
    command_skeleton,
    line_widths,
    message_text,
    notation_skeleton,
    parse_notation,
    read_message,
    split_text,
    text_bytes,
    text_notation,
)

# Invented messages in the engine's notation.
SAMPLES = (
    "Hello there!\nA second line.{0F}Your name: {15}.{0F}",
    "Ready?\n{16}",
    "{80}Red{81} and back{0E}{0C}{17}",
    "An icon {09 1A} and options {0B 81}{0B}{0A 05}.",
    "Odd bytes {char 84}{char 01}{char 7F} kept.",
)


@pytest.mark.parametrize("text", SAMPLES)
def test_notation_round_trips_through_bytes(text):
    data = text_bytes(parse_notation(text))
    assert text_notation(data) == text
    assert message_text(data + b"\x00junk", 0) == data


def test_control_codes_and_their_parameters():
    data = text_bytes(parse_notation("a{09 00}b{0B 89}c{0B}d\ne"))
    # 09's parameter may be 0x00: it does not end the message.
    assert data == b"a\x09\x00b\x0b\x89c\x0bd\x0de"
    pieces = split_text(data)
    assert pieces == (
        "a",
        AwCommand(b"\x09\x00"),
        "b",
        AwCommand(b"\x0b\x89"),
        "c",
        AwCommand(b"\x0b"),
        "d",
        AwCommand(b"\x0d"),
        "e",
    )
    assert pieces[7].notation == "\n" and pieces[7].is_newline
    assert message_text(data + b"\x00", 0) == data


def test_line_ends_after_text_are_not_part_of_the_skeleton():
    assert command_skeleton(text_bytes(parse_notation(SAMPLES[0]))) == ("{0F}", "{15}", "{0F}")
    assert command_skeleton(text_bytes(parse_notation(SAMPLES[1]))) == ("{16}",)
    # A line end after a control code stays.
    pieces = parse_notation("{0F}\nText")
    assert notation_skeleton(pieces) == ("{0F}", "\n")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{1F}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{0B 12}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{09}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{zz}", ErrorCode.UNENCODABLE_TEXT),
        ("oops}", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_bad_notation_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as error:
        parse_notation(text)
    assert error.value.code is code


def test_text_outside_the_font_is_refused():
    with pytest.raises(ClassicRetroError) as error:
        text_bytes(parse_notation("café"))
    assert error.value.code is ErrorCode.UNENCODABLE_TEXT


def test_a_message_needs_its_end():
    with pytest.raises(ClassicRetroError) as error:
        message_text(b"no end", 0)
    assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    with pytest.raises(ClassicRetroError) as error:
        read_message(bytes(8), aw.ROM_BASE + 8)
    assert error.value.code is ErrorCode.INVALID_REFERENCE


def _font_image(widths: dict[int, int]) -> bytes:
    """A small image with the font's two tables at their addresses and glyph rows."""
    size = aw.FONT_WIDTHS + 256 - aw.ROM_BASE + 64 * 256
    rom = bytearray(size)
    glyph_start = aw.FONT_WIDTHS + 256
    for code in range(256):
        width = widths.get(code, 0)
        address = glyph_start + 64 * code
        struct.pack_into("<I", rom, aw.FONT_POINTERS - aw.ROM_BASE + 4 * code, address)
        rom[aw.FONT_WIDTHS - aw.ROM_BASE + code] = width
        per_row = (width + 1) // 2
        for y in range(aw.GLYPH_ROWS):
            for x in range(width):
                if x == y % max(width, 1):
                    offset = address - aw.ROM_BASE + y * per_row + x // 2
                    rom[offset] |= 0xA << 4 * (x % 2)
    return bytes(rom)


def test_font_reads_packed_rows():
    font = AwFont.read(_font_image({0x41: 5, 0x2E: 1}))
    assert font.widths[0x41] == 5 and font.widths[0x42] == 0
    glyph = font.glyphs[0x41]
    assert len(glyph) == aw.GLYPH_ROWS and all(len(row) == 5 for row in glyph)
    assert glyph[0] == (0xA, 0, 0, 0, 0) and glyph[3] == (0, 0, 0, 0xA, 0)
    assert glyph[5] == (0xA, 0, 0, 0, 0)
    assert font.glyphs[0x2E][0] == (0xA,)


def test_font_refuses_glyphs_wider_than_the_printer_draws():
    with pytest.raises(ClassicRetroError) as error:
        AwFont.read(_font_image({0x41: 9}))
    assert error.value.code is ErrorCode.FONT_BUILD_FAILED


def test_lines_count_one_pixel_between_glyphs():
    font = AwFont.read(_font_image({0x41: 5, 0x42: 3, 0x20: 2}))
    data = text_bytes(parse_notation("AB A\nB{0F}AA"))
    # 5 + 1 + 3 + 1 + 2 + 1 + 5; then 3; then 5 + 1 + 5.
    assert line_widths(data, font) == (18, 3, 11)
