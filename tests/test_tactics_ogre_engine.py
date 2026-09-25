from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tactics_ogre import (
    FONT_GLYPHS,
    FONT_WIDTHS,
    GLYPH_BYTES,
    GLYPH_CODES,
    INSTANT,
    LAST_WAIT,
    LATIN_CODES,
    NAME,
    NAME_LIST,
    NEW_PAGE,
    NEWLINE,
    PAGE_WAIT,
    ROM_BASE,
    SCENE_TEXTS,
    SPACE,
    SPACE_WIDTH,
    TABLE_END,
    TYPED,
    ToCommand,
    ToFont,
    command_skeleton,
    encode_text,
    lay_out,
    lines_per_page,
    notation_skeleton,
    page_lines,
    parse_notation,
    pieces_bytes,
    read_block,
    read_message,
    read_name,
    scene_block_address,
    split_text,
    text_bytes,
    text_notation,
)

# An invented message in the engine's notation.
MESSAGE = "{8B}Old Sailor{8C}\nFair winds,\n friend {8705}.{8E}{8A}The tide turns at 9!{8D}{8A}"


def test_latin_codes_follow_the_font():
    assert LATIN_CODES[0x00] == "A" and LATIN_CODES[0x19] == "Z"
    assert LATIN_CODES[0x1A] == "a" and LATIN_CODES[0x33] == "z"
    assert LATIN_CODES[0x34] == "0" and LATIN_CODES[0x3D] == "9"
    assert (LATIN_CODES[0x3E], LATIN_CODES[0x40], LATIN_CODES[0x46]) == ("!", ".", "'")
    assert LATIN_CODES[0x51] == '"' and LATIN_CODES[0x52] == "…"
    assert all(code < GLYPH_CODES for code in LATIN_CODES)
    assert len(set(LATIN_CODES.values())) == len(LATIN_CODES)


def test_notation_round_trips_through_bytes():
    data = pieces_bytes(parse_notation(MESSAGE))
    assert data[:2] == bytes((INSTANT, 0x0E))
    assert bytes((NAME, 0x05)) in data
    assert data.count(SPACE) == 8 and data.count(NEWLINE) == 2
    assert text_notation(data) == MESSAGE
    assert text_notation(bytes((0x50, 0x55, SPACE))) == "{char 50}{char 55} "


def test_pieces_are_text_runs_and_commands():
    pieces = split_text(pieces_bytes(parse_notation(MESSAGE)))
    assert pieces[0] == ToCommand(INSTANT)
    assert pieces[1] == "Old Sailor"
    assert pieces[2] == ToCommand(TYPED)
    assert pieces[3] == ToCommand(NEWLINE)
    assert ToCommand(NAME, 5) in pieces
    assert ToCommand(NAME, 5).notation == "{8705}" and ToCommand(NEWLINE).notation == "\n"
    assert ToCommand(NAME, 5).is_inline and not ToCommand(PAGE_WAIT).is_inline


@pytest.mark.parametrize(
    ("code", "argument"),
    [(NAME, None), (NEW_PAGE, 1), (0x85, 0x20), (0x92, None), (SPACE, None), (0x20, None)],
)
def test_commands_take_their_byte_or_none(code, argument):
    with pytest.raises(ClassicRetroError) as caught:
        ToCommand(code, argument)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


@pytest.mark.parametrize("text", ["{85}", "{9A}", "{char 80}", "{88}", "{8705", "a}"])
def test_bad_notation_is_refused(text):
    with pytest.raises(ClassicRetroError):
        pieces_bytes(parse_notation(text))


def test_a_choice_and_unknown_bytes_are_not_read():
    for code in (0x85, 0x92, 0xFE):
        with pytest.raises(ClassicRetroError) as caught:
            split_text(bytes((0x00, code, 0x01)))
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_encode_text_knows_only_the_font():
    assert encode_text("Hi 5") == bytes((0x07, 0x22, SPACE, 0x39))
    with pytest.raises(ClassicRetroError) as caught:
        encode_text("é")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_skeleton_lets_line_ends_after_text_move():
    skeleton = command_skeleton(pieces_bytes(parse_notation(MESSAGE)))
    assert skeleton == ("{8B}", "{8C}", "{8705}", "{8E}", "{8A}", "{8D}", "{8A}")
    # A line end after a name alone (no text) keeps its place.
    alone = notation_skeleton(parse_notation("{8B}{8705}{8C}\nHi.{8D}{8A}"))
    assert alone == ("{8B}", "{8705}", "{8C}", "\n", "{8D}", "{8A}")
    # A line end after a page break starts the page: it keeps its place too.
    assert "\n" in notation_skeleton(parse_notation("Hi.{8E}{8A}\nHo."))


def test_text_bytes_stop_at_ff_but_not_inside_a_command():
    data = bytes((0x00, NAME, 0xFF, 0x01, 0xFF, 0x02))
    assert text_bytes(data, 0) == data[:4]
    with pytest.raises(ClassicRetroError) as caught:
        text_bytes(bytes((0x00, 0x01)), 0)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def _image() -> bytearray:
    return bytearray(0x800000)


def _put(rom: bytearray, address: int, data: bytes) -> None:
    rom[address - ROM_BASE : address - ROM_BASE + len(data)] = data


def test_blocks_messages_and_names_are_read_from_the_image():
    rom = _image()
    block = 0x08790000
    first = pieces_bytes(parse_notation("Hello."))
    second = pieces_bytes(parse_notation("{8B}Bo{8C}\nYes.{8D}{8A}"))
    _put(rom, SCENE_TEXTS + 4 * 3, struct.pack("<I", block - SCENE_TEXTS))
    _put(rom, block, struct.pack("<3H", 6, 16, TABLE_END))
    _put(rom, block + 6, struct.pack("<H", 0x0021) + first + b"\xff\x00")
    _put(rom, block + 16, struct.pack("<H", 0x0031) + second + b"\xff")
    _put(rom, NAME_LIST + 4 * 2, struct.pack("<I", 0x08791001))
    _put(rom, 0x08791001, pieces_bytes(parse_notation("Mira")) + b"\xff")

    assert scene_block_address(bytes(rom), 3) == block
    parsed = read_block(bytes(rom), block)
    assert parsed.offsets == (6, 16) and parsed.message_address(1) == block + 16
    header, data = read_message(bytes(rom), parsed.message_address(0))
    assert (header, data) == (0x0021, first) and lines_per_page(header) == 2
    header, data = read_message(bytes(rom), parsed.message_address(1))
    assert (header, data) == (0x0031, second) and lines_per_page(header) == 3
    assert read_name(bytes(rom), 2) == pieces_bytes(parse_notation("Mira"))
    with pytest.raises(ClassicRetroError):
        scene_block_address(bytes(rom), 70)
    with pytest.raises(ClassicRetroError):
        read_message(bytes(rom), 0x09000000)


def test_font_reads_widths_and_glyphs_row_by_row():
    rom = _image()
    widths = bytes(range(GLYPH_CODES))
    glyphs = bytearray(GLYPH_BYTES * GLYPH_CODES)
    # Glyph 3: pixel (1, 0) ink, pixel (7, 15) grey.
    glyphs[3 * GLYPH_BYTES] = 0x10
    glyphs[3 * GLYPH_BYTES + 63] = 0x20
    _put(rom, FONT_WIDTHS, widths)
    _put(rom, FONT_GLYPHS, bytes(glyphs))
    font = ToFont.read(bytes(rom))
    assert font.width(5) == 5 and font.width(SPACE) == SPACE_WIDTH
    glyph = font.glyph(3)
    assert len(glyph) == 16 and all(len(row) == 8 for row in glyph)
    assert glyph[0][1] == 1 and glyph[15][7] == 2
    assert sum(value for row in glyph for value in row) == 3


def test_lay_out_places_glyphs_from_the_left_on_lines_and_pages():
    data = pieces_bytes(parse_notation("{8B}ab{8C}\nc d{8E}{8A}e{8D}{8A}"))
    lines = lay_out(data, lambda code: 3 if code == SPACE else 5)
    assert [(line.page, line.number) for line in lines] == [(0, 0), (0, 1), (1, 0), (2, 0)]
    assert [place.pen for place in lines[1].places] == [0, 5, 8]
    assert lines[0].width == 10 and lines[1].width == 13
    assert lines[1].waits and lines[2].waits and not lines[0].waits
    assert not lines[3].places
    assert page_lines(lines) == {0: 2, 1: 1, 2: 1}
    assert LAST_WAIT in data and PAGE_WAIT in data
