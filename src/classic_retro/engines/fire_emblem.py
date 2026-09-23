"""Fire Emblem (GBA) text engine, as used by *The Sacred Stones* (USA, ``BE8E``).

Facts below come from the ROM and the fireemblem8u decompilation
(https://github.com/FireEmblemUniverse/fireemblem8u), which builds this exact
image:

- ``gMsgTable`` holds one pointer per message. The ARM routine
  ``DecodeString`` (copied to IWRAM) walks a node array from the root that
  ``gMsgHuffmanTableRoot`` points to, reading bits least significant first.
  A node is a u32: with bit 31 clear it holds two u16 child indices into the
  node array (bit 0, then bit 1); with bit 31 set it is a leaf holding one or
  two bytes, low byte first. A leaf whose low byte is zero ends the message.
- Bytes below ``0x20`` are commands: ``[X]`` ends, ``[LF]`` (0x01) moves to
  the next line, ``[CR]`` (0x02) clears the box, ``[A]`` (0x03) waits for a
  key, 0x08..0x0F select a speaker slot, ``[LoadFace]`` (0x10) takes two
  bytes, and so on. ``0x80`` starts a two-byte extended command and
  ``0x81 0x40`` is a 6-pixel tab. Every other byte is a glyph: in English
  mode the active font draws ``glyphs[byte]`` from a 256-entry table whose
  entries are ``{next, sjis byte, width, pad, 16 rows of 16 2-bit pixels}``.
- ``[.]`` (0x1F) is a zero-width empty glyph: it paces the typewriter by one
  step, and trailing ones are cut when a message is decoded.

Notation: commands are written in brackets, ``[LoadFace 51 01]`` for a face
load, ``[0x80 0x24]`` or ``[0x1E]`` for codes without a name; everything else
is text.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000

END = 0x00
LINE_FEED = 0x01
CLEAR = 0x02
WAIT_KEY = 0x03
LOAD_FACE = 0x10
YES = 0x18
NO = 0x19
BUY_SELL = 0x1A
SHOP_CONTINUE = 0x1B
PACE = 0x1F
FIRST_GLYPH = 0x20
EXTENDED = 0x80
TAB_PREFIX = 0x81
TAB = 0x40

COMMAND_NAMES: dict[int, str] = {
    0x00: "X",
    0x01: "LF",
    0x02: "CR",
    0x03: "A",
    0x04: "Pause8",
    0x05: "Pause16",
    0x06: "Pause32",
    0x07: "Pause64",
    0x08: "OpenFarLeft",
    0x09: "OpenMidLeft",
    0x0A: "OpenLeft",
    0x0B: "OpenRight",
    0x0C: "OpenMidRight",
    0x0D: "OpenFarRight",
    0x0E: "OpenFarFarLeft",
    0x0F: "OpenFarFarRight",
    0x10: "LoadFace",
    0x11: "ClearFace",
    0x12: "NormalPrint",
    0x13: "FastPrint",
    0x14: "CloseSpeechFast",
    0x15: "CloseSpeechSlow",
    0x16: "ToggleMouthMove",
    0x17: "ToggleSmile",
    0x18: "Yes",
    0x19: "No",
    0x1A: "BuySell",
    0x1B: "ShopContinue",
    0x1C: "SendToBack",
    0x1D: "BringToFront",
    0x1F: ".",
}
EXTENDED_NAMES: dict[int, str] = {
    0x04: "BreakTalk",
    0x05: "G",
    0x0A: "MoveFarLeft",
    0x0B: "MoveMidLeft",
    0x0C: "MoveLeft",
    0x0D: "MoveRight",
    0x0E: "MoveMidRight",
    0x0F: "MoveFarRight",
    0x10: "MoveFarFarLeft",
    0x11: "MoveFarFarRight",
    0x16: "EnableBlinking",
    0x18: "DelayBlinking",
    0x19: "PauseBlinking",
    0x1B: "DisableBlinking",
    0x1C: "OpenEyes",
    0x1D: "CloseEyes",
    0x1E: "HalfCloseEyes",
    0x1F: "Wink",
    0x20: "Tact",
    0x21: "ToggleRed",
    0x22: "Item",
    0x23: "SetName",
    0x25: "ToggleColorInvert",
}
# Extended commands that insert text at runtime: a number, the user string,
# the tactician's name and item/unit names.
RUNTIME_TEXT_COMMANDS = frozenset({0x05, 0x06, 0x20, 0x22, 0x23})
CHOICE_COMMANDS = frozenset({YES, NO, BUY_SELL, SHOP_CONTINUE})
# Layout only: dropped from command skeletons.
LAYOUT_COMMANDS = frozenset({LINE_FEED, PACE})

_NAME_CODES = {name: bytes((code,)) for code, name in COMMAND_NAMES.items()}
_NAME_CODES.update({name: bytes((EXTENDED, code)) for code, name in EXTENDED_NAMES.items()})
_NAME_CODES["TAB"] = bytes((TAB_PREFIX, TAB))


class FireEmblemEngineAdapter(EngineAdapter):
    id = "gba.fire-emblem"
    display_name = "Fire Emblem GBA Huffman text engine"
    platform_ids = ("gba",)


def command_length(data: bytes | Sequence[int], index: int) -> int:
    """Bytes taken by the command at ``index``; 0 when it is a glyph."""
    code = data[index]
    if code == LOAD_FACE:
        return 3
    if code == EXTENDED:
        return 2
    if code == TAB_PREFIX and index + 1 < len(data) and data[index + 1] == TAB:
        return 2
    if code < FIRST_GLYPH and code != PACE:
        return 1
    return 0


def iter_commands(data: bytes) -> Iterable[tuple[int, bytes | None]]:
    """``(index, command bytes)`` for commands, ``(index, None)`` for glyph bytes."""
    index = 0
    while index < len(data):
        length = command_length(data, index)
        if length == 0:
            yield index, None
            index += 1
            continue
        command = bytes(data[index : index + length])
        if len(command) != length:
            raise ClassicRetroError(
                ErrorCode.TOKEN_ORDER_VIOLATION,
                f"Fire Emblem command at byte {index} is cut short",
            )
        yield index, command
        index += length


def command_notation(command: bytes) -> str:
    if command[0] == LOAD_FACE:
        return f"[LoadFace {command[1]:02X} {command[2]:02X}]"
    if command[0] == EXTENDED:
        name = EXTENDED_NAMES.get(command[1])
        return f"[{name}]" if name else f"[0x80 0x{command[1]:02X}]"
    if command == bytes((TAB_PREFIX, TAB)):
        return "[TAB]"
    name = COMMAND_NAMES.get(command[0])
    return f"[{name}]" if name else f"[0x{command[0]:02X}]"


def message_notation(data: bytes) -> str:
    """A message in bracket notation: ASCII glyphs as text, ``[.]``, other glyphs as ``[0xNN]``."""
    output: list[str] = []
    for index, command in iter_commands(data):
        if command is not None:
            output.append(command_notation(command))
        elif data[index] == PACE:
            output.append("[.]")
        elif data[index] < 0x7F:
            output.append(chr(data[index]))
        else:
            output.append(f"[0x{data[index]:02X}]")
    return "".join(output)


_BRACKET = re.compile(r"\[([^\[\]]+)\]")


def parse_command(name: str) -> bytes:
    """Bytes of one bracketed command (without the brackets)."""
    if name in _NAME_CODES:
        return _NAME_CODES[name]
    face = re.fullmatch(r"LoadFace ([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2})", name)
    if face:
        return bytes((LOAD_FACE, int(face.group(1), 16), int(face.group(2), 16)))
    raw = re.fullmatch(r"(0x[0-9A-Fa-f]{2})( 0x[0-9A-Fa-f]{2})*", name)
    if raw:
        return bytes(int(value, 16) for value in name.split())
    raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command [{name}]")


def split_notation(text: str) -> list[str | bytes]:
    """Text pieces (str) and command bytes, in order."""
    pieces: list[str | bytes] = []
    position = 0
    for match in _BRACKET.finditer(text):
        if match.start() > position:
            pieces.append(text[position : match.start()])
        pieces.append(parse_command(match.group(1)))
        position = match.end()
    if position < len(text):
        pieces.append(text[position:])
    return pieces


def command_skeleton(data: bytes) -> tuple[bytes, ...]:
    """Commands in execution order with their arguments; glyphs, ``[LF]`` and ``[.]`` dropped.

    An ``[LF]`` right after ``[CR]`` stays: the world map's narration box
    clears with ``[CR]`` and skips the byte that follows it.
    """
    skeleton: list[bytes] = []
    previous: tuple[int, bytes] | None = None
    for index, command in iter_commands(data):
        if command is None:
            previous = None
            continue
        after_clear = previous is not None and previous[1] == bytes((CLEAR,))
        if command[0] not in LAYOUT_COMMANDS or (command[0] == LINE_FEED and after_clear):
            skeleton.append(command)
        previous = (index, command)
    return tuple(skeleton)


def skeleton_notation(skeleton: Sequence[bytes]) -> str:
    return "".join(command_notation(command) for command in skeleton)


@dataclass(frozen=True, slots=True)
class FireEmblemHuffmanModel:
    """The node array (u32 each) and the index of the root node."""

    nodes: tuple[int, ...]
    root: int

    @classmethod
    def parse(
        cls, rom: bytes, table_offset: int, root_pointer_offset: int
    ) -> FireEmblemHuffmanModel:
        (root_address,) = struct.unpack_from("<I", rom, root_pointer_offset)
        root_offset = root_address - ROM_BASE
        if root_offset < table_offset or (root_offset - table_offset) % 4:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"Huffman root {root_address:#x} is outside its table"
            )
        count = (root_offset - table_offset) // 4 + 1
        nodes = struct.unpack_from(f"<{count}I", rom, table_offset)
        return cls(nodes=tuple(nodes), root=count - 1)

    def decode(self, rom: bytes, offset: int, *, limit: int = 0x4000) -> bytes:
        output = bytearray()
        node = self.root
        position = offset
        while True:
            if position >= len(rom):
                raise ClassicRetroError(
                    ErrorCode.RESOURCE_OUT_OF_BOUNDS, "Huffman message runs past the image"
                )
            byte = rom[position]
            position += 1
            for bit in range(8):
                value = self.nodes[node]
                child = value >> 16 if byte >> bit & 1 else value & 0xFFFF
                if child >= len(self.nodes):
                    raise ClassicRetroError(
                        ErrorCode.INVALID_REFERENCE, f"Huffman child {child} is outside the table"
                    )
                leaf = self.nodes[child]
                if not leaf & 0x80000000:
                    node = child
                    continue
                if leaf & 0xFF00:
                    output += bytes((leaf & 0xFF, leaf >> 8 & 0xFF))
                else:
                    output.append(leaf & 0xFF)
                    if not leaf & 0xFF:
                        return bytes(output)
                if len(output) > limit:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_OVERFLOW, "Huffman message exceeds the message buffer"
                    )
                node = self.root


# A pointer with bit 31 set addresses an uncompressed message (the convention
# of the Arabic overlay; the game's own table never sets it).
RAW_POINTER_FLAG = 0x80000000


@dataclass(frozen=True, slots=True)
class FireEmblemTextBank:
    pointers: tuple[int, ...]
    messages: tuple[bytes, ...]

    @classmethod
    def parse(
        cls,
        rom: bytes,
        table_offset: int,
        count: int,
        huffman_offset: int,
        root_pointer_offset: int,
    ) -> FireEmblemTextBank:
        model = FireEmblemHuffmanModel.parse(rom, huffman_offset, root_pointer_offset)
        pointers = struct.unpack_from(f"<{count}I", rom, table_offset)
        messages = tuple(read_message(rom, pointer, model) for pointer in pointers)
        return cls(pointers=tuple(pointers), messages=messages)


def read_message(rom: bytes, pointer: int, model: FireEmblemHuffmanModel) -> bytes:
    """Decode one message; raw (bit 31) pointers are copied up to their terminator."""
    if pointer & RAW_POINTER_FLAG:
        offset = (pointer & ~RAW_POINTER_FLAG) - ROM_BASE
        end = rom.find(b"\x00", offset)
        if offset < 0 or end < 0:
            raise ClassicRetroError(
                ErrorCode.RESOURCE_OUT_OF_BOUNDS, f"Raw message {pointer:#x} has no terminator"
            )
        return bytes(rom[offset : end + 1])
    offset = pointer - ROM_BASE
    if not 0 <= offset < len(rom):
        raise ClassicRetroError(
            ErrorCode.REFERENCE_OUT_OF_BOUNDS, f"Message pointer {pointer:#x} is outside the image"
        )
    return model.decode(rom, offset)


GLYPH_BYTES = 72
GLYPH_ROWS = 16


@dataclass(frozen=True, slots=True)
class FireEmblemGlyph:
    """``width`` and 16 rows of 16 two-bit pixels (pixel x at bits 2x..2x+1)."""

    width: int
    rows: tuple[int, ...]

    def pixel(self, x: int, y: int) -> int:
        return self.rows[y] >> 2 * x & 3

    def encode(self) -> bytes:
        return struct.pack("<IBBH16I", 0, 0, self.width, 0, *self.rows)


@dataclass(frozen=True, slots=True)
class FireEmblemFont:
    """An English-mode glyph table: one pointer per byte value."""

    glyphs: dict[int, FireEmblemGlyph]

    @classmethod
    def parse(cls, rom: bytes, table_offset: int) -> FireEmblemFont:
        glyphs: dict[int, FireEmblemGlyph] = {}
        for code, pointer in enumerate(struct.unpack_from("<256I", rom, table_offset)):
            if not pointer:
                continue
            offset = pointer - ROM_BASE
            if not 0 <= offset <= len(rom) - GLYPH_BYTES:
                raise ClassicRetroError(
                    ErrorCode.REFERENCE_OUT_OF_BOUNDS, f"Glyph pointer {pointer:#x} is invalid"
                )
            _, _, width, _ = struct.unpack_from("<IBBH", rom, offset)
            rows = struct.unpack_from("<16I", rom, offset + 8)
            glyphs[code] = FireEmblemGlyph(width, tuple(rows))
        return cls(glyphs=glyphs)
