from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.gran_turismo import Briefing
from classic_retro.engines.gran_turismo_arabic import (
    ARABIC_CODES,
    BODY,
    BOX_LEFT,
    BOX_WIDTH,
    CELLS,
    CLEAR,
    DROP,
    INDENT,
    INK,
    LINE_STEP,
    MAX_LINES,
    MIRROR,
    OUTLINE,
    PAGE_ROWS,
    PAGE_WIDTH,
    PREVIEW_BACKGROUND,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    ROW_BYTES,
    SPACE,
    TITLE,
    TITLE_SPACE,
    TITLE_STEP,
    TOP,
    WIDEST_WORD,
    EncodedBriefing,
    GranTurismoArabicEncoder,
    GtFont,
    GtGlyph,
    briefing_characters,
    briefing_preview,
    build_gran_turismo_fonts,
    draw_glyph,
    font_preview,
    glyph_characters,
    gran_turismo_glyph_codes,
    lay_out_paragraphs,
    lay_out_title,
    outlined_glyph,
    place_glyphs,
    visual_text,
)
from classic_retro.font.glyph_raster import DrawnForm, FormDoesNotFit, raised_marks, separated_dots

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
WAW = unicodedata.lookup("ARABIC LETTER WAW ISOLATED FORM")


def _map(*texts: str) -> GlyphCodes:
    characters: set[str] = set()
    for text in texts:
        characters |= set(visual_text(text))
    return gran_turismo_glyph_codes(characters | {" "})


def _bar(width: int) -> GtGlyph:
    return GtGlyph(width, 2, ((INK,) * width,) * 3)


def _fonts(glyph_map: GlyphCodes, width: int = 10) -> dict[int, GtFont]:
    """Every glyph a bar ``width`` pixels wide; the title's space is the real one."""
    glyphs = {
        code: GtGlyph(TITLE_SPACE, 0, ()) if character == " " else _bar(width)
        for character, (code,) in glyph_map.sequences.items()
    }
    return {BODY: GtFont(BODY, glyphs, 10), TITLE: GtFont(TITLE, glyphs, 18)}


def test_the_arabic_codes_are_the_latin_1_half_but_the_no_break_space():
    assert len(ARABIC_CODES) == 121
    assert ARABIC_CODES[0] == 0x86 and ARABIC_CODES[-1] == 0xFF and 0xA0 not in ARABIC_CODES
    order = glyph_characters()
    assert order[:8] == (" ", ".", ",", ":", "!", "-", "،", "؛")
    assert order[8:18] == tuple("0123456789")
    assert len(order) == len(set(order))
    glyph_map = gran_turismo_glyph_codes({BEH["MEDIAL"], "3", "."})
    assert glyph_map.characters == (".", "3", BEH["MEDIAL"])
    assert glyph_map.all_codes() == (0x86, 0x87, 0x88)


@pytest.mark.parametrize("character", ["A", "ڤ"])
def test_characters_without_a_glyph_are_refused(character):
    with pytest.raises(ClassicRetroError) as caught:
        gran_turismo_glyph_codes({character})
    assert caught.value.code in (ErrorCode.UNENCODABLE_TEXT, ErrorCode.MISSING_GLYPH)


def test_a_word_is_stored_left_to_right_as_drawn():
    assert visual_text("بب") == BEH["FINAL"] + BEH["INITIAL"]
    # A number keeps its order, left of a letter it follows.
    assert visual_text("و22") == "22" + WAW
    assert visual_text("1,000") == "1,000"
    # The title is one word, spaces and all.
    assert visual_text("ب 1") == "1 " + BEH["ISOLATED"]


def test_the_encoder_keeps_the_words_in_reading_order():
    glyph_map = _map("بب ب 36", "ب.")
    encoded = GranTurismoArabicEncoder(glyph_map).encode("بب ب", (("بب", "ب."), ("36",)))
    code = glyph_map.code
    assert encoded.lines is None and encoded.title is None
    assert encoded.briefing == Briefing(
        bytes((code(BEH["ISOLATED"]), code(" "), code(BEH["FINAL"]), code(BEH["INITIAL"]))),
        (
            (bytes((code(BEH["FINAL"]), code(BEH["INITIAL"]))),
             bytes((code("."), code(BEH["ISOLATED"])))),
            (bytes((code("3"), code("6"))),),
        ),
    )  # fmt: skip
    # Every glyph is one of the Arabic font's: none is the game's own.
    assert all(byte in ARABIC_CODES for byte in encoded.briefing.title)


@pytest.mark.parametrize(
    ("paragraph", "code"),
    [
        (("1", "000"), ErrorCode.UNENCODABLE_TEXT),  # would be drawn "000 1"
        (("(ب)",), ErrorCode.UNENCODABLE_TEXT),
        (("بَ",), ErrorCode.UNSUPPORTED_ARABIC_MARK),
    ],
)
def test_text_the_game_cannot_draw_as_written_is_refused(paragraph, code):
    glyph_map = _map("ب", "1")
    with pytest.raises(ClassicRetroError) as caught:
        GranTurismoArabicEncoder(glyph_map).encode("ب", (paragraph,))
    assert caught.value.code is code


def test_paragraphs_are_laid_out_as_the_game_does_then_mirrored():
    word = b"\x86" * 4  # 40 pixels
    font = _fonts(gran_turismo_glyph_codes({BEH["MEDIAL"]}))[BODY]
    # 8 + 6 * 40 + 5 * 4 = 268 fits a line; a seventh word does not.
    lines = lay_out_paragraphs(((word,) * 7, (word,)), font)
    assert [len(line.words) for line in lines] == [6, 1, 1]
    assert [line.y for line in lines] == [TOP + TITLE_STEP + LINE_STEP * n for n in range(3)]
    first = lines[0]
    # The game spreads the room left (288 - 268) over the five gaps: 4 each.
    lefts = [INDENT + BOX_LEFT + n * (40 + 4 + 4) for n in range(6)]
    assert [placed.x for placed in first.words] == [MIRROR - x - 40 for x in lefts]
    # A paragraph's last line is not spread, and starts at the right edge.
    assert lines[1].words[0].x == MIRROR - BOX_LEFT - 40
    assert lines[2].words[0].x == MIRROR - BOX_LEFT - INDENT - 40


def test_the_box_takes_seven_lines_and_a_word_as_wide_as_a_first_line():
    font = _fonts(gran_turismo_glyph_codes({BEH["MEDIAL"]}))[BODY]
    assert MAX_LINES == 7 and WIDEST_WORD == BOX_WIDTH - INDENT
    # The seventh line's glyphs end on the box's last row.
    body = CELLS[BODY]
    assert TOP + TITLE_STEP + LINE_STEP * 6 + DROP + body.dy - 4 + body.rows - 1 == 195
    wide = b"\x86" * 28  # 280 pixels
    assert len(lay_out_paragraphs(((wide,),) * 7, font)) == 7
    with pytest.raises(ClassicRetroError) as caught:
        lay_out_paragraphs(((wide,),) * 8, font)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError) as caught:
        lay_out_paragraphs(((wide + b"\x86",),), font)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_the_title_is_centred_and_fits_the_box():
    font = _fonts(gran_turismo_glyph_codes({BEH["MEDIAL"]}))[TITLE]
    title = lay_out_title(b"\x86" * 5, font)
    assert (title.x, title.width) == ((BOX_WIDTH - 50) // 2 + BOX_LEFT, 50)
    with pytest.raises(ClassicRetroError) as caught:
        lay_out_title(b"\x86" * 29, font)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_the_encoder_measures_with_the_fonts():
    glyph_map = _map("بب ب", "ب.")
    encoded = GranTurismoArabicEncoder(glyph_map, _fonts(glyph_map)).encode("بب ب", (("بب", "ب."),))
    assert encoded.title is not None and encoded.title.width == 3 * 10 + TITLE_SPACE
    assert encoded.lines is not None and len(encoded.lines) == 1
    assert [word.width for word in encoded.lines[0].words] == [20, 20]


def test_a_glyph_is_outlined_but_where_it_joins_and_cropped_to_its_rows():
    cell = CELLS[BODY]
    ink = {(0, 9), (1, 9), (2, 9), (1, 8)}
    alone = outlined_glyph(ink, cell, joins_left=False, joins_right=False)
    assert (alone.width, alone.top, alone.height) == (5, 7, 4)
    assert alone.rows[0] == (CLEAR, OUTLINE, OUTLINE, OUTLINE, CLEAR)
    assert alone.rows[2] == (OUTLINE, INK, INK, INK, OUTLINE)
    joined = outlined_glyph(ink, cell, joins_left=True, joins_right=True)
    assert joined.width == 3 and joined.rows[2] == (INK, INK, INK)
    # The table's entry: page place, size, the row it starts on, the advance less one.
    assert alone.entry(40, 200, cell.dy) == bytes((40, 200, 5, 4, 0, 7, 4, 4))
    for bad in ({(0, 0)}, {(0, cell.rows - 1)}, {(cell.widest, 5)}):
        with pytest.raises(FormDoesNotFit):
            outlined_glyph(bad, cell, joins_left=False, joins_right=False)


def test_glyphs_go_to_the_first_tier_with_room_then_the_next():
    full = (1 << PAGE_WIDTH) - 1
    preferred = [full] * PAGE_ROWS
    for y in range(10, 20):
        preferred[y] = full & ~(0xFF << 16)  # 8 pixels from column 16
    kept = [0] * PAGE_ROWS
    places = place_glyphs((preferred, kept), [(8, 10), (4, 0), (6, 6), (3, 4)])
    assert places[0] == (16, 10)  # the preferred room
    assert places[1] == (0, 0)  # a blank glyph takes none
    assert places[2] == (0, 0)  # then anywhere the game leaves free
    assert places[3] == (6, 0)
    with pytest.raises(ClassicRetroError) as caught:
        place_glyphs(([full] * PAGE_ROWS,), [(1, 1)])
    assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED


def test_a_glyph_changes_only_the_low_two_bits_of_its_pixels():
    page = bytearray([0xDD] * (PAGE_ROWS * ROW_BYTES))  # every pixel 0b1101
    draw_glyph(page, 3, 1, GtGlyph(2, 0, ((INK, OUTLINE),)))
    at = ROW_BYTES + 1
    assert page[at] == 0xCD  # pixel 3, high nibble: 0b1100 (ink)
    assert page[at + 1] == 0xDE  # pixel 4, low nibble: 0b1110 (outline)
    assert page[at + 2] == 0xDD


def _form(ink: set[tuple[int, int]]) -> DrawnForm:
    return DrawnForm(frozenset(ink), frozenset(), max(x for x, _ in ink) + 1)


def test_merged_dots_of_small_letters_are_drawn_apart():
    teh = unicodedata.lookup("ARABIC LETTER TEH MEDIAL FORM")
    body = {(2, y) for y in range(6, 10)} | {(x, 10) for x in range(4)}
    merged = _form(body | {(1, 4), (2, 4)})
    fixed = separated_dots(teh, merged)
    assert fixed.ink - body == {(1, 4), (3, 4)}
    # The same shape as beh (one dot) or with dots already apart stays.
    beh = unicodedata.lookup("ARABIC LETTER BEH MEDIAL FORM")
    assert separated_dots(beh, merged) is merged
    apart = _form(body | {(1, 4), (3, 4)})
    assert separated_dots(teh, apart) is apart
    # Three dots in a triangle; yeh's two below, a free row from the letter.
    sheen = unicodedata.lookup("ARABIC LETTER SHEEN MEDIAL FORM")
    assert separated_dots(sheen, merged).ink - body == {(1, 4), (3, 4), (2, 3)}
    yeh = unicodedata.lookup("ARABIC LETTER YEH MEDIAL FORM")
    lost = _form(body | {(2, 12)})
    assert separated_dots(yeh, lost).ink - body == {(1, 12), (3, 12)}


def test_marks_below_a_letter_move_up_into_the_cell():
    body = {(x, 22) for x in range(6)} | {(0, y) for y in range(10, 22)}
    dots = {(1, 25), (2, 25), (1, 26), (2, 26), (4, 25), (4, 26)}
    form = _form(body | dots)
    raised = raised_marks(form, 24)
    # Two rows up; their first row would touch the letter, so they keep a free row.
    assert raised.ink - body == {(1, 24), (2, 24), (4, 24)}
    assert raised_marks(form, 26) is form
    assert raised_marks(form, 25).ink - body == {
        (1, 24),
        (2, 24),
        (4, 24),
        (1, 25),
        (2, 25),
        (4, 25),
    }


@pytest.fixture(scope="module")
def beh_font(tmp_path_factory):
    """Original test outlines: beh's four forms (a box each, the medial widest) and a digit."""
    names = [".notdef", "space", "beh", "beh.init", "beh.medi", "beh.fina", "one"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x628: "beh", 0x31: "one"})
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
    path = tmp_path_factory.mktemp("font") / "beh.ttf"
    builder.save(path)
    return path


def test_the_fonts_are_drawn_at_the_largest_size_their_cells_hold(beh_font):
    body = {BEH["INITIAL"], BEH["FINAL"], ".", "1"}
    title = {BEH["INITIAL"], BEH["FINAL"], " "}
    glyph_map = gran_turismo_glyph_codes(body | title)
    fonts = build_gran_turismo_fonts(
        beh_font, glyph_map, body=body, title=title, sizing=set(BEH.values()) | {"1"}
    )
    assert fonts[BODY].font_size in CELLS[BODY].sizes
    assert fonts[TITLE].font_size in CELLS[TITLE].sizes
    assert fonts[TITLE].font_size > fonts[BODY].font_size
    code = glyph_map.code
    assert set(fonts[BODY].glyphs) == {code(character) for character in body}
    assert set(fonts[TITLE].glyphs) == {code(character) for character in title}
    initial = fonts[BODY].glyphs[code(BEH["INITIAL"])]
    final = fonts[BODY].glyphs[code(BEH["FINAL"])]
    # The initial joins on its left: its first column has ink; the final on its right.
    assert any(row[0] == INK for row in initial.rows)
    assert all(row[0] != INK for row in final.rows)
    assert any(row[-1] == INK for row in final.rows)
    assert fonts[TITLE].glyphs[code(" ")] == GtGlyph(TITLE_SPACE, 0, ())
    # The hand-drawn full stop, outlined all round.
    stop = fonts[BODY].glyphs[code(".")]
    assert stop.width == 4 and stop.rows[1] == (OUTLINE, INK, INK, OUTLINE)


def test_previews_show_the_glyphs_and_the_box():
    glyph_map = _map("بب ب", "ب.")
    fonts = _fonts(glyph_map)
    encoded = GranTurismoArabicEncoder(glyph_map, fonts).encode("بب ب", (("بب", "ب."),))
    image = briefing_preview(encoded, fonts)
    assert image.size == (MIRROR, 195 + 1 - TOP + 2 * PREVIEW_MARGIN)
    line = encoded.lines[0] if encoded.lines else None
    assert line is not None
    word = line.words[0]
    row = line.y + DROP + CELLS[BODY].dy - 4 + 2 - (TOP - PREVIEW_MARGIN)
    assert image.getpixel((word.x, row)) == PREVIEW_COLOURS[INK]
    assert image.getpixel((word.x - 2, row)) == PREVIEW_BACKGROUND
    atlas = font_preview(fonts)
    assert atlas.width > 0 and atlas.height > 0
    with pytest.raises(ClassicRetroError):
        briefing_preview(EncodedBriefing(encoded.briefing, None, None), fonts)


def test_briefing_characters_split_the_title_from_the_body():
    title, body = briefing_characters("ب 1", (("بب",),))
    assert title == {BEH["ISOLATED"], " ", "1"}
    assert body == {BEH["INITIAL"], BEH["FINAL"]}
    assert SPACE == 4
