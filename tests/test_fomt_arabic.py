from __future__ import annotations

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fomt import (
    CELL_HEIGHT,
    CELL_WIDTH,
    INK,
    SHADOW,
    FomtCommand,
    PlaceholderStyle,
    parse_notation,
)
from classic_retro.engines.fomt_arabic import (
    HAMZA,
    HAMZA_GAP,
    LAST_COLUMN,
    MAX_CELLS,
    NAME_CELLS,
    NAME_CODE,
    NAME_GAP,
    PREVIEW_COLOURS,
    RIGHT_MARGIN,
    TAG_CELL_WIDTH,
    TAG_CELLS,
    CellBank,
    FomtArabicEncoder,
    FomtCellRenderer,
    TagBank,
    cell_code,
    cell_data,
    cell_pixels,
    check_text,
    code_cell,
    page_preview,
    render_tag,
    text_pages,
    validate_command_skeleton,
)
from classic_retro.rom.fomt_arabic_script import fomt_arabic_names, fomt_arabic_strings

ALEF = "\u0627"
ALEF_HAMZA = "\u0623"
ALEF_HAMZA_BELOW = "\u0625"
BEH = "\u0628"
WAW_HAMZA = "\u0624"


def _box(pen: TTGlyphPen, left: int, bottom: int, right: int, top: int) -> None:
    pen.moveTo((left, bottom))
    pen.lineTo((left, top))
    pen.lineTo((right, top))
    pen.lineTo((right, bottom))
    pen.closePath()


@pytest.fixture
def arabic_font(tmp_path):
    """Original test outlines: alef, hamza carriers with a blob for the hamza, beh with forms."""
    alef = (100, 0, 300, 700)
    waw = (100, -100, 400, 400)
    shapes = {
        "alef": [alef],
        "alef_hamza": [alef, (100, 800, 300, 900)],
        "alef_hamza_below": [alef, (100, -250, 300, -150)],
        "waw": [waw],
        "waw_hamza": [waw, (200, 500, 400, 600)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap(
        {
            0x20: "space",
            0x627: "alef",
            0x623: "alef_hamza",
            0x625: "alef_hamza_below",
            0x648: "waw",
            0x624: "waw_hamza",
            0x628: "beh",
        }
    )
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        for box in shapes.get(name, []):
            _box(pen, *box)
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics.update({"space": (300, 0), "alef": (400, 100)})
    metrics.update({"alef_hamza": (400, 100), "alef_hamza_below": (400, 100)})
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=900, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro FoMT Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=900, sTypoDescender=-300, usWinAscent=900, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "fomt-test.ttf"
    builder.save(path)
    return path


def _line(cells: tuple[bytes, ...]) -> list[list[int]]:
    """The pixels of cells laid out right to left (cell 0 on the right)."""
    rows: list[list[int]] = [[] for _ in range(CELL_HEIGHT)]
    for cell in reversed(cells):
        for y, row in enumerate(cell_pixels(cell)):
            rows[y].extend(row)
    return rows


def _ink(rows: list[list[int]]) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(rows) for x, value in enumerate(row) if value == INK}


def test_check_text_rejects_what_cells_cannot_show():
    check_text("\u0645\u0631\u062d\u0628\u0627! \u061f\u060c 12")
    for text, code in (
        ("\u200f\u0628", ErrorCode.EXPLICIT_BIDI_CONTROL),
        ("\ufe8f", ErrorCode.PRE_SHAPED_ARABIC_INPUT),
        ("\u0628\u064e", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("\u0628 Jack", ErrorCode.UNENCODABLE_TEXT),
        ("\u0628\u060c\u2026", ErrorCode.UNENCODABLE_TEXT),
    ):
        with pytest.raises(ClassicRetroError) as error:
            check_text(text)
        assert error.value.code is code


def test_cells_round_trip_through_tiles():
    pixels = [[(x + y) % 3 for x in range(16)] for y in range(CELL_HEIGHT)]
    assert len(cell_data(pixels)) == 128
    assert cell_pixels(cell_data(pixels), 16) == tuple(tuple(row) for row in pixels)
    narrow = [row[:8] for row in pixels]
    assert cell_pixels(cell_data(narrow)) == tuple(tuple(row) for row in narrow)


def test_run_grows_leftwards_with_the_game_shadow(arabic_font):
    run = FomtCellRenderer(arabic_font).run(BEH + BEH + " " + ALEF)
    rows = _line(run.cells)
    width = CELL_WIDTH * len(run.cells)
    ink = _ink(rows)
    assert ink
    # The right margin keeps the shadow of the rightmost ink column in the cell.
    assert max(x for x, _ in ink) <= width - 1 - RIGHT_MARGIN
    for x, y in ink:
        for dx, dy in ((1, 0), (1, 1)):
            if x + dx < width and y + dy < CELL_HEIGHT:
                assert rows[y + dy][x + dx] in (INK, SHADOW)
    shadows = {
        (x, y) for y, row in enumerate(rows) for x, value in enumerate(row) if value == SHADOW
    }
    assert all((x - 1, y) in ink or (x - 1, y - 1) in ink for x, y in shadows)


def test_hamza_is_drawn_over_the_base_letter(arabic_font):
    renderer = FomtCellRenderer(arabic_font)
    alef = _ink(_line(renderer.run(ALEF).cells))
    carrier = _ink(_line(renderer.run(ALEF_HAMZA).cells))
    hamza = carrier - alef
    assert alef < carrier
    top = min(y for _, y in alef)
    marks = {
        (x, y) for y, pattern in enumerate(HAMZA) for x, mark in enumerate(pattern) if mark == "#"
    }
    assert len(hamza) == len(marks)
    left = min(x for x, _ in hamza)
    first = min(y for _, y in hamza)
    assert {(x - left, y - first) for x, y in hamza} == marks
    # One blank row between the hamza and the letter, over the alef's stroke.
    assert first + len(HAMZA) + HAMZA_GAP == top
    assert {x for x, _ in hamza} <= {x for x, _ in alef} | {x + 1 for x, _ in alef}


def test_hamza_below_and_on_waw(arabic_font):
    renderer = FomtCellRenderer(arabic_font)
    alef = _ink(_line(renderer.run(ALEF).cells))
    below = _ink(_line(renderer.run(ALEF_HAMZA_BELOW).cells)) - alef
    assert min(y for _, y in below) == max(y for _, y in alef) + HAMZA_GAP + 1
    waw = _ink(_line(renderer.run(WAW_HAMZA).cells))
    assert len(waw) > len(HAMZA)


def test_text_before_the_name_ends_near_the_left_edge(arabic_font):
    run = FomtCellRenderer(arabic_font).run(BEH + BEH + " ", left_gap=NAME_GAP)
    ink = _ink(_line(run.cells))
    assert min(x for x, _ in ink) == NAME_GAP


def test_encoder_keeps_commands_and_lines(arabic_font):
    encoder = FomtArabicEncoder(FomtCellRenderer(arabic_font))
    pieces = parse_notation(
        "{clear}" + BEH * 3 + "\n" + ALEF + " {name}!{wait}", PlaceholderStyle.STORY
    )
    text = encoder.encode(pieces)
    data = text.data
    assert data[0] == 0x0C and data[-1] == 0x05
    assert NAME_CODE in data
    assert data.count(b"\x0d\x0a") == 1
    # No line feed after a clear: the text continues in the empty box.
    assert data[1] == 0xF0
    assert [line.cells for line in text.lines][0] == 0
    assert text.lines[2].cells >= NAME_CELLS
    codes = [data[index : index + 2] for index in range(len(data) - 1) if data[index] == 0xF0]
    assert all(code_cell(code) < len(encoder.bank.cells) for code in codes)
    again = encoder.encode(pieces)
    assert again.data == data
    assert len(text_pages(text)) == 1


def test_encoder_rejects_overflowing_or_unread_text(arabic_font):
    encoder = FomtArabicEncoder(FomtCellRenderer(arabic_font))

    def encode(notation: str):
        return encoder.encode(parse_notation(notation, PlaceholderStyle.SCRIPT))

    encode(ALEF + "\n" + ALEF + "\n" + ALEF + "{wait}\n" + ALEF + "\n" + ALEF + "{wait}")
    for notation in (
        ALEF + "\n" + ALEF + "\n" + ALEF + "\n" + ALEF + "{wait}",
        ALEF + "{clear}" + ALEF + "{wait}",
        ALEF,
        BEH * 50 + "{wait}",
        BEH * 30 + "{name}{wait}",
    ):
        with pytest.raises(ClassicRetroError) as error:
            encode(notation)
        assert error.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError) as error:
        encoder.encode((ALEF, FomtCommand(b"\x01", "{01}")))
    assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_cell_codes_span_eleven_lead_bytes():
    assert cell_code(0) == b"\xf0\x40"
    assert cell_code(188) == b"\xf0\xfc"
    assert cell_code(189) == b"\xf1\x40"
    assert cell_code(MAX_CELLS - 1) == b"\xfa\xfc"
    for index in (0, 188, 189, 1000, MAX_CELLS - 1):
        assert code_cell(cell_code(index)) == index
    for code in (b"\xfb\x40", b"\xf0\x3f", b"\xf0\xfd"):
        with pytest.raises(ClassicRetroError):
            code_cell(code)
    bank = CellBank()
    bank.cells.extend(bytes([n % 256, n // 256]) * 32 for n in range(MAX_CELLS))
    bank._index.update({cell: number for number, cell in enumerate(bank.cells)})
    assert bank.code(bank.cells[5]) == cell_code(5)
    with pytest.raises(ClassicRetroError) as error:
        bank.code(b"\xff" * 64)
    assert error.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED


def test_name_tags_are_right_aligned_in_six_cells(arabic_font):
    renderer = FomtCellRenderer(arabic_font)
    bank = TagBank()
    codes = render_tag(renderer, ALEF + BEH, bank)
    assert len(codes) == 2 * TAG_CELLS
    assert all(codes[index] == 0xFC for index in range(0, len(codes), 2))
    blank = codes[:2]
    assert codes[2:4] == blank
    assert all(value == 0 for row in cell_pixels(bank.cells[blank[1] - 0x40], 16) for value in row)
    assert codes[-2:] != blank
    assert len(bank.cells[0]) == TAG_CELL_WIDTH * CELL_HEIGHT // 2
    with pytest.raises(ClassicRetroError) as error:
        render_tag(renderer, BEH * 40, bank)
    assert error.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_page_preview_mirrors_the_columns(arabic_font):
    encoder = FomtArabicEncoder(FomtCellRenderer(arabic_font))
    text = encoder.encode(parse_notation(ALEF + "{wait}", PlaceholderStyle.SCRIPT))
    image = page_preview(text.lines)
    column = 8 + LAST_COLUMN * CELL_WIDTH
    inked = [
        x
        for x in range(image.width)
        for y in range(4, 4 + CELL_HEIGHT)
        if image.getpixel((x, y)) == PREVIEW_COLOURS[INK]
    ]
    assert inked and min(inked) >= column and max(inked) < column + CELL_WIDTH


def test_skeleton_validation():
    pieces = parse_notation("A{wait}{clear}B{wait}", PlaceholderStyle.SCRIPT)
    validate_command_skeleton(("{wait}", "{clear}", "{wait}"), pieces)
    with pytest.raises(ClassicRetroError) as error:
        validate_command_skeleton(("{wait}",), pieces)
    assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_the_opening_translation_keeps_every_original_command():
    strings = fomt_arabic_strings()
    assert len({string.key for string in strings}) == len(strings) == 33
    indices = sorted(string.index for string in strings if string.index is not None)
    assert indices == list(range(10))
    story = [string for string in strings if string.index is None]
    assert len({string.address for string in story}) == len(story) == 23
    for string in strings:
        pieces = string.pieces
        validate_command_skeleton(string.source_skeleton, pieces)
        for piece in pieces:
            if isinstance(piece, str):
                check_text(piece)
    names = fomt_arabic_names()
    assert [name.key for name in names] == ["mother", "father", "old_man", "voice", "girl"]
    for name in names:
        check_text(name.arabic)
    literals = [literal for string in story for literal in string.literals]
    literals += [literal for name in names for literal in name.literals]
    assert len(set(literals)) == len(literals)
