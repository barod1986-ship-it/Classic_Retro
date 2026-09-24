from __future__ import annotations

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mmbn import (
    BACKGROUND,
    CELL_WIDTH,
    CLEAR,
    INK,
    NEWLINE,
    PAGE_CELLS,
    SYMBOL_LEAD,
    cell_pixels,
    parse_notation,
)
from classic_retro.engines.mmbn_arabic import (
    BOX_COLUMNS,
    LATIN_CHARACTERS,
    PREVIEW_COLOURS,
    MmbnArabicEncoder,
    MmbnLineRenderer,
    check_text,
    page_preview,
    pages_sheet,
    placeholder_latin_cells,
    split_runs,
    validate_command_skeleton,
)
from classic_retro.rom.mmbn_arabic_script import mmbn_arabic_sections, mmbn_script_archives


def _box(pen: TTGlyphPen, left: int, bottom: int, right: int, top: int) -> None:
    pen.moveTo((left, bottom))
    pen.lineTo((left, top))
    pen.lineTo((right, top))
    pen.lineTo((right, bottom))
    pen.closePath()


@pytest.fixture
def arabic_font(tmp_path):
    """Original test outlines: alef, beh with OpenType forms, no Latin punctuation."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x627: "alef", 0x628: "beh"})
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        for box in shapes.get(name, []):
            _box(pen, *box)
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics["alef"] = (329, 100)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro MMBN Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "mmbn-test.ttf"
    builder.save(path)
    return path


def _ink_columns(cells: tuple[bytes, ...]) -> list[int]:
    """Ink columns of a line, counted from its right edge (cell 0 is rightmost)."""
    columns = set()
    for number, cell in enumerate(cells):
        for row in cell_pixels(cell):
            for x, value in enumerate(row):
                if value != BACKGROUND:
                    columns.add(CELL_WIDTH * (number + 1) - 1 - x)
    return sorted(columns)


def test_runs_split_arabic_from_latin_words():
    assert split_runs("اب PET!") == (("اب ", False), ("PET", True), ("!", False))
    assert split_runs("MegaMan.EXE!") == (("MegaMan.EXE", True), ("!", False))
    assert split_runs("ب Recov10 A") == (("ب ", False), ("Recov10 A", True))


def test_line_grows_leftwards_from_the_right_edge(arabic_font):
    line = MmbnLineRenderer(arabic_font).render(["ببب ا"])

    assert 1 <= len(line.cells) <= 4
    columns = _ink_columns(line.cells)
    # One blank column on the right, then ink; nothing past the line's cells.
    assert columns[0] == 1
    assert columns[-1] < CELL_WIDTH * len(line.cells)
    assert line.width == columns[-1] + 1


def test_latin_words_keep_the_game_cells(arabic_font):
    latin = placeholder_latin_cells()
    renderer = MmbnLineRenderer(arabic_font, latin)
    alone = renderer.render(["ب"])
    mixed = renderer.render(["ب PET"])

    # Three 8-pixel game cells to the left of the Arabic word.
    assert mixed.width - alone.width >= 3 * CELL_WIDTH
    with pytest.raises(ClassicRetroError) as caught:
        MmbnLineRenderer(arabic_font, {"A": latin["A"]})
    assert caught.value.code is ErrorCode.MISSING_GLYPH


def test_latin_words_sit_on_the_baseline_and_digits_stay_in_the_cell(arabic_font):
    letter = tuple(
        tuple(INK if 3 <= y <= 13 and 1 <= x <= 6 else BACKGROUND for x in range(8))
        for y in range(16)
    )
    digit = tuple(
        tuple(INK if 2 <= y <= 13 and 1 <= x <= 6 else BACKGROUND for x in range(8))
        for y in range(16)
    )
    latin = {character: letter for character in LATIN_CHARACTERS} | {"1": digit}
    renderer = MmbnLineRenderer(arabic_font, latin)

    def rows(text: str) -> list[int]:
        cells = renderer.render([text]).cells
        return sorted(
            {y for cell in cells for y, row in enumerate(cell_pixels(cell)) if INK in row}
        )

    assert rows("AB")[0] == 0 and rows("AB")[-1] == 10
    # A word with a digit moves up one row less.
    assert rows("A1")[0] == 0 and rows("A1")[-1] == 11


def test_text_after_a_wait_starts_in_a_new_cell(arabic_font):
    renderer = MmbnLineRenderer(arabic_font)
    (wait,) = parse_notation("{d 30}")
    (mouth,) = parse_notation(">")
    waited = renderer.render([".", wait, ".", wait, "."])
    # Every dot has a cell of its own, and each wait sits between them.
    assert len(waited.cells) == 3 and waited.boundaries == (1, 2)
    first = renderer.render(["ب"])
    soft = renderer.render(["ب", mouth, "ب"])
    hard = renderer.render(["ب", wait, "ب"])
    # Both commands go where the first word ends; only the wait moves the
    # second word into cells of its own.
    assert soft.boundaries == hard.boundaries == (len(first.cells),)
    assert hard.cells[: len(first.cells)] == first.cells
    assert soft.width <= hard.width


def test_encoder_keeps_commands_and_pages(arabic_font):
    encoder = MmbnArabicEncoder(MmbnLineRenderer(arabic_font))
    notation = "{pic 0 0}{dialog_up}<بب\nاب>\\p{cls 0}<ب.>{d 30}\n<ا!>\\p{end 5}"
    script = encoder.encode(parse_notation(notation))

    first, second = script.pages
    assert first.start == 0 and second.start == script.data.index(CLEAR) + 3
    assert len(first.line_cells) == 2 and len(second.line_cells) == 2
    data = script.data
    assert data.startswith(bytes.fromhex("ed000000f200ee02"))
    assert data.count(NEWLINE) == 2 and data.endswith(bytes.fromhex("ee01ebe70500"))
    # Every character byte is a cell of its page's bank.
    codes = [byte for byte in data[len(bytes.fromhex("ed000000f200ee02")) :] if byte < 0x30]
    assert codes and max(codes) < SYMBOL_LEAD
    assert len(first.cells) == len(set(first.cells))


def test_encoder_rejects_what_it_cannot_draw(arabic_font):
    encoder = MmbnArabicEncoder(MmbnLineRenderer(arabic_font))
    cases = {
        "{dialog_up}" + "ب" * 60 + "\\p{end 0}": ErrorCode.TEXT_BOX_OVERFLOW,
        "{dialog_up}ب\nب\nب\nب\\p{end 0}": ErrorCode.TEXT_BOX_OVERFLOW,
        "{dialog_up}ب{key 0}\\p{end 0}": ErrorCode.UNSUPPORTED_CONTROL_CODE,
        "{dialog_up}ب{char 93}\\p{end 0}": ErrorCode.UNENCODABLE_TEXT,
        "{dialog_up}ﺏ\\p{end 0}": ErrorCode.PRE_SHAPED_ARABIC_INPUT,
        "{dialog_up}بَ\\p{end 0}": ErrorCode.UNSUPPORTED_ARABIC_MARK,
        "{dialog_up}ب١\\p{end 0}": ErrorCode.UNENCODABLE_TEXT,
    }
    for notation, code in cases.items():
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode(parse_notation(notation))
        assert caught.value.code is code, notation
    with pytest.raises(ClassicRetroError) as caught:
        check_text("ب\u200fب")
    assert caught.value.code is ErrorCode.EXPLICIT_BIDI_CONTROL


def test_a_full_page_fits_the_tile_buffer(arabic_font):
    renderer = MmbnLineRenderer(arabic_font)
    encoder = MmbnArabicEncoder(renderer)
    width = renderer.render(["ب" * 20]).cells
    assert len(width) <= BOX_COLUMNS
    script = encoder.encode(parse_notation("{dialog_up}" + "\n".join(["بب"] * 3) + "\\p{end 0}"))
    assert sum(script.pages[0].line_cells) <= PAGE_CELLS


def test_skeleton_must_match_the_original():
    validate_command_skeleton(("{dialog_up}", "<", ">", "\\p"), parse_notation("{dialog_up}<ب>\\p"))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(("{dialog_up}", "\\p"), parse_notation("{dialog_up}<ب>\\p"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_every_translation_keeps_its_original_commands():
    sections = mmbn_arabic_sections()
    archives = {archive.key: archive for archive in mmbn_script_archives()}

    assert len(sections) == len({section.key for section in sections})
    for section in sections:
        validate_command_skeleton(section.source_skeleton, section.pieces)
        assert 0 <= section.index < archives[section.archive].sections
        assert len(section.source_sha256) == 64


def test_page_preview_mirrors_the_columns(arabic_font):
    script = MmbnArabicEncoder(MmbnLineRenderer(arabic_font)).encode(
        parse_notation("{dialog_up}بب\\p{end 0}")
    )
    image = page_preview(script.pages[0])
    sheet = pages_sheet([("test/0", script.pages[0])])

    ink = [
        x
        for x in range(image.width)
        for y in range(image.height)
        if image.getpixel((x, y)) == PREVIEW_COLOURS[INK]
    ]
    # Cell 0 of the line is drawn in column 27, the rightmost of the box.
    assert 27 * CELL_WIDTH <= max(ink) < 28 * CELL_WIDTH
    assert min(ink) >= 8 * CELL_WIDTH
    assert sheet.width > image.width
