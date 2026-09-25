from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.metroid_fusion import (
    ARROW,
    DEFAULT_WIDTH,
    DIALECTS,
    END,
    FONT_CODES,
    FONT_GRAPHICS,
    FONT_WIDTHS,
    INTRO,
    LATIN_CODES,
    NAVIGATION,
    NEW_PAGE,
    NEWLINE,
    QUESTION,
    QUESTION_PROMPT,
    ROM_BASE,
    TILE_ROW_BYTES,
    MfCommand,
    MfFont,
    command_skeleton,
    encode_text,
    is_command,
    lay_out,
    line_widths,
    notation_skeleton,
    pack_units,
    parse_notation,
    pieces_units,
    read_text,
    split_text,
    text_notation,
    text_units,
)

# Invented texts in the engine's notation.
SAMPLES = (
    "Line one\nand line two.{FC00}{FD00}A new page!{FC00}",
    "{E132}After a wait, two arrows.{FC00}{FC00}{FD00}Done.{FC00}",
    "Odd glyphs {char 0305}{char 9000} stay glyphs.",
    "Punctuation: 1, 2 & 3? (yes) 'quoted' -dash_",
)


@pytest.mark.parametrize("text", SAMPLES)
def test_notation_round_trips_through_units(text):
    units = pieces_units(parse_notation(text))
    assert text_notation(units) == text
    data = pack_units((*units, END)) + b"junk"
    assert text_units(data, 0) == units


def test_latin_codes_are_ascii_shifted():
    assert encode_text("Aa ?") == (0x81, 0xC1, 0x40, 0x5F)
    assert LATIN_CODES[0x89] == "I" and LATIN_CODES[0xDA] == "z" and LATIN_CODES[0x40] == " "
    # Braces are the notation's: those codes go through {char XXXX}.
    assert "{" not in LATIN_CODES.values() and "}" not in LATIN_CODES.values()
    assert encode_text("{char 00DB}") == (0xDB,)


def test_control_units_split_the_text():
    units = pieces_units(parse_notation("ab\ncd{FC00}{FD00}{E10A}e"))
    assert units == (0xC1, 0xC2, NEWLINE, 0xC3, 0xC4, ARROW, NEW_PAGE, 0xE10A, 0xC5)
    pieces = split_text(units)
    assert pieces == (
        "ab",
        MfCommand(NEWLINE),
        "cd",
        MfCommand(ARROW),
        MfCommand(NEW_PAGE),
        MfCommand(0xE10A),
        "e",
    )
    assert pieces[1].is_newline and pieces[1].notation == "\n"
    assert pieces[5].notation == "{E10A}"


def test_line_ends_after_text_are_not_part_of_the_skeleton():
    assert notation_skeleton(parse_notation("a\nb{FC00}{FD00}c{FC00}")) == (
        "{FC00}",
        "{FD00}",
        "{FC00}",
    )
    # A line end that follows a control unit stays.
    assert command_skeleton(pieces_units(parse_notation("a{FD00}\nb"))) == ("{FD00}", "\n")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{FE00}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{FF00}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{E0 12}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{FC00", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("a}", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_bad_notation_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as caught:
        pieces_units(parse_notation(text))
    assert caught.value.code is code


def test_text_outside_the_font_and_control_units_as_glyphs_are_refused():
    with pytest.raises(ClassicRetroError) as caught:
        encode_text("café")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
    for unit in ("FE00", "FF00", "E105"):
        with pytest.raises(ClassicRetroError) as caught:
            encode_text(f"{{char {unit}}}")
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_a_text_needs_its_end_and_an_even_address():
    with pytest.raises(ClassicRetroError) as caught:
        text_units(pack_units((0xC1, 0xC2)), 0)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    rom = bytes(16) + pack_units((0xC1, END))
    assert read_text(rom, ROM_BASE + 16) == (0xC1,)
    with pytest.raises(ClassicRetroError) as caught:
        read_text(rom, ROM_BASE + 17)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def _font_image() -> bytes:
    """An image with the font's tables: code 0x81 is 8 pixels, two tiles tall."""
    size = FONT_GRAPHICS - ROM_BASE + 32 * FONT_CODES + TILE_ROW_BYTES + 64
    rom = bytearray(size)
    widths = FONT_WIDTHS - ROM_BASE
    rom[widths : widths + FONT_CODES] = bytes(range(256)) * 4 + bytes(FONT_CODES - 1024)
    top = FONT_GRAPHICS - ROM_BASE + 32 * 0x81
    # Row 1 of the top tile: pixel 0 ink (2), pixel 7 outline (3).
    struct.pack_into("<I", rom, top + 4, 2 | 3 << 28)
    # Row 0 of the bottom tile, and of the next code's top tile (pixels 8-15).
    struct.pack_into("<I", rom, top + TILE_ROW_BYTES, 3)
    struct.pack_into("<I", rom, top + 32, 2 << 4)
    return bytes(rom)


def test_font_reads_widths_and_both_tile_columns():
    font = MfFont.read(_font_image())
    assert font.width(0x81) == 0x81 and font.width(0x40) == 0x40
    assert font.width(FONT_CODES) == DEFAULT_WIDTH == 10
    glyph = font.glyph(0x81)
    assert len(glyph) == 16 and all(len(row) == 16 for row in glyph)
    assert glyph[1][0] == 2 and glyph[1][7] == 3
    assert glyph[8][0] == 3
    assert glyph[0][9] == 2


def test_font_outside_the_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        MfFont.read(bytes(1024))
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_lines_add_up_glyph_widths():
    font = MfFont(tuple([8] * 0x40 + [6] + [7] * (FONT_CODES - 0x41)), b"")
    units = pieces_units(parse_notation("ab c\nd{FC00}{FD00}ef{E120}"))
    assert line_widths(units, font) == (7 + 7 + 6 + 7, 7, 14)


# ---------------------------------------------------------------------------
# The briefings and their question

BRIEFING_SAMPLE = (
    "{B003}Go to the {8102}Old Dock{8100}.{FD00}Stay low\nand {E000}wait.{FC00}"
    "{E105}Then {8103}run{8100}.{FB00}Done."
)
QUESTION_SAMPLE = "{8017}Ready{char 041F}\n{8057}{8340}Yes {83A0}No"


@pytest.mark.parametrize(
    ("unit", "commands"),
    [
        (NEWLINE, {INTRO, NAVIGATION, QUESTION}),
        (ARROW, {INTRO, NAVIGATION}),
        (QUESTION_PROMPT, {NAVIGATION}),
        (0xE105, {INTRO, NAVIGATION}),
        (0xE000, {NAVIGATION}),
        (0x8102, {NAVIGATION}),
        (0x8017, {NAVIGATION, QUESTION}),
        (0x83A0, {NAVIGATION, QUESTION}),
        (0x9123, {NAVIGATION}),
        (0xB003, {NAVIGATION}),
        # Glyphs everywhere: a briefing draws Bxxx past its events, Dxxx and odd Fxxx.
        (0xB040, set()),
        (0xD120, set()),
        (0xFA00, set()),
        (0x0081, set()),
    ],
)
def test_each_routine_reads_its_own_commands(unit, commands):
    assert {dialect for dialect in DIALECTS if is_command(unit, dialect)} == commands


def test_an_unknown_dialect_is_refused():
    with pytest.raises(ValueError):
        is_command(NEWLINE, "menu")


@pytest.mark.parametrize(
    ("text", "dialect"), [(BRIEFING_SAMPLE, NAVIGATION), (QUESTION_SAMPLE, QUESTION)]
)
def test_briefing_and_question_notation_round_trips(text, dialect):
    units = pieces_units(parse_notation(text, dialect), dialect)
    assert text_notation(units, dialect) == text
    # The intro reads their commands as glyphs, and has no notation for them.
    with pytest.raises(ClassicRetroError) as caught:
        parse_notation(text)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_skeletons_leave_out_moving_line_ends_and_pen_amounts():
    # A line end after a colour still follows text; a pen advance keeps its place.
    assert notation_skeleton(parse_notation("a{8102}b{8100}\nc{FD00}\nd", NAVIGATION)) == (
        "{8102}",
        "{8100}",
        "{FD00}",
        "\n",
    )
    assert command_skeleton(pieces_units(parse_notation(QUESTION_SAMPLE, QUESTION), QUESTION),
                            QUESTION) == ("{80xx}", "{80xx}", "{8340}", "{83A0}")  # fmt: skip


def test_a_briefing_lays_out_its_boxes():
    units = pieces_units(parse_notation(BRIEFING_SAMPLE, NAVIGATION), NAVIGATION)
    lines = lay_out(units, lambda unit: 6 if unit == 0x40 else 8, NAVIGATION)
    shape = [(line.page, line.number, line.start, line.waits) for line in lines]
    assert shape == [
        (0, 0, 0, True),
        (1, 0, 0, False),
        (1, 1, NEWLINE, True),
        (1, 2, ARROW, True),
        (2, 0, 0, False),
    ]
    # "Go to the " is white, the name in colour 2; the line ends after its full stop.
    first = lines[0].places
    assert [place.colour for place in first] == [0] * 10 + [2] * 8 + [0]
    assert lines[0].width == 7 * 8 + 3 * 6 + 7 * 8 + 6 + 8
    assert {place.colour for place in lines[3].places} == {0, 3}


def test_the_question_places_its_options():
    units = pieces_units(parse_notation(QUESTION_SAMPLE, QUESTION), QUESTION)
    first, second = lay_out(units, lambda unit: 8, QUESTION)
    assert first.places[0].pen == 0x17 and second.start == NEWLINE
    pens = [place.pen for place in second.places]
    # Yes at 0x40; No at 0xA0 less the question's 16 pixels.
    assert pens == [0x40, 0x48, 0x50, 0x58, 0x90, 0x98]
    # A briefing puts 83A0 at 0xA0 itself.
    (line,) = lay_out((0x83A0, 0xC1), lambda unit: 8, NAVIGATION)
    assert line.places[0].pen == 0xA0
