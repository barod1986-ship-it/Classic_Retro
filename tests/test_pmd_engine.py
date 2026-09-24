from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pmd import (
    ENTRY_BYTES,
    GLYPH_BYTES,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    NEWLINE_COMMAND,
    ROM_BASE,
    PmdCharmap,
    PmdCommand,
    PmdGlyphEntry,
    bitmap_pixels,
    character_at,
    command_skeleton,
    format_command,
    glyph_bitmap,
    line_widths,
    notation_skeleton,
    parse_notation,
    pmd_notation,
    read_string,
    split_text,
)


def test_format_commands_placeholders_and_line_ends_are_split_from_text():
    data = b"#+OK...#W\n#+Let the $m0 in~2c $n1!#P#C\x05Hi#R"
    pieces = split_text(data)

    assert pieces[0] == format_command("CENTER_ALIGN")
    assert pieces[1] == "OK..."
    assert pieces[2].notation == "{WAIT_PRESS}" and pieces[3] is NEWLINE_COMMAND
    assert "".join(piece for piece in pieces if isinstance(piece, str)) == "OK...Let the  in, !Hi"
    assert pmd_notation(data) == (
        "{CENTER_ALIGN}OK...{WAIT_PRESS}\n{CENTER_ALIGN}Let the {POKEMON_0} in, {NAME_1}!"
        "{EXTRA_MSG}{COLOR:05}Hi{RESET}"
    )
    assert command_skeleton(data) == (
        "{CENTER_ALIGN}",
        "{WAIT_PRESS}",
        "{CENTER_ALIGN}",
        "{POKEMON_0}",
        "{NAME_1}",
        "{EXTRA_MSG}",
        "{COLOR:05}",
        "{RESET}",
    )


def test_characters_follow_get_next_char_from_str():
    assert character_at(b"~2c", 0) == (0x2C, 3)
    assert character_at(b"\x84\x40x", 0) == (0x8440, 2)
    assert character_at(b"\xe9", 0) == (0xE9, 1)
    assert pmd_notation(b"Pok\xe9mon \x87\x40 #x") == "Pokémon {CHAR:8740} #x"
    for broken in (b"~2", b"~zz", b"\x84"):
        with pytest.raises(ClassicRetroError):
            split_text(broken)
    with pytest.raises(ClassicRetroError):
        split_text(b"a\x00b")


def test_commands_with_arguments_and_dots():
    data = b"#=\x40.x#~\x10y#>12.z#[cb]w$v03$$"
    notation = pmd_notation(data)

    assert notation == (
        "{MOVE_X_POSITION:40.}x{WAIT_FRAMES:10}y{ALIGN_X:31322E}z{CALLBACK:63625D}w"
        "{NUMBER_0_3}{DOLLAR}"
    )
    with pytest.raises(ClassicRetroError) as caught:
        split_text(b"$q")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_notation_parses_back_to_the_game_bytes():
    pieces = parse_notation("{CENTER_ALIGN}أ\n{WAIT_PRESS}{COLOR:07}ب")

    assert [piece.data for piece in pieces if isinstance(piece, PmdCommand)] == [
        b"#+",
        b"\n",
        b"#W",
        b"#C\x07",
    ]
    assert notation_skeleton(pieces) == ("{CENTER_ALIGN}", "{WAIT_PRESS}", "{COLOR:07}")
    for bad in ("{POKEMON_0}", "{COLOR}", "a}b", "{nope}"):
        with pytest.raises(ClassicRetroError):
            parse_notation(bad)


def test_line_widths_add_glyph_widths_per_line_and_box():
    widths = {ord("a"): 5, ord("b"): 3, 0x8440: 7}
    assert line_widths(b"ab\na#Pb\x84\x40#Wa", widths) == (8, 5, 15)
    with pytest.raises(ClassicRetroError) as caught:
        line_widths(b"z", widths)
    assert caught.value.code is ErrorCode.MISSING_GLYPH


def test_glyph_bitmaps_hold_12_rows_of_12_nibbles():
    pixels = [[(x + y) % 16 for x in range(GLYPH_COLUMNS)] for y in range(GLYPH_ROWS)]
    data = glyph_bitmap(pixels)

    assert len(data) == GLYPH_BYTES
    # Pixel 0 is the low nibble of the row's first halfword.
    assert data[0] & 0xF == 0 and data[0] >> 4 == 1
    assert bitmap_pixels(data) == tuple(tuple(row) for row in pixels)
    with pytest.raises(ClassicRetroError):
        glyph_bitmap([[0] * 12] * 11)
    with pytest.raises(ClassicRetroError):
        glyph_bitmap([[16] * 12] * 12)


def _charmap_rom(codes: list[int]) -> tuple[bytes, int]:
    rom = bytearray(0x10000)
    siro, table, entries, bitmaps = 0x100, 0x200, 0x300, 0x2000
    rom[siro : siro + 8] = b"SIRO" + struct.pack("<I", ROM_BASE + table)
    rom[table : table + 8] = struct.pack("<iI", len(codes), ROM_BASE + entries)
    for number, code in enumerate(codes):
        entry = PmdGlyphEntry(code, 4 + number, 0, 2, ROM_BASE + bitmaps + number * GLYPH_BYTES)
        rom[entries + number * ENTRY_BYTES : entries + (number + 1) * ENTRY_BYTES] = entry.pack()
        pixels = [[0xF if x == number else 0 for x in range(12)] for _ in range(12)]
        start = bitmaps + number * GLYPH_BYTES
        rom[start : start + GLYPH_BYTES] = glyph_bitmap(pixels)
    return bytes(rom), ROM_BASE + siro


def test_charmap_parses_sorted_entries_and_bitmaps():
    rom, siro = _charmap_rom([0x20, 0x41, 0x8486])
    charmap = PmdCharmap.parse(rom, siro)

    assert [entry.code for entry in charmap.entries] == [0x20, 0x41, 0x8486]
    assert charmap.widths() == {0x20: 4, 0x41: 5, 0x8486: 6}
    assert charmap.entry(0x41).style == 2 and charmap.entry(0x42) is None
    assert charmap.pixels(rom, 0x41)[0][1] == 0xF
    with pytest.raises(ClassicRetroError):
        charmap.pixels(rom, 0x42)


def test_charmap_must_be_a_sorted_siro_file():
    rom, siro = _charmap_rom([0x41, 0x20])
    with pytest.raises(ClassicRetroError) as caught:
        PmdCharmap.parse(rom, siro)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError):
        PmdCharmap.parse(rom, siro + 4)


def test_strings_are_read_up_to_their_terminator():
    rom = b"\x00" * 16 + b"#+Hi\x00rest"
    assert read_string(rom, ROM_BASE + 16) == b"#+Hi"
    with pytest.raises(ClassicRetroError):
        read_string(rom, ROM_BASE + len(rom) + 4)
    with pytest.raises(ClassicRetroError):
        read_string(b"abc", ROM_BASE)
