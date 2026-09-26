from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.nsmb import CELL_HEIGHT, CELL_WIDTH, colour_escape, parse_notation
from classic_retro.engines.nsmb_arabic import (
    ARABIC_CODES,
    BASELINE,
    INK,
    NUMBER_WIDTH,
    PREVIEW_MARGIN,
    SPACE_WIDTH,
    SPLIT_FORMS,
    NsmbArabicEncoder,
    NsmbArabicFont,
    build_nsmb_arabic_font,
    font_preview,
    glyph_characters,
    message_preview,
    messages_sheet,
    nsmb_glyph,
    nsmb_glyph_codes,
    painted_characters,
    validate_command_skeleton,
    visual_lines,
)
from classic_retro.font.glyph_raster import FormDoesNotFit
from classic_retro.text.bmg import BmgEscape

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
ALEF = unicodedata.lookup("ARABIC LETTER ALEF ISOLATED FORM")
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")
NUMBER = BmgEscape(0x01, bytes.fromhex("0100"))


def _map(text: str = "بب ب. ا س! بببب:") -> GlyphCodes:
    return nsmb_glyph_codes(painted_characters(parse_notation(text)))


def _fake_font(glyph_map: GlyphCodes, width: int = 5) -> NsmbArabicFont:
    """Every glyph a bar ``width`` pixels wide; the space is the real one."""
    bar = nsmb_glyph({(x, y) for x in range(width - 1) for y in range(4, BASELINE)}, width)
    glyphs = {}
    for character, codes in glyph_map.sequences.items():
        for code in codes:
            glyphs[code] = nsmb_glyph((), SPACE_WIDTH) if character == " " else bar
    return NsmbArabicFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def _code(glyph_map: GlyphCodes, character: str) -> str:
    return "".join(map(chr, glyph_map.sequence(character) or ()))


def test_codes_are_the_kana_given_in_a_fixed_order():
    assert len(ARABIC_CODES) == len(set(ARABIC_CODES)) == 166
    glyph_map = nsmb_glyph_codes({BEH["MEDIAL"], ".", " ", ALEF, SEEN})
    assert glyph_map.characters == (" ", ".", ALEF, BEH["MEDIAL"], SEEN)
    # A split form takes two codes: its left half's, then its right half's.
    assert glyph_map.sequence(SEEN) == (ARABIC_CODES[4], ARABIC_CODES[5])
    assert glyph_map.all_codes() == ARABIC_CODES[:6]
    assert SEEN in SPLIT_FORMS and BEH["MEDIAL"] not in SPLIT_FORMS
    assert glyph_characters()[:4] == (" ", ".", "!", ":")


@pytest.mark.parametrize("character", ["A", "ڤ"])
def test_characters_without_a_glyph_are_refused(character):
    with pytest.raises(ClassicRetroError) as caught:
        nsmb_glyph_codes({character})
    assert caught.value.code in (ErrorCode.UNENCODABLE_TEXT, ErrorCode.MISSING_GLYPH)


def test_a_line_is_stored_reversed_its_first_letter_on_the_right():
    glyph_map = _map()
    stored = NsmbArabicEncoder(glyph_map).encode(parse_notation("بب ب.\nا"), 200)
    assert stored.line_widths is None
    expected = (
        _code(glyph_map, ".")
        + _code(glyph_map, BEH["ISOLATED"])
        + _code(glyph_map, " ")
        + _code(glyph_map, BEH["FINAL"])
        + _code(glyph_map, BEH["INITIAL"])
        + "\n"
        + _code(glyph_map, ALEF)
    )
    assert stored.pieces == (expected,)


def test_a_split_form_is_stored_left_half_first():
    glyph_map = _map()
    stored = NsmbArabicEncoder(glyph_map).encode(parse_notation("س"), 200)
    assert stored.pieces == (_code(glyph_map, SEEN),)
    assert len(stored.pieces[0]) == 2


def test_colours_follow_their_glyphs_in_visual_order():
    glyph_map = _map()
    text = "ب {FF:00000100}{01:0100}{FF:00000000} بب"
    stored = NsmbArabicEncoder(glyph_map).encode(parse_notation(text), 200)
    # Visual order: "بب", a space, the number in colour 1, a space, "ب".
    assert stored.pieces == (
        _code(glyph_map, BEH["FINAL"]) + _code(glyph_map, BEH["INITIAL"]) + _code(glyph_map, " "),
        colour_escape(1),
        NUMBER,
        colour_escape(0),
        _code(glyph_map, " ") + _code(glyph_map, BEH["ISOLATED"]),
    )


def test_a_line_keeps_the_colour_its_text_ends_in():
    glyph_map = _map()
    text = "ب\n{FF:00000200}بب\n{FF:00000000}ب"
    lines = visual_lines(parse_notation(text))
    assert [end for _, end in lines] == [0, 2, 0]
    stored = NsmbArabicEncoder(glyph_map).encode(parse_notation(text), 200)
    assert stored.pieces == (
        _code(glyph_map, BEH["ISOLATED"]) + "\n",
        colour_escape(2),
        _code(glyph_map, BEH["FINAL"]) + _code(glyph_map, BEH["INITIAL"]) + "\n",
        colour_escape(0),
        _code(glyph_map, BEH["ISOLATED"]),
    )
    # A colour that changes after a line's last glyph is set again at its end.
    stored = NsmbArabicEncoder(glyph_map).encode(parse_notation("ب{FF:00000100}\nب"), 200)
    assert stored.pieces[1] == colour_escape(1)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("ب A", ErrorCode.UNENCODABLE_TEXT),
        ("ب 12", ErrorCode.UNENCODABLE_TEXT),
        ("(ب)", ErrorCode.UNENCODABLE_TEXT),
        ("بَ", ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ("ب{05:00}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
    ],
)
def test_what_a_reversed_line_cannot_hold_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as caught:
        NsmbArabicEncoder(_map()).encode(parse_notation(text), 200)
    assert caught.value.code is code


def test_lines_are_measured_against_their_width():
    glyph_map = _map()
    encoder = NsmbArabicEncoder(glyph_map, _fake_font(glyph_map, width=6))
    stored = encoder.encode(parse_notation("بب ب\nب {FF:00000100}{01:0100}{FF:00000000}"), 200)
    assert stored.line_widths == (6 + 6 + SPACE_WIDTH + 6, 6 + SPACE_WIDTH + NUMBER_WIDTH)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(parse_notation("بببب"), 20)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_escapes_and_line_ends_must_match_the_original():
    source = ("{FF:00000100}", "{01:0100}", "{FF:00000000}", "\n")
    validate_command_skeleton(source, parse_notation("ب{FF:00000100}{01:0100}{FF:00000000}\nب"))
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(source, parse_notation("ب{FF:00000100}{01:0100}{FF:00000000}"))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_a_glyph_keeps_its_ink_inside_its_cell():
    glyph = nsmb_glyph({(0, 3), (4, 14)}, 5)
    assert glyph.widths.advance == 5 and glyph.pixels[14][4] == INK
    assert len(glyph.pixels) == CELL_HEIGHT and len(glyph.pixels[0]) == CELL_WIDTH
    for ink, width in (({(0, 15)}, 5), ((), 12), ((), 0)):
        with pytest.raises(FormDoesNotFit):
            nsmb_glyph(ink, width)


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef, beh and a wide seen, with OpenType forms."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
        "seen": [(0, 0, 1200, 300)],
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
    metrics["seen"] = (1200, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro NSMB Test", "styleName": "Regular"})
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
    glyph_map = nsmb_glyph_codes({" ", ".", "!", ALEF, SEEN, *BEH.values()})
    forms = (ALEF, SEEN, *BEH.values())
    font = build_nsmb_arabic_font(contextual_font, glyph_map, sizing=forms)

    assert set(font.glyphs) == set(glyph_map.all_codes())
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= CELL_WIDTH, code
        assert all(x < glyph.width for x, _ in _ink(glyph)), code
    beh = font.glyphs[glyph_map.code(BEH["ISOLATED"])]
    assert max(y for _, y in _ink(beh) if y < BASELINE) == BASELINE - 1
    medial = font.glyphs[glyph_map.code(BEH["MEDIAL"])]
    columns = {x for x, _ in _ink(medial)}
    assert min(columns) == 0 and max(columns) == medial.width - 1
    # The wide seen is two glyphs whose widths make its advance.
    left, right = (font.glyphs[code] for code in glyph_map.sequence(SEEN))
    assert font.width(SEEN) == left.width + right.width > CELL_WIDTH
    space = font.glyphs[glyph_map.code(" ")]
    assert space.width == SPACE_WIDTH and not _ink(space)
    stop = font.glyphs[glyph_map.code(".")]
    assert _ink(stop) == {(0, BASELINE - 2), (1, BASELINE - 2), (0, BASELINE - 1),
                          (1, BASELINE - 1)}  # fmt: skip
    assert stop.width == 3


def test_a_font_without_a_form_is_refused(contextual_font):
    glyph_map = nsmb_glyph_codes({unicodedata.lookup("ARABIC LETTER TEH ISOLATED FORM")})
    with pytest.raises(ClassicRetroError) as caught:
        build_nsmb_arabic_font(contextual_font, glyph_map, sizing=(ALEF,))
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_previews_centre_every_line_with_the_shadow():
    glyph_map = _map()
    font = _fake_font(glyph_map, width=6)
    stored = NsmbArabicEncoder(glyph_map, font).encode(parse_notation("بب\nب"), 60)
    image = message_preview(font, stored.pieces, 60)
    assert image.size == (60 + 2 * PREVIEW_MARGIN, 2 * CELL_HEIGHT + 2 * PREVIEW_MARGIN)
    top = PREVIEW_MARGIN + 6
    white = [x for x in range(image.width) if image.getpixel((x, top)) == (246, 246, 246)]
    # Two glyphs of 6 (ink 5 each) centred in 60: from 24 to 36.
    assert white[0] == PREVIEW_MARGIN + 24 and white[-1] == PREVIEW_MARGIN + 34
    assert image.getpixel((white[-1] + 1, top)) != image.getpixel((0, 0))
    assert font_preview(font).size[0] > 0
    sheet = messages_sheet([("one", image), ("two", image)])
    assert sheet.height >= 2 * image.height
