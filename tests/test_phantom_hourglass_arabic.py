from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.adapters.registry import build_registry
from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.phantom_hourglass import (
    BOX_WIDTH,
    CELL_HEIGHT,
    CELL_WIDTH,
    LETTER_SPACING,
    PEN_START,
    escape_code,
    escape_colour,
    pages,
)
from classic_retro.engines.phantom_hourglass_arabic import (
    ARABIC_CODES,
    BASELINE,
    INK,
    LINE_HEIGHT,
    LINE_WIDTH,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    RTL_FIRST,
    RTL_LAST,
    SOFT,
    SPACE_WIDTH,
    SPLIT_FORMS,
    PhArabicEncoder,
    PhArabicFont,
    build_ph_arabic_font,
    font_preview,
    glyph_characters,
    message_preview,
    messages_sheet,
    painted_characters,
    ph_glyph,
    ph_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit
from classic_retro.text.bmg import BmgEscape, parse_notation

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
ALEF = unicodedata.lookup("ARABIC LETTER ALEF ISOLATED FORM")
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")
PAUSE = BmgEscape(0x01, bytes.fromhex("0A001400"))
BLUE = BmgEscape(0xFF, bytes.fromhex("00000300"))
WHITE = BmgEscape(0xFF, bytes.fromhex("00000000"))


def _map(text: str = "بب ب. ا س! بببب:") -> GlyphCodes:
    return ph_glyph_codes(painted_characters(parse_notation(text)))


def _fake_font(glyph_map: GlyphCodes, width: int = 5) -> PhArabicFont:
    """Every glyph a bar ``width`` pixels wide, meeting the next; the space is the real one."""
    bar = ph_glyph({(x, y) for x in range(width) for y in range(4, BASELINE)}, width)
    glyphs = {}
    for character, codes in glyph_map.sequences.items():
        for code in codes:
            glyphs[code] = ph_glyph((), SPACE_WIDTH) if character == " " else bar
    return PhArabicFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def _code(glyph_map: GlyphCodes, character: str) -> str:
    return "".join(map(chr, glyph_map.sequence(character) or ()))


def test_the_engine_is_registered_for_the_game():
    registry = build_registry()
    game = registry.games["zelda-phantom-hourglass-usa"]
    assert game.engine_id == "nds.zelda-ph" and game.platform_id == "nds"
    assert registry.engines["nds.zelda-ph"].platform_ids == ("nds",)


def test_escape_codes_colours_and_pages():
    assert escape_code(PAUSE) == 0x1000A
    assert escape_code(BmgEscape(0xFE, b"\x00\x00")) == 0xFE0000
    assert escape_code(BmgEscape(0x02, b"\x01")) is None
    assert escape_colour(BLUE) == 3 and escape_colour(WHITE) == 0
    assert escape_colour(PAUSE) is None
    # Three lines a page; the fourth starts the next.
    split = pages(parse_notation("a\nb{01:0E00B400}\nc\nd\ne"))
    assert [len(page) for page in split] == [3, 2]
    assert split[1] == [["d"], ["e"]]


def test_codes_are_the_kana_given_in_a_fixed_order():
    assert len(ARABIC_CODES) == len(set(ARABIC_CODES)) == 170
    assert (RTL_FIRST, RTL_LAST) == (0x3041, 0x30FC)
    assert all(RTL_FIRST <= code <= RTL_LAST for code in ARABIC_CODES)
    glyph_map = ph_glyph_codes({BEH["MEDIAL"], ".", " ", ALEF, SEEN})
    assert glyph_map.characters == (" ", ".", ALEF, BEH["MEDIAL"], SEEN)
    # A split form takes two codes: its right half's, then its left half's.
    assert glyph_map.sequence(SEEN) == (ARABIC_CODES[4], ARABIC_CODES[5])
    assert glyph_map.all_codes() == ARABIC_CODES[:6]
    assert SEEN in SPLIT_FORMS and len(SPLIT_FORMS) == 4 and BEH["MEDIAL"] not in SPLIT_FORMS
    assert glyph_characters()[:4] == (" ", ".", "!", ":")


@pytest.mark.parametrize("character", ["A", "ڤ"])
def test_characters_without_a_glyph_are_refused(character):
    with pytest.raises(ClassicRetroError) as caught:
        ph_glyph_codes({character})
    assert caught.value.code in (ErrorCode.UNENCODABLE_TEXT, ErrorCode.MISSING_GLYPH)


def test_a_line_is_stored_in_paint_order_its_first_letter_on_the_right():
    glyph_map = _map()
    stored = PhArabicEncoder(glyph_map).encode(parse_notation("بب ب.\nا"))
    assert stored.line_widths is None
    expected = (
        _code(glyph_map, BEH["INITIAL"])
        + _code(glyph_map, BEH["FINAL"])
        + _code(glyph_map, " ")
        + _code(glyph_map, BEH["ISOLATED"])
        + _code(glyph_map, ".")
        + "\n"
        + _code(glyph_map, ALEF)
    )
    assert stored.pieces == (expected,)
    assert all(RTL_FIRST <= ord(unit) <= RTL_LAST for unit in expected if unit != "\n")


def test_escapes_keep_their_places_between_the_letters():
    glyph_map = _map()
    text = "ب{01:0A001400} {FF:00000300}بب{FF:00000000}."
    stored = PhArabicEncoder(glyph_map).encode(parse_notation(text))
    assert stored.pieces == (
        _code(glyph_map, BEH["ISOLATED"]),
        PAUSE,
        _code(glyph_map, " "),
        BLUE,
        _code(glyph_map, BEH["INITIAL"]) + _code(glyph_map, BEH["FINAL"]),
        WHITE,
        _code(glyph_map, "."),
    )


def test_a_split_form_is_stored_right_half_first():
    glyph_map = _map()
    stored = PhArabicEncoder(glyph_map).encode(parse_notation("س"))
    assert stored.pieces == (_code(glyph_map, SEEN),)
    assert len(stored.pieces[0]) == 2


@pytest.mark.parametrize("text", ["ب{FE:0000}", "ب{02:0100}"])
def test_escapes_other_than_timing_and_colour_are_refused(text):
    with pytest.raises(ClassicRetroError) as caught:
        PhArabicEncoder(_map()).encode(parse_notation(text))
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_brackets_and_vowel_marks_are_refused():
    for text, code in (
        ("(ب)", ErrorCode.UNENCODABLE_TEXT),
        ("بَ", ErrorCode.UNSUPPORTED_ARABIC_MARK),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            painted_characters(parse_notation(text))
        assert caught.value.code is code


def test_lines_are_measured_against_the_box():
    glyph_map = _map()
    encoder = PhArabicEncoder(glyph_map, _fake_font(glyph_map, width=6))
    stored = encoder.encode(parse_notation("بب ب\n{01:0E00B400}\nب{FF:00000300}ب"))
    assert stored.line_widths == (6 + 6 + SPACE_WIDTH + 6, 0, 6 + 6)
    assert LINE_WIDTH == BOX_WIDTH - 2 * PEN_START == 206
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation("ب" * 35))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert encoder.encode(parse_notation("بببب"), 24).line_widths == (24,)


def test_escapes_and_line_ends_must_match_the_original():
    source = ("{01:0A001400}", "\n", "{01:0E00B400}")
    validate_command_skeleton(source, parse_notation("ب{01:0A001400} ب\nب{01:0E00B400}"))
    for text in ("ب{01:0A001400}\n{01:0E00B400}\n", "ب\n{01:0A001400}{01:0E00B400}"):
        with pytest.raises(ClassicRetroError) as caught:
            validate_command_skeleton(source, parse_notation(text))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_a_glyph_is_as_wide_as_its_advance_and_the_letter_spacing():
    glyph = ph_glyph({(0, 3), (4, 15)}, 5, soft={(1, 3), (0, 3), (6, 3)})
    assert glyph.widths.left == 0 and glyph.widths.width == 5
    assert glyph.widths.advance == 5 - LETTER_SPACING
    # Ink wins over smoothing, and nothing right of the width is kept.
    assert glyph.pixels[3][:2] == (INK, SOFT) and glyph.pixels[15][4] == INK
    assert not any(glyph.pixels[3][5:])
    assert len(glyph.pixels) == CELL_HEIGHT and len(glyph.pixels[0]) == CELL_WIDTH
    for ink, width in (({(0, 16)}, 5), ((), 15), ((), 0)):
        with pytest.raises(FormDoesNotFit):
            ph_glyph(ink, width)


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef, beh and a wide seen, with OpenType forms."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
        "seen": [(0, 0, 1500, 300)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x627: "alef", 0x628: "beh", 0x633: "seen"})
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        for left, bottom, right, top in shapes.get(name, []):
            pen.moveTo((left, bottom))
            pen.lineTo((left, top))
            pen.lineTo((right, top))
            pen.lineTo((right, bottom))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics["alef"] = (329, 100)
    metrics["seen"] = (1500, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro PH Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "contextual.ttf"
    builder.save(path)
    return path


def _ink(glyph) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, v in enumerate(row) if v == INK}


def test_the_font_draws_every_form_in_the_cell_on_the_arabic_baseline(contextual_font):
    glyph_map = ph_glyph_codes({" ", ".", "!", ALEF, SEEN, *BEH.values()})
    forms = (ALEF, SEEN, *BEH.values())
    font = build_ph_arabic_font(contextual_font, glyph_map, sizing=forms)

    assert font.font_size == 11
    assert set(font.glyphs) == set(glyph_map.all_codes())
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= CELL_WIDTH, code
        assert all(x < glyph.width for x, _ in _ink(glyph)), code
    # The body of beh (ink, then its smoothing) sits on the baseline, its dot below.
    beh = font.glyphs[glyph_map.code(BEH["ISOLATED"])]
    body = {(x, y) for y, row in enumerate(beh.pixels) for x, v in enumerate(row) if v}
    assert max(y for _, y in body if y < BASELINE) == BASELINE - 1
    assert {beh.pixels[y][x] for x, y in body} == {INK, SOFT}
    assert any(y > BASELINE for _, y in _ink(beh))
    medial = font.glyphs[glyph_map.code(BEH["MEDIAL"])]
    columns = {x for x, _ in _ink(medial)}
    assert min(columns) == 0 and max(columns) == medial.width - 1
    # The wide seen is two glyphs, the right half first, whose widths make its advance.
    right, left = (font.glyphs[code] for code in glyph_map.sequence(SEEN))
    assert left.width + right.width > CELL_WIDTH
    assert {x for x, _ in _ink(left)} == set(range(left.width))
    space = font.glyphs[glyph_map.code(" ")]
    assert space.width == SPACE_WIDTH and not _ink(space)
    stop = font.glyphs[glyph_map.code(".")]
    assert _ink(stop) == {(0, BASELINE - 2), (1, BASELINE - 2), (0, BASELINE - 1),
                          (1, BASELINE - 1)}  # fmt: skip
    assert stop.width == 4


def test_a_font_without_a_form_is_refused(contextual_font):
    glyph_map = ph_glyph_codes({unicodedata.lookup("ARABIC LETTER TEH ISOLATED FORM")})
    with pytest.raises(ClassicRetroError) as caught:
        build_ph_arabic_font(contextual_font, glyph_map, sizing=(ALEF,))
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_previews_end_every_line_at_the_box_right_edge():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=6)
    text = "بب\nب{FF:00000300}ب{FF:00000000}\nب\nبب"
    stored = PhArabicEncoder(glyph_map, font).encode(parse_notation(text))
    image = message_preview(font, stored.pieces)
    page = (BOX_WIDTH + 2 * PREVIEW_MARGIN, 3 * LINE_HEIGHT + 2 * PREVIEW_MARGIN)
    # Two pages side by side, the first on the right.
    assert image.size == (2 * page[0] + 4, page[1])
    first = page[0] + 4
    right = first + PREVIEW_MARGIN + BOX_WIDTH - PEN_START
    top = PREVIEW_MARGIN + 6
    white = PREVIEW_COLOURS[0]
    lit = [x for x in range(first, image.width) if image.getpixel((x, top)) == white]
    assert lit[-1] == right - 1 and lit[0] == right - 12
    # The second line: its first glyph white, the next one blue.
    second = top + LINE_HEIGHT
    assert image.getpixel((right - 1, second)) == white
    assert image.getpixel((right - 7, second)) == PREVIEW_COLOURS[3]
    assert image.getpixel((PREVIEW_MARGIN + BOX_WIDTH - PEN_START - 1, top)) == white
    assert font_preview(font).size[0] > 0
    sheet = messages_sheet([("one", image), ("two", image)])
    assert sheet.height >= 2 * image.height
