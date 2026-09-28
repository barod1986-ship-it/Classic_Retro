from __future__ import annotations

import dataclasses
import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines import ff4
from classic_retro.engines.ff4 import (
    BANKS,
    BLANK,
    CHARACTER_CODES,
    CLOSE,
    COMMAND_CODES,
    DTE_CODES,
    DTE_FIRST,
    DTE_TABLE,
    END,
    ISLAND_CODES,
    LAYOUT_COMMANDS,
    LINE,
    ROW,
    SPACE,
    byte_length,
    command_notation,
    command_skeleton,
    dte_pairs,
    lorom_address,
    lorom_offset,
    message_at,
    message_notation,
    messages,
)
from classic_retro.engines.ff4_arabic import (
    ARABIC_CODES,
    BACKGROUND,
    BLANK_TOP,
    CELL,
    CELL_HEIGHT,
    INK,
    LETTER_CODES,
    NAME_CELLS,
    PAIR_CODES,
    PREVIEW_BLOCK,
    PREVIEW_COLOURS,
    PREVIEW_MARGIN,
    SIGN_CODES,
    SPACE_CODE,
    TILE_ROWS,
    EncodedMessage,
    Ff4ArabicEncoder,
    Ff4Font,
    Ff4Glyph,
    TileSet,
    build_ff4_font,
    compensate_islands,
    decoded_rows,
    encode_name,
    ff4_glyph_codes,
    font_preview,
    glyph_characters,
    hand_drawn_glyph,
    message_characters,
    message_preview,
    notation_skeleton,
    pack_tile,
    paint_text,
    placed_glyph,
    shown_row,
    tile_set,
    tiles_needed,
    unpack_tile,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
NAME = COMMAND_CODES["Name"]


def _code(text: str) -> bytes:
    return bytes(CHARACTER_CODES[character] for character in text)


# ---------------------------------------------------------------------------
# The game's text


def _put(rom: bytearray, offset: int, data: bytes) -> int:
    rom[offset : offset + len(data)] = data
    return offset + len(data)


@pytest.fixture(scope="module")
def rom() -> bytes:
    """A table of pairs (the first two "th" and "e "), the map bank with a block of two
    messages and an entry to a third, and the event banks with a message each."""
    data = bytearray(0x100000)
    table = lorom_offset(DTE_TABLE)
    for code in DTE_CODES:
        _put(data, table + 2 * (code - DTE_FIRST), _code("xx"))
    _put(data, table + 2 * (0x8A - DTE_FIRST), _code("th"))
    _put(data, table + 2 * (0x8B - DTE_FIRST), _code("e "))
    map_bank, event1, event2 = BANKS
    text = lorom_offset(map_bank.text)
    block = _code("Hi") + bytes([0x8A, LINE, NAME, 0x00, END]) + _code("Yes") + bytes([CLOSE])
    third = bytes([0x21]) + _code("Go") + bytes([0x8B, 0x05, 0x10, END])
    _put(data, text, block + third)
    struct.pack_into("<3H", data, lorom_offset(map_bank.pointers), 0, len(block), 0)
    _put(data, lorom_offset(event1.text), _code("Crew") + bytes([0xC8, 0x02, 0x03, END]))
    _put(data, lorom_offset(event2.text), _code("Bye") + bytes([END]))
    return bytes(data)


@pytest.fixture
def narrowed(monkeypatch):
    """The banks' text ended where the fixture's messages end."""
    ends = {0: 18, 1: 8, 2: 4}
    banks = {
        bank.number: dataclasses.replace(bank, end=bank.text + ends[bank.number]) for bank in BANKS
    }
    monkeypatch.setattr(ff4, "BANK_BY_NUMBER", banks)


def test_lorom_addresses_are_32_kib_pieces():
    assert lorom_offset(0x118300) == 0x88300 == lorom_offset(0x918300)
    assert lorom_address(0x88300) == 0x118300
    with pytest.raises(ClassicRetroError) as caught:
        lorom_offset(0x110000)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_the_pairs_come_from_the_rom(rom):
    pairs = dte_pairs(rom)
    assert len(pairs) == 107 and set(pairs) == set(DTE_CODES)
    assert pairs[0x8A] == "th" and pairs[0x8B] == "e " and pairs[0xFE] == "xx"


def test_messages_are_found_from_each_entry_to_the_next(rom, narrowed):
    found = messages(rom, 0)
    assert [message.offset for message in found] == [0, 7, 11]
    assert found[0].data == _code("Hi") + bytes([0x8A, LINE, NAME, 0x00, END])
    assert found[1].data == _code("Yes") + bytes([CLOSE])
    assert found[2].data.endswith(bytes([0x05, 0x10, END]))
    assert found[2].address == BANKS[0].text + 11
    assert message_at(rom, 0, 7) == found[1]
    with pytest.raises(ClassicRetroError) as caught:
        message_at(rom, 0, 8)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE
    assert [message.offset for message in messages(rom, 1)] == [0]
    assert messages(rom, 2)[0].data == _code("Bye") + bytes([END])
    outside = bytearray(rom)
    struct.pack_into("<H", outside, lorom_offset(BANKS[1].pointers), 0x7000)
    with pytest.raises(ClassicRetroError) as caught:
        messages(bytes(outside), 1)
    assert caught.value.code is ErrorCode.REFERENCE_OUT_OF_BOUNDS


def test_a_message_without_an_end_is_refused(rom, narrowed):
    broken = bytearray(rom)
    broken[lorom_offset(BANKS[2].text) + 3] = 0x42
    with pytest.raises(ClassicRetroError) as caught:
        messages(bytes(broken), 2)
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_the_notation_writes_pairs_icons_and_commands(rom, narrowed):
    pairs = dte_pairs(rom)
    found = messages(rom, 0)
    assert message_notation(found[0].data, pairs) == "Hith{line}{Name 00}"
    assert message_notation(found[1].data, pairs) == "Yes{Close}"
    assert message_notation(found[2].data, pairs) == "{Petrify}Goe {Wait 10}"
    assert message_notation(messages(rom, 1)[0].data, pairs) == "Crew:{Spaces 03}"
    with pytest.raises(ClassicRetroError) as caught:
        message_notation(bytes([0x0A, END]), pairs)
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE
    assert command_notation(COMMAND_CODES["Item"]) == "{Item}"
    with pytest.raises(ClassicRetroError):
        command_notation(COMMAND_CODES["Item"], 1)
    with pytest.raises(ClassicRetroError):
        command_notation(COMMAND_CODES["Wait"])


def test_the_command_skeleton_keeps_every_command_but_the_layout():
    data = bytes([0x03, 0x2A, LINE, 0x02, 0x04, BLANK, NAME, 0x01, 0x08, 0x07, CLOSE, 0x05, 0x01])
    assert command_skeleton(data) == ("{Song 2A}", "{Name 01}", "{Gil}", "{Item}", "{Close}")
    assert command_skeleton(_code("Go") + bytes([END, NAME, 0x00])) == ()
    assert LAYOUT_COMMANDS == {LINE, BLANK, COMMAND_CODES["Spaces"]}
    assert byte_length(NAME) == 2 and byte_length(0x42) == 1 and byte_length(CLOSE) == 1
    with pytest.raises(ClassicRetroError) as caught:
        command_skeleton(bytes([0x05]))
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR
    assert ISLAND_CODES == frozenset(range(0x21, 0x42)) | frozenset(range(0x79, 0x8A))


# ---------------------------------------------------------------------------
# A translation's notation


def test_a_translations_skeleton_is_its_tokens_but_the_layout():
    notation = "{Song 2A}بب{line}{Name 00}{blank}تت\n{Wait 10}{Gil}{Close}"
    assert notation_skeleton(notation) == (
        "{Song 2A}",
        "{Name 00}",
        "{Wait 10}",
        "{Gil}",
        "{Close}",
    )
    validate_command_skeleton(("{Song 2A}", "{Name 00}", "{Wait 10}", "{Gil}", "{Close}"), notation)
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(("{Name 00}",), "بب")
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    for bad in ("{Item}بب", "{Name}بب", "{Name 0}", "{Gil 01}", "{Close}بب", "{Wait zz}"):
        with pytest.raises(ClassicRetroError) as caught:
            notation_skeleton(bad)
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE, bad


def test_message_characters_are_the_painted_forms_and_the_games_own():
    used = message_characters("بب {Name 00}، 12\n!{line}ب")
    assert BEH["INITIAL"] in used and BEH["FINAL"] in used and BEH["ISOLATED"] in used
    assert {" ", "،", "1", "2", "!"} <= used
    with pytest.raises(ClassicRetroError) as caught:
        message_characters("بب ")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
    with pytest.raises(ClassicRetroError):
        paint_text("بَ")  # a vowel mark


# ---------------------------------------------------------------------------
# Codes and tiles


def _glyph(cells: int, *ink: tuple[int, int]) -> Ff4Glyph:
    rows = [[BACKGROUND] * (CELL * cells) for _ in range(CELL_HEIGHT)]
    for x, y in ink:
        rows[y][x] = INK
    return Ff4Glyph(cells, tuple(tuple(row) for row in rows))


def _font(used: set[str]) -> Ff4Font:
    """Every form a distinct bottom; the initial and medial forms a distinct top too."""
    glyphs = {}
    for number, character in enumerate(sorted(used, key=ord)):
        if character in (" ", "1", "2", "!", ".", ":"):
            continue
        ink = [(number % CELL, TILE_ROWS + 1 + number % 6)]
        if character in (BEH["INITIAL"], BEH["MEDIAL"]):
            ink.append((number % CELL, 2))
        glyphs[character] = _glyph(2 if character == BEH["MEDIAL"] else 1, *ink)
    return Ff4Font(glyphs, 12)


def test_tiles_are_packed_as_the_font_holds_them():
    rows = [[BACKGROUND] * 8 for _ in range(8)]
    rows[0][0] = INK
    rows[1][7] = BACKGROUND
    rows[2][3] = 2
    tile = pack_tile(rows)
    assert len(tile) == 16
    assert tile[0:2] == bytes([0xFF, 0x80])  # plane 0 all set, plane 1 the first pixel
    assert tile[2:4] == bytes([0xFF, 0x00])
    assert tile[4:6] == bytes([0xEF, 0x10])  # a pixel of value 2: plane 1 only
    assert unpack_tile(tile) == tuple(tuple(row) for row in rows)
    assert pack_tile([[BACKGROUND] * 8] * 8) == BLANK_TOP


def test_a_form_sits_against_its_joining_edge_with_its_stroke_carried_on():
    stroke = {(x, 11) for x in range(4)} | {(1, 9)}
    medial = placed_glyph(stroke, joins_left=True, joins_right=True)
    assert medial.cells == 1 and medial.rows[11] == (INK,) * 8
    assert medial.rows[9] == (BACKGROUND,) * 5 + (INK, BACKGROUND, BACKGROUND)
    initial = placed_glyph(stroke, joins_left=True, joins_right=False)
    assert initial.rows[11] == (INK,) * 8 and initial.rows[9][5] == INK
    final = placed_glyph(stroke, joins_left=False, joins_right=True)
    assert final.rows[11] == (BACKGROUND,) * 4 + (INK,) * 4
    alone = placed_glyph(stroke, joins_left=False, joins_right=False)
    assert alone.rows[11] == (BACKGROUND,) * 2 + (INK,) * 4 + (BACKGROUND,) * 2
    wide = placed_glyph({(x, 11) for x in range(12)}, joins_left=True, joins_right=True)
    assert wide.cells == 2 and wide.rows[11] == (INK,) * 16
    for ink in (set(), {(0, -1)}, {(0, CELL_HEIGHT)}, {(x, 5) for x in range(17)}):
        with pytest.raises(FormDoesNotFit):
            placed_glyph(ink, joins_left=False, joins_right=False)
    comma = hand_drawn_glyph("،")
    assert comma.cells == 1 and any(INK in row for row in comma.rows)
    assert comma.tile(0, 0) == BLANK_TOP


def test_the_codes_are_the_free_tiles_and_the_games_own():
    assert len(ARABIC_CODES) == 146 and LETTER_CODES == tuple(range(0x42, 0x76))
    assert set(PAIR_CODES) == set(range(0x8A, 0xC0)) | set(range(0xCA, 0xF1)) | {0xF6}
    assert not (set(ARABIC_CODES) & set(ISLAND_CODES)) and 0xFF not in ARABIC_CODES
    used = {BEH["INITIAL"], BEH["FINAL"], " ", "1", "!", "،"}
    codes = ff4_glyph_codes(used)
    assert codes.sequence(" ") == (SPACE_CODE,) and codes.sequence("1") == (CHARACTER_CODES["1"],)
    assert codes.sequence("!") == (SIGN_CODES["!"],)
    assert codes.code("،") == ARABIC_CODES[0]
    order = glyph_characters()
    assert order.index("،") < order.index(BEH["INITIAL"])
    with pytest.raises(ClassicRetroError) as caught:
        ff4_glyph_codes({"A"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_a_tile_set_shares_halves_and_names_the_tops_from_the_high_end():
    used = {BEH["INITIAL"], BEH["MEDIAL"], BEH["FINAL"], BEH["ISOLATED"], " ", "1"}
    font = _font(used)
    tiles = tile_set(font, used)
    initial, medial = tiles.codes.sequence(BEH["INITIAL"]), tiles.codes.sequence(BEH["MEDIAL"])
    # The initial: its top then its bottom; the medial's two cells, the right one
    # first, whose top is blank, then the left one's top and bottom.
    assert len(initial) == 2 and initial[0] >= tiles.top_first > initial[1]
    assert len(medial) == 3 and medial[1] >= tiles.top_first > max(medial[0], medial[2])
    first = min(BEH.values(), key=lambda form: glyph_characters().index(form))
    assert tiles.codes.sequence(first)[-1] == ARABIC_CODES[0]
    assert tiles.top_first in PAIR_CODES
    assert all(code in PAIR_CODES for code in tiles.tiles if code >= tiles.top_first)
    assert tiles.tiles[initial[1]] == font.glyphs[BEH["INITIAL"]].tile(0, 1)
    assert tiles.tiles[initial[0]] == font.glyphs[BEH["INITIAL"]].tile(0, 0)
    assert tiles.tiles[medial[0]] == font.glyphs[BEH["MEDIAL"]].tile(1, 1)
    assert tiles.tiles[medial[1]] == font.glyphs[BEH["MEDIAL"]].tile(0, 0)
    assert tiles.tiles[medial[2]] == font.glyphs[BEH["MEDIAL"]].tile(0, 1)
    assert tiles_needed(font.glyphs) == len(tiles.tiles)
    assert tiles.codes.sequence(" ") == (SPACE_CODE,) and tiles.codes.sequence("1") == (0x81,)


def test_a_tile_set_that_passes_the_free_codes_is_refused():
    used = set(glyph_characters())
    glyphs = {}
    for number, character in enumerate(sorted(used, key=ord)):
        bits = [bit for bit in range(8) if number >> bit & 1]
        left = [(bit, TILE_ROWS) for bit in bits] + [(0, TILE_ROWS + 1)]
        right = [(CELL + bit, TILE_ROWS + 2) for bit in bits] + [(CELL, TILE_ROWS + 3)]
        glyphs[character] = _glyph(2, *left, *right)
    with pytest.raises(ClassicRetroError) as caught:
        tile_set(Ff4Font(glyphs, 12), used)
    assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED


# ---------------------------------------------------------------------------
# Encoding


def _tiles(notation: str) -> TileSet:
    used = message_characters(notation)
    return tile_set(_font(used), used)


def test_a_message_is_painted_from_the_right_in_reading_order():
    tiles = _tiles("بب")
    encoded = Ff4ArabicEncoder(tiles.codes, tiles).encode("بب")
    initial, final = tiles.codes.sequence(BEH["INITIAL"]), tiles.codes.sequence(BEH["FINAL"])
    assert encoded.data == bytes(initial + final) + bytes([LINE, END])
    assert encoded.pages == (((bytes(initial + final), 2),),) or encoded.pages[0][0].cells == 2


def test_rows_end_as_the_english_does_and_pages_fill_with_empty_rows():
    tiles = _tiles("ب")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    alone = tiles.codes.sequence(BEH["ISOLATED"])
    encoded = encoder.encode("ب{line}ب\nب{Close}")
    assert encoded.data == bytes(alone) + bytes([LINE]) + bytes(alone) + bytes(
        [LINE, BLANK, BLANK]
    ) + bytes(alone) + bytes([LINE, CLOSE])
    assert [[row.cells for row in page] for page in encoded.pages] == [[1, 1], [1]]
    blank = encoder.encode("ب{blank}ب")
    assert blank.data == bytes(alone) + bytes([LINE]) + bytes([LINE]) + bytes(alone) + bytes(
        [LINE, END]
    )
    assert [row.cells for row in blank.pages[0]] == [1, 0, 1]


def test_rows_break_before_the_word_that_would_pass_the_row():
    tiles = _tiles("ب")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    words = " ".join(["ب"] * 14)  # 14 cells and 13 spaces: 27, one past the row
    encoded = encoder.encode(words)
    assert [row.cells for row in encoded.pages[0]] == [25, 1]
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode("\n".join(["ب"] * 2) + "\n" + "{line}".join(["ب"] * 5))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    tiles = _tiles("ببب")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode("ب" * 20)  # the initial, 18 medials of two cells, the final
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert "38 cells" in str(caught.value)


def test_the_games_own_codes_are_written_reversed_for_the_hook_to_turn():
    assert compensate_islands(bytes([0x8A, 0x80, 0x81, 0x82, 0x8B])) == bytes(
        [0x8A, 0x82, 0x81, 0x80, 0x8B]
    )
    assert compensate_islands(bytes([0x80, 0x81])) == bytes([0x81, 0x80])
    tiles = _tiles("ب 12")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    codes, cells = encoder.word("12")
    assert codes == bytes([0x81, 0x82]) and cells == 2  # the hook mirrors, then turns them
    assert shown_row([(0x81, 0xFF), (0x82, 0xFF), (0xFF, 0xFF)]) == [
        (0xFF, 0xFF),
        (0x81, 0xFF),
        (0x82, 0xFF),
    ]


def test_without_the_tiles_the_codes_are_provisional_and_nothing_is_laid_out():
    encoder = Ff4ArabicEncoder(ff4_glyph_codes(message_characters("بب")))
    encoded = encoder.encode("بب")
    assert encoded.pages is None and encoded.data[-2:] == bytes([LINE, END])
    assert encoder.cells(bytes([0x8A, 0x8B])) == 2


def test_a_name_is_one_word_of_six_cells_at_most():
    tiles = _tiles("ببب")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    codes = encode_name(encoder, "name.00", "ببب")
    assert encoder.cells(codes) == 4  # the medial of the test font is two cells wide
    for text in ("", "ب ب", "{Name 00}", "بببببببب"):
        with pytest.raises(ClassicRetroError):
            encode_name(encoder, "name.00", text)
    assert NAME_CELLS == 6


# ---------------------------------------------------------------------------
# What the game shows


def test_the_decoder_model_fills_rows_and_the_hook_model_mirrors_them():
    tiles = _tiles("ب {Name 00}")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    encoded = encoder.encode("ب {Name 00}")
    rows = decoded_rows(encoded.data, tiles.top_first)
    alone = tiles.codes.sequence(BEH["ISOLATED"])
    assert len(rows) == 1 and len(rows[0]) == ROW
    assert rows[0][0] == (alone[-1], SPACE_CODE if len(alone) == 1 else alone[0])
    assert rows[0][1] == (SPACE_CODE, SPACE_CODE)
    assert rows[0][2:8] == [(-NAME, SPACE_CODE)] * NAME_CELLS
    shown = shown_row(rows[0])
    assert shown[-1][0] == alone[-1] and shown[-2] == (SPACE_CODE, SPACE_CODE)
    assert [code for code, _ in shown[-8:-2]] == [-NAME] * NAME_CELLS
    assert decoded_rows(bytes([0x02, 0x03, END]), 0xFF)[0][:4] == [(SPACE, SPACE)] * 3 + [
        (SPACE, SPACE)
    ]


def test_previews_show_the_rows_mirrored_with_their_tops(tmp_path):
    tiles = _tiles("بب {Name 00}")
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    encoded = encoder.encode("بب {Name 00}")
    image = message_preview(encoded, tiles)
    assert image.width == ROW * CELL + 2 * PREVIEW_MARGIN
    right = PREVIEW_MARGIN + ROW * CELL
    initial = tiles.codes.sequence(BEH["INITIAL"])
    top_rows = unpack_tile(tiles.tiles[initial[0]])
    bottom_rows = unpack_tile(tiles.tiles[initial[1]])
    y = PREVIEW_MARGIN
    ink_top = next((x, r) for r, row in enumerate(top_rows) for x, v in enumerate(row) if v == INK)
    ink_bottom = next(
        (x, r) for r, row in enumerate(bottom_rows) for x, v in enumerate(row) if v == INK
    )
    assert image.getpixel((right - CELL + ink_top[0], y + ink_top[1])) == PREVIEW_COLOURS[INK]
    assert (
        image.getpixel((right - CELL + ink_bottom[0], y + TILE_ROWS + ink_bottom[1]))
        == PREVIEW_COLOURS[INK]
    )
    # The name: grey blocks left of the word (two cells) and its space.
    assert image.getpixel((right - 4 * CELL + 2, y + TILE_ROWS + 2)) == PREVIEW_BLOCK
    assert image.getpixel((right - 3 * CELL + 2, y + TILE_ROWS + 2)) == PREVIEW_COLOURS[BACKGROUND]
    atlas = font_preview(tiles)
    assert atlas.width > 0 and atlas.height > 0
    with pytest.raises(ClassicRetroError):
        message_preview(EncodedMessage(encoded.data, None), tiles)


# ---------------------------------------------------------------------------
# The font


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


def test_the_font_is_drawn_at_the_largest_size_its_cells_hold(beh_font):
    used = {BEH["INITIAL"], BEH["FINAL"], " ", "!", "1", "،"}
    font = build_ff4_font(beh_font, used, sizing=set(BEH.values()))
    assert font.font_size in range(8, 13)
    assert set(font.glyphs) == {BEH["INITIAL"], BEH["FINAL"], "،"}
    initial, final = font.glyphs[BEH["INITIAL"]], font.glyphs[BEH["FINAL"]]
    # The initial joins on its left: its stroke reaches its first column; the final's
    # reaches its last.
    assert any(row[0] == INK for row in initial.rows)
    assert any(row[-1] == INK for row in final.rows)
    assert font.glyphs["،"] == hand_drawn_glyph("،")
    assert font.cells(BEH["FINAL"]) in (1, 2)
    with pytest.raises(ClassicRetroError) as caught:
        build_ff4_font(beh_font, {"A"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
    with pytest.raises(ClassicRetroError):
        font.cells("A")
