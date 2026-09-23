from __future__ import annotations

import heapq
import struct
from collections import Counter

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fire_emblem import (
    CLEAR,
    END,
    LINE_FEED,
    LOAD_FACE,
    PACE,
    RAW_POINTER_FLAG,
    ROM_BASE,
    WAIT_KEY,
    FireEmblemFont,
    FireEmblemGlyph,
    FireEmblemHuffmanModel,
    FireEmblemTextBank,
    command_length,
    command_skeleton,
    message_notation,
    parse_command,
    read_message,
    skeleton_notation,
    split_notation,
)

TABLE = 0x100
MESSAGES = (
    b"\x09\x10\x51\x01\x09Your Majesty.\x1f\x03\x01Go!\x03\x00",
    b"The continent.\x03\x02\x01\x80\x04Renais.\x03\x00",
    b"\x00",
)


def _huffman(messages: tuple[bytes, ...], base: int) -> tuple[bytes, int, list[bytes]]:
    """Node array (leaves hold one byte), root address, and the encoded messages."""
    weights = Counter(byte for message in messages for byte in message)
    heap: list[tuple[int, int, object]] = [(count, byte, byte) for byte, count in weights.items()]
    heapq.heapify(heap)
    order = 256
    while len(heap) > 1:
        a, b = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, (a[0] + b[0], order, (a[2], b[2])))
        order += 1
    nodes: list[int] = []
    codes: dict[int, str] = {}

    def place(tree: object, prefix: str) -> int:
        index = len(nodes)
        nodes.append(0)
        if isinstance(tree, int):
            nodes[index] = 0x80000000 | tree
            codes[tree] = prefix
        else:
            left = place(tree[0], prefix + "0")
            right = place(tree[1], prefix + "1")
            nodes[index] = left | right << 16
        return index

    root_tree = heap[0][2]
    # The decoder never treats the root as a leaf: give lone symbols a sibling.
    if isinstance(root_tree, int):
        root_tree = (root_tree, root_tree)
    root = place(root_tree, "")
    encoded = []
    for message in messages:
        bits = "".join(codes[byte] for byte in message)
        bits += "0" * (-len(bits) % 8)
        encoded.append(bytes(int(bits[i : i + 8][::-1], 2) for i in range(0, len(bits), 8)))
    # The game points at the root, stored last; move it there.
    table = nodes[:]
    if root != len(table) - 1:
        table.append(table[root])
        root = len(table) - 1
    data = b"".join(struct.pack("<I", node) for node in table)
    return data, base + 4 * root, encoded


def _image() -> bytes:
    rom = bytearray(0x2000)
    nodes, root, encoded = _huffman(MESSAGES, ROM_BASE + TABLE)
    rom[TABLE : TABLE + len(nodes)] = nodes
    root_pointer = TABLE + len(nodes)
    struct.pack_into("<I", rom, root_pointer, root)
    table = root_pointer + 4
    cursor = 0x1000
    for index, data in enumerate(encoded):
        struct.pack_into("<I", rom, table + 4 * index, ROM_BASE + cursor)
        rom[cursor : cursor + len(data)] = data
        cursor += len(data)
    return bytes(rom)


def _bank(rom: bytes) -> FireEmblemTextBank:
    root_pointer = TABLE + len(_huffman(MESSAGES, ROM_BASE + TABLE)[0])
    return FireEmblemTextBank.parse(rom, root_pointer + 4, len(MESSAGES), TABLE, root_pointer)


def test_huffman_bank_decodes_every_message():
    rom = _image()
    bank = _bank(rom)

    assert bank.messages == MESSAGES
    assert all(not pointer & RAW_POINTER_FLAG for pointer in bank.pointers)


def test_raw_pointers_are_copied_up_to_the_terminator():
    rom = bytearray(_image())
    rom[0x1800:0x1805] = b"\x1eab\x00Z"
    model = FireEmblemHuffmanModel.parse(bytes(rom), TABLE, TABLE + len(_huffman(MESSAGES, 0)[0]))

    assert read_message(bytes(rom), ROM_BASE + 0x1800 | RAW_POINTER_FLAG, model) == b"\x1eab\x00"
    with pytest.raises(ClassicRetroError) as caught:
        read_message(bytes(rom), 0x0A000000, model)
    assert caught.value.code is ErrorCode.REFERENCE_OUT_OF_BOUNDS


def test_huffman_root_must_lie_in_its_table():
    rom = bytearray(_image())
    root_pointer = TABLE + len(_huffman(MESSAGES, 0)[0])
    struct.pack_into("<I", rom, root_pointer, ROM_BASE + TABLE - 4)
    with pytest.raises(ClassicRetroError) as caught:
        FireEmblemHuffmanModel.parse(bytes(rom), TABLE, root_pointer)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_command_lengths_follow_the_talk_interpreter():
    data = bytes((LOAD_FACE, 0x51, 0x01, 0x80, 0x04, 0x81, 0x40, 0x81, 0x41, PACE, 0x41, END))

    assert command_length(data, 0) == 3
    assert command_length(data, 3) == 2
    assert command_length(data, 5) == 2  # tab
    assert command_length(data, 7) == 0  # 0x81 without 0x40 is a glyph
    assert command_length(data, 9) == 0  # [.] is a zero-width glyph
    assert command_length(data, 10) == 0
    assert command_length(data, 11) == 1


def test_notation_round_trips_and_names_commands():
    for message in MESSAGES:
        pieces = split_notation(message_notation(message))
        data = b"".join(p if isinstance(p, bytes) else p.encode("ascii") for p in pieces)
        assert data == message

    assert message_notation(MESSAGES[0]).startswith(
        "[OpenMidLeft][LoadFace 51 01][OpenMidLeft]Your"
    )
    assert "[.][A][LF]" in message_notation(MESSAGES[0])
    assert message_notation(b"\x93Hi\x94\x00") == "[0x93]Hi[0x94][X]"
    assert parse_command("0x80 0x24") == b"\x80\x24"
    assert parse_command("BreakTalk") == b"\x80\x04"
    with pytest.raises(ClassicRetroError) as caught:
        parse_command("Nope")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_skeleton_drops_text_line_feeds_and_pacing_but_keeps_cr_lf():
    skeleton = command_skeleton(MESSAGES[0])
    assert skeleton_notation(skeleton) == "[OpenMidLeft][LoadFace 51 01][OpenMidLeft][A][A][X]"

    narration = command_skeleton(MESSAGES[1])
    assert narration == (
        bytes((WAIT_KEY,)),
        bytes((CLEAR,)),
        bytes((LINE_FEED,)),
        b"\x80\x04",
        bytes((WAIT_KEY,)),
        bytes((END,)),
    )
    # A line feed that does not follow [CR] directly is layout only.
    assert command_skeleton(b"a\x02b\x01c\x00") == (b"\x02", b"\x00")


def test_cut_short_commands_are_reported():
    with pytest.raises(ClassicRetroError) as caught:
        command_skeleton(bytes((LOAD_FACE, 0x51)))
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_glyph_tables_parse_width_and_rows():
    rom = bytearray(0x800)
    glyph = FireEmblemGlyph(6, tuple(range(16)))
    rom[0x400 : 0x400 + 72] = glyph.encode()
    struct.pack_into("<I", rom, 4 * 0x41, ROM_BASE + 0x400)

    font = FireEmblemFont.parse(bytes(rom), 0)
    assert set(font.glyphs) == {0x41}
    assert font.glyphs[0x41] == glyph
    assert glyph.pixel(1, 1) == 0 and glyph.pixel(0, 1) == 1

    struct.pack_into("<I", rom, 4 * 0x42, ROM_BASE + 0x7FF)
    with pytest.raises(ClassicRetroError) as caught:
        FireEmblemFont.parse(bytes(rom), 0)
    assert caught.value.code is ErrorCode.REFERENCE_OUT_OF_BOUNDS


def test_sacred_stones_is_registered():
    registry = build_registry()

    assert "gba.fire-emblem" in registry.engines
    game = registry.games["fire-emblem-sacred-stones-usa"]
    assert game.engine_id == "gba.fire-emblem"
    assert game.game_code == "BE8E"
    assert game.revisions[0].size == 16_777_216
