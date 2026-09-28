from __future__ import annotations

import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.alttp import (
    CHARACTERS,
    DICTIONARY_BANK,
    DICTIONARY_CODES,
    END,
    FINISH,
    LINE_2,
    LINE_3,
    MESSAGE_DATA,
    MESSAGE_DATA_EXTRA,
    NAME,
    SCROLL,
    SPACE,
    SWITCH_BANK,
    WAIT_KEY,
    WORD_DICTIONARY,
    dictionary,
    lorom_address,
    lorom_offset,
    message_notation,
    messages,
)
from classic_retro.engines.alttp_arabic import (
    ARABIC_CODES,
    CELL,
    CLEAR,
    INK,
    LINE_WIDTH,
    MAX_LINES,
    NAME_WIDTH,
    OUTLINE,
    PREVIEW_BACKGROUND,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    SPACE_CODE,
    SPACE_WIDTH,
    AlttpArabicEncoder,
    AlttpFont,
    AlttpGlyph,
    EncodedMessage,
    alttp_glyph_codes,
    build_alttp_font,
    font_preview,
    glyph_characters,
    hand_drawn_glyph,
    message_characters,
    message_preview,
    outlined_glyph,
    paint_text,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip


def _code(text: str) -> bytes:
    return bytes(CHARACTERS.index(character) for character in text)


# ---------------------------------------------------------------------------
# The game's text


def _put(rom: bytearray, offset: int, data: bytes) -> int:
    rom[offset : offset + len(data)] = data
    return offset + len(data)


@pytest.fixture(scope="module")
def rom() -> bytes:
    """A dictionary of two words (the, ou), and three messages: two in the first block, the
    third after the switch to the second."""
    data = bytearray(0x100000)
    words = [_code("the"), _code("ou")] + [b""] * 95
    start = 0xC800
    pointers = []
    for word in words:
        pointers.append(start)
        _put(data, DICTIONARY_BANK + start, word)
        start += len(word)
    pointers.append(start)
    struct.pack_into(f"<{len(pointers)}H", data, WORD_DICTIONARY, *pointers)
    at = _put(data, MESSAGE_DATA, _code("Hi") + bytes([0x88, LINE_2, NAME, END]))
    at = _put(data, at, bytes([0x7A, 0x03]) + _code("y") + bytes([0x89, END]))
    _put(data, at, bytes([SWITCH_BANK]))
    _put(data, MESSAGE_DATA_EXTRA, _code("Go!") + bytes([END, FINISH]))
    return bytes(data)


def test_lorom_addresses_are_32_kib_pieces():
    assert lorom_offset(0x1C8000) == MESSAGE_DATA == lorom_offset(0x9C8000)
    assert lorom_offset(0x0EDF40) == MESSAGE_DATA_EXTRA
    assert lorom_address(MESSAGE_DATA_EXTRA) == 0x0EDF40
    with pytest.raises(ClassicRetroError) as caught:
        lorom_offset(0x0E7FFF)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_the_dictionary_is_97_words_each_to_the_next_ones_start(rom):
    words = dictionary(rom)
    assert len(words) == len(DICTIONARY_CODES) == 97
    assert words[:3] == (_code("the"), _code("ou"), b"")


def test_messages_are_found_as_the_game_finds_them(rom):
    found = messages(rom)
    assert [message.offset for message in found] == [
        MESSAGE_DATA,
        MESSAGE_DATA + 6,
        MESSAGE_DATA_EXTRA,
    ]
    assert found[1].data == bytes([0x7A, 0x03]) + _code("y") + bytes([0x89, END])
    with pytest.raises(ClassicRetroError) as caught:
        messages(bytes(rom[:MESSAGE_DATA]) + bytes([0x00] * 16))
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_the_notation_writes_words_signs_and_commands(rom):
    words = dictionary(rom)
    found = messages(rom)
    assert message_notation(found[0].data, words) == "Hithe{2}{Name}"
    assert message_notation(found[1].data, words) == "{Speed 03}you"
    assert CHARACTERS[SPACE] == " " and CHARACTERS[0x43] == "…"
    assert message_notation(bytes([0x47, 0x5B, 0x59, 0x51]), words) == "{Ankh}{A} '"
    for data, error in (
        (bytes([0x63]), ErrorCode.UNKNOWN_TEXT_BYTE),
        (bytes([0x85]), ErrorCode.UNKNOWN_TEXT_BYTE),
        (bytes([0x78]), ErrorCode.MISSING_TERMINATOR),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            message_notation(data, words)
        assert caught.value.code is error


# ---------------------------------------------------------------------------
# Codes, glyphs and encoding


def _map(*texts: str) -> GlyphCodes:
    characters: set[str] = set()
    for text in texts:
        characters |= message_characters(text)
    return alttp_glyph_codes(characters)


def _bar(width: int) -> AlttpGlyph:
    return AlttpGlyph(width, tuple((INK,) * width + (CLEAR,) * (CELL - width) for _ in range(CELL)))


def _font(glyph_map: GlyphCodes, width: int = 10) -> AlttpFont:
    """Every glyph a bar ``width`` pixels wide; the space the real one."""
    glyphs = {
        code: _bar(0) if character == " " else _bar(width)
        for character, (code,) in glyph_map.sequences.items()
    }
    glyphs[SPACE_CODE] = AlttpGlyph(SPACE_WIDTH, _bar(0).rows)
    return AlttpFont(glyphs, 11)


def test_the_codes_skip_the_commands_and_the_space_keeps_its_code():
    assert len(ARABIC_CODES) == 205 and SPACE not in ARABIC_CODES
    assert ARABIC_CODES[:2] == (0x00, 0x01) and ARABIC_CODES[101:103] == (0x66, 0x80)
    assert ARABIC_CODES[-1] == 0xE6
    assert not set(ARABIC_CODES) & set(range(0x67, 0x80))
    assert glyph_characters()[:3] == (".", ",", ":")
    glyph_map = alttp_glyph_codes({BEH["ISOLATED"], " ", "1", "!"})
    assert [glyph_map.code(c) for c in (" ", "!", "1", BEH["ISOLATED"])] == [SPACE, 0, 1, 2]
    for character, error in (("A", ErrorCode.UNENCODABLE_TEXT), ("ﭐ", ErrorCode.MISSING_GLYPH)):
        with pytest.raises(ClassicRetroError) as caught:
            alttp_glyph_codes({character})
        assert caught.value.code is error


def test_a_message_is_painted_from_the_right_in_reading_order():
    assert paint_text("بب ب") == BEH["INITIAL"] + BEH["FINAL"] + " " + BEH["ISOLATED"]
    glyph_map = _map("ب {Name}!")
    encoded = AlttpArabicEncoder(glyph_map).encode("{Window 02}ب {Name}!")
    code = glyph_map.code
    assert encoded.data == bytes([0x6B, 0x02, code(BEH["ISOLATED"]), SPACE, NAME, code("!"), END])
    assert encoded.pages is None


def test_lines_change_as_the_english_does_and_pages_wait_for_the_button():
    glyph_map = _map("ب")
    encoder = AlttpArabicEncoder(glyph_map, _font(glyph_map))
    b = glyph_map.code(BEH["ISOLATED"])
    encoded = encoder.encode("ب{line}{line}ب\nب{line}ب")
    assert encoded.data == bytes([b, LINE_2, LINE_3, b, WAIT_KEY, SCROLL, b, SCROLL, b, END])
    assert [[line.width for line in page] for page in encoded.pages or ()] == [
        [10, 0, 10],
        [10, 10],
    ]


def test_lines_break_before_the_word_that_would_pass_the_line():
    words = " ".join(["ببب"] * 8)  # 30 pixels a word, 34 with its space
    glyph_map = _map(words)
    encoded = AlttpArabicEncoder(glyph_map, _font(glyph_map)).encode(words)
    assert encoded.pages is not None
    widths = [line.width for line in encoded.pages[0]]
    assert all(width <= LINE_WIDTH for width in widths)
    assert [len(line.data) for line in encoded.pages[0]] == [19, 11]  # five words, then three
    names = " ".join(["{Name}"] * 4)
    wide = AlttpArabicEncoder(_map("ب"), _font(_map("ب"))).encode(names)
    assert wide.pages is not None and len(wide.pages[0]) == 2
    assert wide.pages[0][0].width == 3 * NAME_WIDTH + 2 * SPACE_WIDTH


def test_a_page_holds_three_lines_and_a_word_a_line():
    long_word = "ب" * 15  # 180 pixels
    glyph_map = _map("ب", long_word)
    encoder = AlttpArabicEncoder(glyph_map, _font(glyph_map, width=12))
    four = "{line}".join(["ب"] * (MAX_LINES + 1))
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(four)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode(long_word)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    for bad, error in (
        ("ب  ب", ErrorCode.UNENCODABLE_TEXT),
        (" ب", ErrorCode.UNENCODABLE_TEXT),
        ("{Link}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{Choose}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{Speed}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{Name 01}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode(bad)
        assert caught.value.code is error, bad


def test_a_glyph_is_outlined_but_on_its_joining_sides():
    stroke = {(x, 8) for x in range(4)}
    alone = outlined_glyph(stroke, joins_left=False, joins_right=False)
    assert alone.width == 6
    assert alone.rows[8][:7] == (OUTLINE, INK, INK, INK, INK, OUTLINE, CLEAR)
    assert alone.rows[7][:7] == (OUTLINE,) * 6 + (CLEAR,)
    joined = outlined_glyph(stroke, joins_left=True, joins_right=True)
    assert joined.width == 4
    assert joined.rows[8][:5] == (INK, INK, INK, INK, CLEAR)
    assert joined.rows[9][:5] == (OUTLINE,) * 4 + (CLEAR,)
    for ink in ({(0, 0)}, {(0, CELL - 1)}, {(x, 5) for x in range(16)}):
        with pytest.raises(FormDoesNotFit):
            outlined_glyph(ink, joins_left=False, joins_right=False)
    stop = hand_drawn_glyph(".")
    assert stop.width == 4 and stop.rows[9][:5] == (OUTLINE, INK, INK, OUTLINE, CLEAR)


def test_a_glyph_is_stored_as_the_hook_reads_it():
    rows = [[CLEAR] * CELL for _ in range(CELL)]
    rows[0][0] = 3  # both planes
    rows[1][7] = OUTLINE  # plane 0
    rows[2][8] = INK  # plane 1, the right byte
    rows[3][15] = OUTLINE
    data = AlttpGlyph(16, tuple(tuple(row) for row in rows)).data()
    assert len(data) == 64
    assert data[0:4] == bytes([0x00, 0x80, 0x00, 0x80])
    assert data[4:8] == bytes([0x00, 0x01, 0x00, 0x00])
    assert data[8:12] == bytes([0x00, 0x00, 0x80, 0x00])
    assert data[12:16] == bytes([0x01, 0x00, 0x00, 0x00])


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
    glyph_map = alttp_glyph_codes(used)
    font = build_alttp_font(beh_font, glyph_map, used, sizing=set(BEH.values()) | {"1"})
    assert font.font_size in range(8, 15)
    code = glyph_map.code
    assert set(font.glyphs) == {code(character) for character in used}
    initial = font.glyphs[code(BEH["INITIAL"])]
    final = font.glyphs[code(BEH["FINAL"])]
    # The initial joins on its left: its first column is ink; the final's last is.
    assert any(row[0] == INK for row in initial.rows)
    assert any(row[final.width - 1] == INK for row in final.rows)
    assert font.glyphs[SPACE_CODE].width == SPACE_WIDTH
    assert font.glyphs[code("!")] == hand_drawn_glyph("!")
    with pytest.raises(ClassicRetroError) as caught:
        build_alttp_font(beh_font, glyph_map, {"A"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_previews_show_the_glyphs_at_the_mirror_of_the_pen():
    glyph_map = _map("بب {Name}")
    font = _font(glyph_map)
    encoded = AlttpArabicEncoder(glyph_map, font).encode("{Speed 01}بب {Name}")
    image = message_preview(encoded, font)
    assert image.width == LINE_WIDTH + 2 * PREVIEW_MARGIN
    right = PREVIEW_MARGIN + LINE_WIDTH
    y = PREVIEW_MARGIN + 5
    assert image.getpixel((right - 1, y)) == PREVIEW_COLOURS[INK]
    assert image.getpixel((right + 1, y)) == PREVIEW_BACKGROUND
    # The name, a grey bar left of the word and its space.
    name_x = right - 20 - SPACE_WIDTH - NAME_WIDTH
    assert image.getpixel((name_x + 1, PREVIEW_MARGIN + 8)) == (150, 150, 150)
    atlas = font_preview(font)
    assert atlas.width > 0 and atlas.height > 0
    with pytest.raises(ClassicRetroError):
        message_preview(EncodedMessage(encoded.data, None), font)
