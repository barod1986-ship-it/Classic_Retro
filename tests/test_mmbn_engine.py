from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mmbn import (
    CELL_BYTES,
    SECTION_TRAILER,
    MmbnCommand,
    ScriptArchive,
    build_archive,
    cell_data,
    cell_pixels,
    command_length,
    command_skeleton,
    encode_text,
    glyph_code,
    parse_notation,
    script_bytes,
    script_notation,
    section_script,
    split_script,
)

# An invented scene in the engine's notation: a mugshot, the box, a line
# with the mouth moving, a wait inside the text, a key wait, a clear, a jump.
SCENE = "{pic 8 0}{dialog_up}<Hello,Robo!>{d 30}\n<Ready?>\\p{cls 5}{jump 3}"


def test_scene_encodes_and_decodes_back():
    data = script_bytes(parse_notation(SCENE))

    assert data.startswith(bytes.fromhex("ed000800f200ee02"))
    assert data.endswith(bytes.fromhex("ebe90500f60003"))
    assert script_notation(data) == SCENE
    assert script_bytes(split_script(data)) == data


def test_characters_follow_the_usa_font():
    assert encode_text("Az09 -") == bytes([0x5F, 0x92, 0x01, 0x0A, 0x00, 0x5E])
    # Punctuation is E5 + a byte; the game draws it as glyph 0xE5 + that byte.
    assert encode_text("!.,?") == bytes.fromhex("e500e516e514e502")
    assert glyph_code(".") == 0xE5 + 0x16
    assert glyph_code("A") == 0x5F
    # Codes without a character here keep their bytes as {char ..}.
    assert script_notation(bytes([0x93, 0xE5, 0x06])) == "{char 93}{char E506}"
    assert encode_text("{char 93}{char E506}") == bytes([0x93, 0xE5, 0x06])
    with pytest.raises(ClassicRetroError) as caught:
        encode_text("é")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_command_lengths_follow_the_layout_tables():
    assert command_length(bytes.fromhex("f40c1234ffff"), 0) == 6
    assert command_length(bytes.fromhex("f408123400"), 0) == 5
    assert command_length(bytes.fromhex("fa04"), 0) == 3
    # A choice carries its own length; rewards grow with their count.
    assert command_length(bytes.fromhex("f10580aabb"), 0) == 5
    assert command_length(bytes.fromhex("fd000200"), 0) == 6 + 2 * 4
    assert command_length(bytes.fromhex("fd040300"), 0) == 6 + 3 * 2
    assert command_length(bytes.fromhex("fd10"), 0) == 9
    with pytest.raises(ClassicRetroError) as caught:
        command_length(bytes.fromhex("f455"), 0)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_skeleton_skips_line_ends_and_item_names():
    data = script_bytes(parse_notation("{dialog_up}Take the\n{key 0}!\\p{end 5}"))

    assert command_skeleton(data) == ("{dialog_up}", "\\p", "{end 5}")
    key = MmbnCommand(bytes.fromhex("fb000000"), "{key 0}")
    assert key.is_key_print and not key.is_newline


def test_named_and_raw_commands_parse_to_the_same_bytes():
    (named,) = parse_notation("{cls}")
    assert named.data == bytes.fromhex("e90000") and named.notation == "{cls 0}"
    (raw,) = parse_notation("{raw F3 00 80 02}")
    assert raw.data == bytes.fromhex("f3008002") and raw.notation == "{raw F3 00 80 02}"
    (jump,) = parse_notation("{raw F6 00 07}")
    assert jump.notation == "{jump 7}"
    for bad in ("{raw F3 00}", "{nope}", "{jump}", "{d 70000}", "text}", "\\q", "{char 93"):
        with pytest.raises(ClassicRetroError):
            script_bytes(parse_notation(bad))


def test_a_section_ends_at_its_ending_command():
    body = script_bytes(parse_notation("{dialog_up}Hi\\p{end 5}"))
    data = body + SECTION_TRAILER + b"\x5f\x5f"

    assert section_script(data, 0) == body
    # F6 00 FF does not jump: the script goes on.
    going_on = script_bytes(parse_notation("Hi{raw F6 00 FF}Yo{jump 2}"))
    assert section_script(going_on, 0) == going_on
    with pytest.raises(ClassicRetroError) as caught:
        section_script(b"\x5f\x5f", 0)
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_archive_builds_and_parses_back():
    first = script_bytes(parse_notation("{dialog_up}One\\p{end 0}"))
    second = script_bytes(parse_notation("{dialog_up}Two\\p{jump 0}"))
    data = build_archive([first + SECTION_TRAILER, SECTION_TRAILER, second + SECTION_TRAILER])
    rom = bytes(0x100) + data + bytes.fromhex("cc01")
    archive = ScriptArchive.parse(rom, 0x08000100)

    assert len(data) % 4 == 0
    assert archive.offsets == (6, 6 + len(first) + 2, 6 + len(first) + 4)
    assert archive.section(rom, 0) == first
    assert archive.section(rom, 2) == second
    assert archive.extent(rom, 1) == SECTION_TRAILER
    assert archive.extent(rom, 2) == second + SECTION_TRAILER


def test_empty_last_section_is_only_the_trailer():
    data = build_archive([SECTION_TRAILER, SECTION_TRAILER])
    rom = data + bytes.fromhex("5f5f5f5f")
    archive = ScriptArchive.parse(rom, 0x08000000)

    assert archive.extent(rom, 1) == SECTION_TRAILER


def test_archive_rejects_a_bad_table():
    with pytest.raises(ClassicRetroError) as caught:
        ScriptArchive.parse(struct.pack("<HH", 3, 9) + bytes(16), 0x08000000)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError):
        ScriptArchive.parse(struct.pack("<HH", 8, 4) + bytes(16), 0x08000000)


def test_cells_are_two_4bpp_tiles():
    pixels = [[(x + y) % 4 for x in range(8)] for y in range(16)]
    data = cell_data(pixels)

    assert len(data) == CELL_BYTES
    assert data[0] == 0x10 and data[4] == 0x21
    assert cell_pixels(data) == tuple(tuple(row) for row in pixels)
    with pytest.raises(ClassicRetroError):
        cell_data([[0] * 8] * 15)
