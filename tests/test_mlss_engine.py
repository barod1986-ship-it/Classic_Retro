from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mlss import (
    ROM_BASE,
    MlssCommand,
    MlssEngineAdapter,
    MlssFont,
    MlssMessage,
    command_length,
    command_skeleton,
    encode_text,
    glyph_bytes,
    glyph_pixels,
    measure_text,
    notation_skeleton,
    parse_notation,
    split_text,
    text_bytes,
    text_notation,
)

EMPTY_8 = bytes(24)


def _font(width: int = 5, *, cell_width: int = 8, widths: dict[int, int] | None = None) -> MlssFont:
    size = cell_width * 12 // 4
    advances = [width] * 256
    for code, advance in (widths or {}).items():
        advances[code] = advance
    return MlssFont(cell_width, 12, tuple(advances), (bytes(size),) * 256)


def _fonts(*extra: MlssFont | None) -> list[MlssFont | None]:
    fonts: list[MlssFont | None] = [_font(), *extra]
    return fonts + [None] * (6 - len(fonts))


def test_engine_adapter_id():
    assert MlssEngineAdapter().id == "gba.mlss"
    assert MlssEngineAdapter().platform_ids == ("gba",)


def test_command_lengths_follow_the_parameter_codes():
    assert command_length(b"\xff\x00", 0) == 2
    assert command_length(b"\xff\x35", 0) == 2
    assert command_length(b"\xff\x0a", 0) == 2
    for code in (0x01, 0x0B, 0x0C, 0x11):
        assert command_length(bytes((0xFF, code, 0x00)), 0) == 3
    for data in (b"\xff", b"\xff\x0c", b"ab\xff\x01"):
        with pytest.raises(ClassicRetroError) as caught:
            command_length(data, data.index(0xFF))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_message_reads_its_header_and_text_up_to_ff_0a():
    body = b"\xff\x0b\x01Two words\xff\x00and more\xff\x11\x01\xff\x0a"
    rom = bytes(16) + b"\x09\x03" + body + b"\0\0" + b"\x04\x02tail"
    message = MlssMessage.read(rom, ROM_BASE + 16)

    assert (message.width_tiles, message.height_tiles) == (9, 3)
    assert message.body == body
    assert message.data == b"\x09\x03" + body
    stored = message.stored()
    assert stored.startswith(message.data + b"\0") and len(stored) % 4 == 0
    # A message that ends on a word boundary still gets its zero.
    aligned = MlssMessage(1, 2, b"abcd\xff\x0a")
    assert aligned.stored() == b"\x01\x02abcd\xff\x0a\0\0\0\0"
    with pytest.raises(ClassicRetroError) as caught:
        MlssMessage.read(b"\x01\x02abc\0\0\0", ROM_BASE)
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR
    with pytest.raises(ClassicRetroError) as caught:
        MlssMessage.read(rom, ROM_BASE + len(rom))
    assert caught.value.code is ErrorCode.REFERENCE_OUT_OF_BOUNDS


def test_notation_round_trips_every_byte():
    body = b"\xff\x0b\x01A {x}\x1c\x1d\xff\x00b\xff\x2bc\xff\x20\xff\x0c\x1e\xff\x0a"
    notation = text_notation(body)

    assert notation == (
        "{FF 0B 01}A {char 7B}x{char 7D}{char 1C}{char 1D}\nb{FF 2B}c{FF 20}{FF 0C 1E}{FF 0A}"
    )
    assert text_bytes(parse_notation(notation)) == body
    pieces = split_text(body)
    assert isinstance(pieces[0], MlssCommand) and pieces[0].data == b"\xff\x0b\x01"
    assert pieces[-1].is_end and not pieces[-1].is_page
    assert encode_text("Hi {char 1C}") == b"Hi \x1c"


@pytest.mark.parametrize(
    ("notation", "code"),
    [
        ("{FF 0B}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{FF 00 01}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{oops}", ErrorCode.UNENCODABLE_TEXT),
        ("stray }", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_bad_notation_is_rejected(notation, code):
    with pytest.raises(ClassicRetroError) as caught:
        parse_notation(notation)
    assert caught.value.code is code


def test_text_outside_the_fonts_is_rejected():
    with pytest.raises(ClassicRetroError) as caught:
        encode_text("café")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_skeleton_drops_only_the_line_ends_after_text():
    pieces = parse_notation("{FF 0B 01}\n{FF 35}one\ntwo{FF 11 01}{FF 0A}")

    assert notation_skeleton(pieces) == ("{FF 0B 01}", "\n", "{FF 35}", "{FF 11 01}", "{FF 0A}")
    assert command_skeleton(text_bytes(pieces)) == notation_skeleton(pieces)
    # Moving the line end inside the text keeps the skeleton.
    moved = parse_notation("{FF 0B 01}\n{FF 35}o\nnetwo{FF 11 01}{FF 0A}")
    assert notation_skeleton(moved) == notation_skeleton(pieces)


@pytest.mark.parametrize("width", [8, 12, 16])
def test_glyph_planes_round_trip(width):
    values = (0, 1, 3)
    pixels = tuple(tuple(values[(x * 7 + y * 5) % 3] for x in range(width)) for y in range(12))
    data = glyph_bytes(pixels, width, 12)

    assert len(data) == width * 12 // 4
    assert glyph_pixels(data, width, 12) == pixels


def test_glyph_layout_matches_the_printer():
    pixels = [[0] * 16 for _ in range(12)]
    pixels[5][9] = 3
    pixels[0][0] = 1
    data = glyph_bytes(pixels, 16, 12)

    # Left half: row groups of two plane words; column 0, row 0 is bit 0 of plane 0.
    assert struct.unpack_from("<II", data, 0) == (1, 0)
    # Right half after the 24 bytes of the left: group 1 (rows 4-7), column 1, row 1.
    assert struct.unpack_from("<II", data, 24 + 8) == (1 << 5, 1 << 5)
    with pytest.raises(ClassicRetroError):
        glyph_bytes([[2] * 8 for _ in range(12)], 8, 12)
    with pytest.raises(ClassicRetroError):
        glyph_bytes([[0] * 8 for _ in range(12)], 10, 12)


def test_font_packs_and_reads_back():
    widths = tuple(code % 16 + 1 for code in range(256))
    glyphs = tuple(bytes((code,)) * 24 for code in range(256))
    font = MlssFont(8, 12, widths, glyphs)
    data = font.pack()

    assert data[:4] == b"\x23\0\0\0"
    assert len(data) == 4 + 128 + 256 * 24
    assert MlssFont.read(bytes(64) + data, ROM_BASE + 64) == font
    assert font.pixels(0) == tuple((0,) * 8 for _ in range(12))
    with pytest.raises(ClassicRetroError) as caught:
        MlssFont.read(b"\x77\0\0\0" + data[4:], ROM_BASE)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError):
        MlssFont(8, 12, (0,) * 256, glyphs).pack()


def test_measure_follows_the_game_rule():
    body = b"\xff\x0b\x01ab c\xff\x00\xff\x33ab\xff\x11\x01\xff\x0a"
    layout = measure_text(body, _fonts())

    # a b space c; then two double-width glyphs on a double-height line.
    assert layout.line_widths == (21, 20)
    assert layout.page_heights == (12 + 24,)
    assert layout.header() == (3, 5)


def test_measure_pages_spaces_moves_and_prefixed_fonts():
    pages = measure_text(b"ab\xff\x01\x00\xff\x0b\x01\xff\x00abc\xff\x0a", _fonts())
    assert pages.line_widths == (10, 0, 15)
    assert pages.page_heights == (12, 24)

    spaced = measure_text(b"\xff\x53a a\xff\x61a\xff\x81\xff\x0a", _fonts())
    assert spaced.line_widths == (5 + 3 + 5 + 2 + 5,)

    wide = _font(cell_width=16, widths={0x41: 9})
    prefixed = measure_text(b"a\xfe\x41\xff\x0a", _fonts(wide))
    assert prefixed.line_widths == (5 + 9,)
    # Without font 1 the prefix is an ordinary character of font 0.
    plain = measure_text(b"a\xfe\x41\xff\x0a", _fonts())
    assert plain.line_widths == (15,)
    with pytest.raises(ClassicRetroError) as caught:
        measure_text(b"abc", _fonts())
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR
