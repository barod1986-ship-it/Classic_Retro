from __future__ import annotations

import random
import struct

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.golden_sun import (
    CHARACTER_NAME,
    COLOR,
    DASH,
    FONT_FIRST,
    FONT_GLYPH_BYTES,
    FONT_GLYPHS,
    KEY_END,
    NEWLINE,
    QUESTION,
    ROM_BASE,
    STORE_INDEX_END,
    STORE_INDEX_OFFSET,
    STORE_TREE_BLOCKS,
    STRINGS_PER_BLOCK,
    GoldenSunFont,
    GoldenSunTextBank,
    build_string_store,
    build_text_bank,
    command_skeleton,
    read_huffman_model,
    read_string_store,
    script_notation,
    skeleton_notation,
)


def _parse(built, count: int) -> GoldenSunTextBank:
    image = bytes(built.address - ROM_BASE) + built.data
    return GoldenSunTextBank.parse(
        image,
        built.tree_table - ROM_BASE,
        built.string_table - ROM_BASE,
        count,
        built.tree_blocks,
    )


def _text(value: str) -> tuple[int, ...]:
    return tuple(value.encode("ascii"))


def test_text_bank_round_trips_through_fresh_trees():
    strings = [
        _text("Hello!") + (KEY_END,),
        (CHARACTER_NAME, 0x01) + _text(", wake up!") + (KEY_END,),
        _text("Attack"),
        (),
        _text("Line one") + (NEWLINE,) + _text("line two?") + (QUESTION,),
    ] * 70
    built = build_text_bank(strings, 0x08100000)

    assert built.tree_blocks == 1
    assert len(strings) > STRINGS_PER_BLOCK
    assert _parse(built, len(strings)).strings == tuple(tuple(string) for string in strings)


def test_twelve_bit_codes_use_a_second_tree_block():
    strings = [(0x0B, 0x100, 0x1FE, 0x20, 0x185, KEY_END), _text("plain")]
    built = build_text_bank(strings, 0x08200000)

    assert built.tree_blocks == 2
    table = built.data[:16]
    trees_1, offsets_1 = struct.unpack_from("<II", table, 8)
    assert built.address < trees_1 < built.address + len(built.data)
    assert built.address < offsets_1 < built.address + len(built.data)
    assert _parse(built, 2).strings == tuple(tuple(string) for string in strings)


def test_long_strings_continue_their_length_byte():
    generator = random.Random(7)
    long = tuple(generator.randrange(0x20, 0x80) for _ in range(700)) + (KEY_END,)
    built = build_text_bank([long, _text("after")], 0x08100000)

    bank = _parse(built, 2)
    assert bank.strings == (long, _text("after"))
    lengths = struct.unpack_from("<I", built.data, built.string_table - built.address + 4)[0]
    assert built.data[lengths - built.address] == 0xFF


def test_single_symbol_contexts_cost_no_bits():
    built = build_text_bank([_text("a")] * 3, 0x08100000)
    model = read_huffman_model(
        bytes(built.address - ROM_BASE) + built.data, built.tree_table - ROM_BASE
    )
    # "a" always follows the start and the end always follows "a": both trees are one leaf.
    assert model.tree(0) == ord("a")
    assert model.tree(ord("a")) == 0
    _, lengths = struct.unpack_from("<II", built.data, built.string_table - built.address)
    assert built.data[lengths - built.address : lengths - built.address + 3] == bytes(3)


def test_tree_layout_matches_the_documented_format():
    # Context 0 emits "a" or "b"; each tree is its leaves backwards, then its topology.
    built = build_text_bank([_text("a"), _text("b")], 0x08100000)
    image = bytes(built.address - ROM_BASE) + built.data
    trees, offsets = struct.unpack_from("<II", built.data, 0)
    (offset,) = struct.unpack_from("<H", image, offsets - ROM_BASE)
    tree = trees - ROM_BASE + offset

    # Topology 0 (inner), 1, 1 in the lowest bits; leaves 12-bit, leaf 0 nearest the tree.
    assert image[tree] & 0b111 == 0b110
    leaf_0 = image[tree - 1] << 4 | image[tree - 2] >> 4
    leaf_1 = (image[tree - 2] & 0x0F) << 8 | image[tree - 3]
    assert {leaf_0, leaf_1} == {ord("a"), ord("b")}


def test_string_store_holds_a_few_strings_with_their_own_trees():
    strings = {
        3670: (0x0B, CHARACTER_NAME, 0x01, 0x21, 0x20, 0x100, 0x1FE, KEY_END),
        3666: (0x0B, 0x185, 0x20, 0x100, KEY_END),
        12: (0x0B, 0x130, QUESTION),
    }
    store = build_string_store(strings, 0x08810000)
    image = bytes(store.address - ROM_BASE) + store.data

    assert store.tree_table == store.address
    assert store.index == store.address + STORE_INDEX_OFFSET
    entries = [
        struct.unpack_from("<HHI", store.data, STORE_INDEX_OFFSET + 8 * position)
        for position in range(len(strings) + 1)
    ]
    assert [entry[0] for entry in entries] == [12, 3666, 3670, STORE_INDEX_END]
    assert all(entry[2] % 4 == 0 for entry in entries[:-1])
    assert {index: address for index, _, address in entries[:-1]} == store.entries
    for block in range(STORE_TREE_BLOCKS):
        trees, offsets = struct.unpack_from("<II", store.data, 8 * block)
        assert store.address < trees and store.address < offsets and offsets % 2 == 0
    assert read_string_store(image, store.address) == strings


def test_string_store_refuses_codes_beyond_two_tree_blocks():
    with pytest.raises(ClassicRetroError) as caught:
        build_string_store({1: (0x200,)}, 0x08810000)
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT

    with pytest.raises(ClassicRetroError) as caught:
        build_string_store({1: (0x41,)}, 0x08810002)
    assert caught.value.code is ErrorCode.REFERENCE_ALIGNMENT_ERROR


def test_strings_cannot_hold_the_end_code_or_oversized_codes():
    with pytest.raises(ClassicRetroError) as caught:
        build_text_bank([(0x41, 0x00, 0x42)], 0x08100000)
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT

    with pytest.raises(ClassicRetroError) as caught:
        build_text_bank([(0x1000,)], 0x08100000)
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_replace_keeps_the_other_strings():
    bank = GoldenSunTextBank((_text("one"), _text("two")))
    assert bank.replace({1: (0x0B, 0x100)}).strings == (_text("one"), (0x0B, 0x100))
    with pytest.raises(ClassicRetroError):
        bank.replace({2: ()})


def test_skeleton_keeps_commands_and_arguments_only():
    codes = (CHARACTER_NAME, 0x01) + _text("Hi") + (NEWLINE, COLOR, 0x41, DASH, KEY_END)

    assert command_skeleton(codes) == (CHARACTER_NAME, 0x01, COLOR, 0x41, DASH, KEY_END)
    assert skeleton_notation(command_skeleton(codes)) == (
        "{11:CHARACTER_NAME} 01 {08:COLOR} 41 {18:DASH} {02:KEY_END}"
    )
    assert script_notation(codes) == "\\x11\\x01Hi\\x03\\x08A\\x18\\x02"


def test_font_parses_advances_and_msb_first_rows():
    data = bytearray(FONT_GLYPHS * FONT_GLYPH_BYTES)
    glyph = (ord("I") - FONT_FIRST) * FONT_GLYPH_BYTES
    struct.pack_into("<H", data, glyph, 4)
    struct.pack_into("<H", data, glyph + 2 + 2 * 3, 0b0110 << 12)
    font = GoldenSunFont.parse(bytes(data), 0)

    assert font.glyph(ord("I")).advance == 4
    assert font.glyph(ord("I")).pixel(1, 3) and font.glyph(ord("I")).pixel(2, 3)
    assert not font.glyph(ord("I")).pixel(0, 3)
    with pytest.raises(ClassicRetroError):
        font.glyph(0x90)


def test_registry_knows_the_game_and_its_engine():
    registry = build_registry()
    game = registry.games["golden-sun-usa-europe"]

    assert game.engine_id == "gba.golden-sun"
    assert game.engine_id in registry.engines
    assert game.game_code == "AGSE"
    assert game.revisions[0].size == 8_388_608
