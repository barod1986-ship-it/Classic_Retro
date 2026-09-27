from __future__ import annotations

import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.chrono_trigger import (
    BOX_INDENTED,
    CHARACTERS,
    DICTIONARY_BANK,
    DICTIONARY_TABLE,
    LINE,
    LINE_INDENTED,
    dictionary,
    string_bytes,
    string_notation,
    table_string,
)
from classic_retro.engines.chrono_trigger_arabic import (
    ARABIC_CODES,
    CELL,
    CLEAR,
    CORNER,
    INK,
    LAST_PEN,
    LINE_INDENT,
    LINE_START,
    MAX_LINES,
    MIRROR,
    NAME_WIDTH,
    PREVIEW_BACKGROUND,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    SHADOW,
    SPACE_WIDTH,
    WIDEST,
    ChronoTriggerArabicEncoder,
    CtFont,
    CtGlyph,
    EncodedMessage,
    build_chrono_trigger_font,
    chrono_trigger_glyph_codes,
    font_preview,
    form_glyph,
    glyph_characters,
    hand_drawn_glyph,
    message_characters,
    message_preview,
    paint_text,
    shaded_glyph,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip


def _code(text: str) -> bytes:
    return bytes(0xA0 + CHARACTERS.index(character) for character in text)


# ---------------------------------------------------------------------------
# The game's text


@pytest.fixture(scope="module")
def rom() -> bytes:
    """A dictionary of three words (the, ou, CHANCELLOR:) and the rest empty."""
    data = bytearray(0x200000)
    words = [_code("the"), _code("ou"), _code("CHANCELLOR:")]
    at = 0xF000
    pointers = []
    for word in words + [b""] * 124:
        pointers.append(at)
        data[DICTIONARY_BANK + at] = len(word)
        data[DICTIONARY_BANK + at + 1 : DICTIONARY_BANK + at + 1 + len(word)] = word
        at += 1 + len(word)
    struct.pack_into("<127H", data, DICTIONARY_TABLE, *pointers)
    return bytes(data)


def test_the_dictionary_is_127_words_of_the_font(rom):
    words = dictionary(rom)
    assert len(words) == 127
    assert words[:3] == (_code("the"), _code("ou"), _code("CHANCELLOR:"))
    assert words[3] == b""


def test_a_string_ends_at_its_zero_past_the_bytes_of_its_codes():
    data = bytes([0x03, 0x00, 0xA0, 0x01, 0x00, 0x12, 0x00, 0xA1, 0x00, 0xFF])
    assert string_bytes(data, 0) == data[:9]
    with pytest.raises(ClassicRetroError) as caught:
        string_bytes(bytes([0xA0, 0x03]), 0)
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_the_notation_writes_words_names_and_codes(rom):
    words = dictionary(rom)
    data = (
        _code("MOM: ")
        + bytes([0x21])
        + _code(" b")
        + bytes([0x22, LINE_INDENTED, 0x15, 0x03, 0x0F, 0xDE, BOX_INDENTED, 0x1B, 0x10, 0x00])
    )
    assert string_notation(data, words) == (
        "MOM: the bou{line+}{Lucca}{pause 0F}!{box+}{member 1}{code 10}"
    )
    assert string_notation(bytes([0xF1, 0xEE, LINE]), words) == "…♪{line}"
    # 1A reads Crono's name from its own address, as 13 does through the table.
    assert string_notation(bytes([0x1A, 0x12, 0x01, 0x1F, 0x20]), words) == (
        "{Crono}{code 12 01}{item}{Epoch}"
    )
    with pytest.raises(ClassicRetroError) as caught:
        string_notation(bytes([0xF4]), words)
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE
    with pytest.raises(ClassicRetroError) as caught:
        string_notation(bytes([0x03]), words)
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_a_table_points_into_its_own_bank():
    data = bytearray(0x20000)
    struct.pack_into("<3H", data, 0x10000, 0x0006, 0x0010, 0x0020)
    assert table_string(bytes(data), 0x10000, 2) == 0x10020


# ---------------------------------------------------------------------------
# Codes, glyphs and encoding


def _map(*texts: str) -> GlyphCodes:
    characters: set[str] = set()
    for text in texts:
        characters |= message_characters(text)
    return chrono_trigger_glyph_codes(characters)


def _bar(width: int) -> CtGlyph:
    return CtGlyph(width, tuple((INK,) * width + (CLEAR,) * (WIDEST - width) for _ in range(CELL)))


def _font(glyph_map: GlyphCodes, width: int = 10) -> CtFont:
    """Every glyph a bar ``width`` pixels wide; the space the real one."""
    glyphs = {
        code: CtGlyph(SPACE_WIDTH, ((CLEAR,) * WIDEST,) * CELL) if character == " " else _bar(width)
        for character, (code,) in glyph_map.sequences.items()
    }
    return CtFont(glyphs, 9)


def test_the_codes_start_after_the_control_codes_in_the_fonts_order():
    assert ARABIC_CODES[0] == 0x21 and ARABIC_CODES[-1] == 0xFF
    assert glyph_characters()[:3] == (" ", ".", ",")
    glyph_map = chrono_trigger_glyph_codes({BEH["ISOLATED"], " ", "1", "!"})
    assert [glyph_map.code(c) for c in (" ", "!", "1", BEH["ISOLATED"])] == [0x21, 0x22, 0x23, 0x24]
    for character, error in (("A", ErrorCode.UNENCODABLE_TEXT), ("ﭐ", ErrorCode.MISSING_GLYPH)):
        with pytest.raises(ClassicRetroError) as caught:
            chrono_trigger_glyph_codes({character})
        assert caught.value.code is error


def test_a_message_is_painted_from_the_right_in_reading_order():
    assert paint_text("بب ب") == BEH["INITIAL"] + BEH["FINAL"] + " " + BEH["ISOLATED"]
    glyph_map = _map("ب {Lucca}!")
    encoded = ChronoTriggerArabicEncoder(glyph_map).encode("ب {Lucca}!")
    code = glyph_map.code
    assert encoded.data == bytes([code(BEH["ISOLATED"]), code(" "), 0x15, code("!"), 0x00])
    assert encoded.boxes is None


def test_a_speakers_lines_and_boxes_are_indented():
    glyph_map = _map("ب: ب{line}ب\nب")
    encoder = ChronoTriggerArabicEncoder(glyph_map, _font(glyph_map))
    encoded = encoder.encode("ب: ب{line}ب\nب")
    lines = [[(line.start, line.end) for line in box] for box in encoded.boxes or ()]
    colon = 10  # every glyph a bar of 10, the space 4
    assert lines == [
        [(LINE_START, LINE_START + 10 + colon + SPACE_WIDTH + 10), (LINE_INDENT, LINE_INDENT + 10)],
        [(LINE_INDENT, LINE_INDENT + 10)],
    ]
    assert encoded.data.count(LINE_INDENTED) == 1 and encoded.data.count(BOX_INDENTED) == 1
    plain = encoder.encode("ب{line}ب\nب")
    assert plain.data.count(LINE) == 1 and plain.data.count(0x0B) == 1
    assert [line.start for box in plain.boxes or () for line in box] == [LINE_START] * 3


def test_lines_break_before_the_word_that_would_pass_the_last_pen():
    words = " ".join(["ببب"] * 12)  # 30 pixels a word, 34 with its space
    glyph_map = _map(words)
    encoded = ChronoTriggerArabicEncoder(glyph_map, _font(glyph_map)).encode(words)
    assert encoded.boxes is not None
    ends = [line.end for line in encoded.boxes[0]]
    assert all(end <= LAST_PEN for end in ends)
    assert [len(line.data) for line in encoded.boxes[0]] == [23, 23]  # six words each
    names = " ".join(["{Crono}"] * 5)
    wide = ChronoTriggerArabicEncoder(_map("ب"), _font(_map("ب"))).encode(names)
    assert wide.boxes is not None and len(wide.boxes[0]) == 2
    assert wide.boxes[0][0].end == LINE_START + 4 * NAME_WIDTH + 3 * SPACE_WIDTH


def test_a_box_holds_four_lines_and_a_word_a_line():
    long_word = "ب" * 20  # 240 pixels
    glyph_map = _map("ب", long_word)
    encoder = ChronoTriggerArabicEncoder(glyph_map, _font(glyph_map, width=12))
    five = "{line}".join(["ب"] * (MAX_LINES + 1))
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(five)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(long_word)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    for bad, error in (
        ("ب  ب", ErrorCode.UNENCODABLE_TEXT),
        ("ب\n", ErrorCode.UNENCODABLE_TEXT),
        ("{Chrono}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode(bad)
        assert caught.value.code is error, bad


def test_a_glyph_has_the_games_shadow_inside_its_width():
    glyph = shaded_glyph({(0, 2), (1, 2)}, 3)
    assert glyph.rows[2][:4] == (INK, INK, SHADOW, CLEAR)
    assert glyph.rows[3][:4] == (SHADOW, SHADOW, CORNER, CLEAR)
    cut = shaded_glyph({(0, 2), (1, 2)}, 2)
    assert cut.rows[2][:3] == (INK, INK, CLEAR) and cut.rows[3][:3] == (SHADOW, SHADOW, CLEAR)
    for ink, width in (({(0, CELL - 1)}, 2), ({(12, 0)}, 13), ({(-1, 0)}, 2)):
        with pytest.raises(FormDoesNotFit):
            shaded_glyph(ink, width)
    # A form that joins the glyph on its right ends at its ink; any other has a free column.
    stroke = {(x, 5) for x in range(4)}
    assert form_glyph(BEH["FINAL"], stroke, 4).width == 4
    assert form_glyph(BEH["INITIAL"], stroke, 4).width == 5
    assert form_glyph(BEH["ISOLATED"], stroke, 7).width == 7
    stop = hand_drawn_glyph(".")
    assert stop.width == 4 and stop.rows[6][:4] == (INK, INK, SHADOW, CLEAR)


def test_a_glyph_is_stored_as_the_hook_reads_it():
    rows = [[CLEAR] * WIDEST for _ in range(CELL)]
    rows[0][0] = INK  # both planes
    rows[1][7] = SHADOW  # plane 0
    rows[2][8] = CORNER  # plane 1, right part
    rows[3][11] = INK
    data = CtGlyph(12, tuple(tuple(row) for row in rows)).data()
    assert len(data) == 48
    assert data[0:2] == bytes([0x80, 0x80])
    assert data[2:4] == bytes([0x01, 0x00])
    assert data[24 + 4 : 24 + 6] == bytes([0x00, 0x80])
    assert data[24 + 6 : 24 + 8] == bytes([0x10, 0x10])


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


def test_the_font_is_drawn_at_the_largest_size_its_cell_holds(beh_font):
    used = {BEH["INITIAL"], BEH["FINAL"], " ", "!", "1"}
    glyph_map = chrono_trigger_glyph_codes(used)
    font = build_chrono_trigger_font(beh_font, glyph_map, used, sizing=set(BEH.values()) | {"1"})
    assert font.font_size in range(8, 14)
    code = glyph_map.code
    assert set(font.glyphs) == {code(character) for character in used}
    initial = font.glyphs[code(BEH["INITIAL"])]
    final = font.glyphs[code(BEH["FINAL"])]
    # The initial joins on its left: its first column is ink; the final's last is.
    assert any(row[0] == INK for row in initial.rows)
    assert any(row[final.width - 1] == INK for row in final.rows)
    assert font.glyphs[code(" ")].width == SPACE_WIDTH
    assert font.glyphs[code("!")] == hand_drawn_glyph("!")
    with pytest.raises(ClassicRetroError) as caught:
        build_chrono_trigger_font(beh_font, glyph_map, {"A"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_previews_show_the_glyphs_at_the_mirror_of_the_pen():
    glyph_map = _map("بب {Crono}")
    font = _font(glyph_map)
    encoded = ChronoTriggerArabicEncoder(glyph_map, font).encode("بب {Crono}")
    image = message_preview(encoded, font)
    assert image.width == MIRROR
    y = PREVIEW_MARGIN + 5
    assert image.getpixel((MIRROR - LINE_START - 1, y)) == PREVIEW_COLOURS[INK]
    assert image.getpixel((MIRROR - LINE_START + 1, y)) == PREVIEW_BACKGROUND
    # The name, a grey bar left of the word and its space.
    name_x = MIRROR - LINE_START - 20 - SPACE_WIDTH - NAME_WIDTH
    assert image.getpixel((name_x + 1, PREVIEW_MARGIN + 6)) == (150, 150, 150)
    atlas = font_preview(font)
    assert atlas.width > 0 and atlas.height > 0
    with pytest.raises(ClassicRetroError):
        message_preview(EncodedMessage(encoded.data, None), font)
