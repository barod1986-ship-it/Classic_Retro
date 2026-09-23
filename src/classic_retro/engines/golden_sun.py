"""Golden Sun (GBA) text engine.

Facts below come from the USA/Europe ROM (game code ``AGSE``) and the
symbolized disassembly at https://github.com/gsret/goldensun, which assembles
to this exact image:

- All 10722 strings share one context Huffman model. The code of a character
  is chosen by the tree of the *previous* character (``0`` before the first
  one); a string ends with the code ``0``. Tree leaves hold 12-bit values, so
  codes ``0x100..0xFFF`` are possible, and trees of the context ``c`` live in
  block ``c >> 8`` of the tree pointer table (``{trees, offsets}`` per block).
- A tree is its leaf array, written backwards in 12-bit pairs, followed by its
  topology in pre-order (``0`` inner node, ``1`` leaf), least significant bit
  first. ``offsets[c & 0xFF]`` (u16) points from ``trees`` to the topology.
- Strings are grouped by 256. For each group the string pointer table holds
  the compressed data and one length byte per string (``0xFF`` continues the
  length in the next byte); every string starts on a byte boundary.
- Codes below ``0x20`` are commands (newline ``0x03``, page ``0x01``, end
  ``0x02``...); some take the next code as an argument, stored plus one.
- The dialogue font has one 32-byte glyph per code ``0x20..0x8F``: a u16
  advance, then 14 rows of 1bpp pixels (u16, most significant bit leftmost).
"""

from __future__ import annotations

import heapq
import struct
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000
STRINGS_PER_BLOCK = 256
CONTEXTS_PER_BLOCK = 256
MAX_CODE = 0xFFF
NO_TREE = 0x8000

END = 0x00
KEY_PAGE = 0x01
KEY_END = 0x02
NEWLINE = 0x03
PAUSE_LONG = 0x04
PAUSE = 0x05
PAUSE_LONGER = 0x06
COLOR_RESET = 0x07
COLOR = 0x08
EFFECT = 0x09
EFFECT_ALT = 0x0A
WINDOW_MODE = 0x0F
LEADER_NAME = 0x10
CHARACTER_NAME = 0x11
PARTY_NAME = 0x12
CLASS_NAME = 0x13
ITEM_NAME = 0x14
PSYNERGY_NAME = 0x15
NUMBER = 0x16
DJINN_NAME = 0x17
DASH = 0x18
PLURAL = 0x19
BUTTON = 0x1A
POSSESSIVE = 0x1B
ICON = 0x1D
QUESTION = 0x1E
FIRST_GLYPH = 0x20
SPACE = 0x20

# Commands followed by one argument code (stored as value + 1).
COMMANDS_WITH_ARGUMENT = frozenset(
    {COLOR, EFFECT, EFFECT_ALT, WINDOW_MODE, CHARACTER_NAME, PARTY_NAME, CLASS_NAME}
    | {ITEM_NAME, BUTTON, ICON}
)
# Commands that end a message.
TERMINATORS = frozenset({KEY_END, QUESTION})
# Commands that only lay out the page; a translation may add or drop them.
LAYOUT_COMMANDS = frozenset({NEWLINE})
# Commands that insert text decided at runtime (names, items, numbers, English grammar).
RUNTIME_TEXT_COMMANDS = frozenset(
    {LEADER_NAME, CHARACTER_NAME, PARTY_NAME, CLASS_NAME, ITEM_NAME, PSYNERGY_NAME}
    | {NUMBER, DJINN_NAME, PLURAL, POSSESSIVE, BUTTON, ICON}
)

COMMAND_NAMES = {
    END: "END",
    KEY_PAGE: "KEY_PAGE",
    KEY_END: "KEY_END",
    NEWLINE: "NEWLINE",
    PAUSE_LONG: "PAUSE_LONG",
    PAUSE: "PAUSE",
    PAUSE_LONGER: "PAUSE_LONGER",
    COLOR_RESET: "COLOR_RESET",
    COLOR: "COLOR",
    EFFECT: "EFFECT",
    EFFECT_ALT: "EFFECT_ALT",
    WINDOW_MODE: "WINDOW_MODE",
    LEADER_NAME: "LEADER_NAME",
    CHARACTER_NAME: "CHARACTER_NAME",
    PARTY_NAME: "PARTY_NAME",
    CLASS_NAME: "CLASS_NAME",
    ITEM_NAME: "ITEM_NAME",
    PSYNERGY_NAME: "PSYNERGY_NAME",
    NUMBER: "NUMBER",
    DJINN_NAME: "DJINN_NAME",
    DASH: "DASH",
    PLURAL: "PLURAL",
    BUTTON: "BUTTON",
    POSSESSIVE: "POSSESSIVE",
    ICON: "ICON",
    QUESTION: "QUESTION",
}

FONT_FIRST = 0x20
FONT_GLYPHS = 0x70
FONT_GLYPH_BYTES = 32
FONT_ROWS = 14


class GoldenSunEngineAdapter(EngineAdapter):
    id = "gba.golden-sun"
    display_name = "Golden Sun context-Huffman text engine"
    platform_ids = ("gba",)


def command_notation(code: int) -> str:
    name = COMMAND_NAMES.get(code)
    return f"{{{code:02X}}}" if name is None else f"{{{code:02X}:{name}}}"


def command_skeleton(codes: Sequence[int]) -> tuple[int, ...]:
    """Commands in execution order with their arguments; glyphs and layout commands dropped."""
    skeleton: list[int] = []
    expect_argument = False
    for code in codes:
        if expect_argument:
            skeleton.append(code)
            expect_argument = False
            continue
        if code >= FIRST_GLYPH or code in LAYOUT_COMMANDS:
            continue
        skeleton.append(code)
        expect_argument = code in COMMANDS_WITH_ARGUMENT
    return tuple(skeleton)


def skeleton_notation(skeleton: Sequence[int]) -> str:
    """Commands as ``{11:CHARACTER_NAME}`` with their arguments as plain numbers."""
    parts: list[str] = []
    expect_argument = False
    for code in skeleton:
        if expect_argument:
            parts.append(f"{code:02X}")
            expect_argument = False
            continue
        parts.append(command_notation(code))
        expect_argument = code in COMMANDS_WITH_ARGUMENT
    return " ".join(parts)


def script_notation(codes: Iterable[int]) -> str:
    """The disassembly's script notation: printable ASCII, ``\\xNN`` for other codes."""
    parts = []
    for code in codes:
        if 0x20 <= code < 0x7F and code != 0x5C:
            parts.append(chr(code))
        elif code <= 0xFF:
            parts.append(f"\\x{code:02x}")
        else:
            parts.append(f"\\u{code:03x}")
    return "".join(parts)


class _BitReader:
    def __init__(self, data: bytes, position: int) -> None:
        self.data = data
        self.position = position
        self.bits = 0
        self.available = 0

    def next(self) -> int:
        if self.available == 0:
            if self.position >= len(self.data):
                raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "Golden Sun bit stream ended")
            self.bits = self.data[self.position]
            self.position += 1
            self.available = 8
        bit = self.bits & 1
        self.bits >>= 1
        self.available -= 1
        return bit


class _BitWriter:
    def __init__(self) -> None:
        self.output = bytearray()
        self.bits = 0
        self.pending = 0

    def append(self, bit: int) -> None:
        self.bits |= bit << self.pending
        self.pending += 1
        if self.pending == 8:
            self.flush()

    def flush(self) -> None:
        if self.pending:
            self.output.append(self.bits)
            self.bits = 0
            self.pending = 0


def _leaf_value(data: bytes, tree: int, leaf: int) -> int:
    position = tree - (leaf + (leaf >> 1))
    high, low = data[position - 1], data[position - 2]
    if leaf & 1:
        return (high & 0x0F) << 8 | low
    return high << 4 | low >> 4


_Tree = int | tuple["_Tree", "_Tree"]


def _read_tree(data: bytes, tree: int) -> _Tree:
    """The tree at ``tree`` as nested ``(left, right)`` pairs with leaf codes."""
    topology = _BitReader(data, tree)
    leaves = 0

    def node(depth: int) -> _Tree:
        nonlocal leaves
        if depth > MAX_CODE:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "Golden Sun tree is too deep")
        if topology.next():
            value = _leaf_value(data, tree, leaves)
            leaves += 1
            return value
        left = node(depth + 1)
        return left, node(depth + 1)

    return node(0)


@dataclass(slots=True)
class HuffmanModel:
    """Tree positions (absolute data offsets) per context code."""

    data: bytes
    trees: dict[int, int]
    _parsed: dict[int, _Tree] = field(default_factory=dict)

    def tree(self, previous: int) -> _Tree:
        parsed = self._parsed.get(previous)
        if parsed is None:
            position = self.trees.get(previous)
            if position is None:
                raise ClassicRetroError(
                    ErrorCode.UNKNOWN_TEXT_BYTE,
                    f"Golden Sun has no Huffman tree after {previous:#x}",
                )
            parsed = self._parsed[previous] = _read_tree(self.data, position)
        return parsed

    def decode_code(self, text: _BitReader, previous: int) -> int:
        node = self.tree(previous)
        while not isinstance(node, int):
            node = node[text.next()]
        return node


def _pointer(data: bytes, offset: int) -> int:
    (value,) = struct.unpack_from("<I", data, offset)
    if not ROM_BASE <= value < ROM_BASE + len(data):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"Golden Sun pointer {value:#x} at {offset:#x} is outside"
        )
    return value - ROM_BASE


def read_huffman_model(rom: bytes, table_offset: int, blocks: int = 1) -> HuffmanModel:
    trees: dict[int, int] = {}
    for block in range(blocks):
        base = _pointer(rom, table_offset + 8 * block)
        offsets = _pointer(rom, table_offset + 8 * block + 4)
        for index in range(CONTEXTS_PER_BLOCK):
            (offset,) = struct.unpack_from("<H", rom, offsets + 2 * index)
            if offset != NO_TREE:
                trees[block * CONTEXTS_PER_BLOCK + index] = base + offset
    return HuffmanModel(rom, trees)


def decode_string(model: HuffmanModel, data: bytes, position: int) -> tuple[int, ...]:
    """Codes of one string up to (not including) its terminating ``0``."""
    text = _BitReader(data, position)
    codes: list[int] = []
    previous = 0
    while True:
        code = model.decode_code(text, previous)
        if code == END:
            return tuple(codes)
        codes.append(code)
        previous = code
        if len(codes) > 0x1000:
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "Golden Sun string never ends")


@dataclass(frozen=True, slots=True)
class GoldenSunTextBank:
    """Every string of the game as a tuple of codes (without the final ``0``)."""

    strings: tuple[tuple[int, ...], ...]

    @classmethod
    def parse(
        cls, rom: bytes, tree_table: int, string_table: int, count: int, tree_blocks: int = 1
    ) -> GoldenSunTextBank:
        model = read_huffman_model(rom, tree_table, tree_blocks)
        strings: list[tuple[int, ...]] = []
        for block in range((count + STRINGS_PER_BLOCK - 1) // STRINGS_PER_BLOCK):
            position = _pointer(rom, string_table + 8 * block)
            lengths = _pointer(rom, string_table + 8 * block + 4)
            for _ in range(min(STRINGS_PER_BLOCK, count - len(strings))):
                strings.append(decode_string(model, rom, position))
                while rom[lengths] == 0xFF:
                    position += 0xFF
                    lengths += 1
                position += rom[lengths]
                lengths += 1
        return cls(tuple(strings))

    def replace(self, replacements: dict[int, Sequence[int]]) -> GoldenSunTextBank:
        strings = list(self.strings)
        for index, codes in replacements.items():
            if not 0 <= index < len(strings):
                raise ClassicRetroError(
                    ErrorCode.INVALID_REFERENCE, f"Golden Sun has no string {index}"
                )
            strings[index] = tuple(codes)
        return GoldenSunTextBank(tuple(strings))

    def build(self, address: int) -> BuiltTextBank:
        return build_text_bank(self.strings, address)


@dataclass(frozen=True, slots=True)
class BuiltTextBank:
    """A compressed text bank laid out at ``address``."""

    address: int
    data: bytes
    tree_table: int
    string_table: int
    tree_blocks: int


@dataclass(slots=True)
class _Node:
    weight: int
    order: int
    code: int | None = None
    left: _Node | None = None
    right: _Node | None = None


def _huffman_tree(frequencies: Counter[int]) -> _Node:
    heap: list[tuple[int, int, _Node]] = []
    for order, (code, weight) in enumerate(sorted(frequencies.items())):
        heap.append((weight, order, _Node(weight, order, code)))
    heapq.heapify(heap)
    order = len(heap)
    while len(heap) > 1:
        weight_a, _, first = heapq.heappop(heap)
        weight_b, _, second = heapq.heappop(heap)
        node = _Node(weight_a + weight_b, order, left=first, right=second)
        heapq.heappush(heap, (node.weight, order, node))
        order += 1
    return heap[0][2]


def _serialize_tree(root: _Node) -> tuple[bytes, bytes, dict[int, tuple[int, ...]]]:
    """Leaf array (to be placed before the tree position), topology and code bits."""
    topology = _BitWriter()
    leaves: list[int] = []
    codes: dict[int, tuple[int, ...]] = {}

    def visit(node: _Node, path: tuple[int, ...]) -> None:
        if node.code is not None:
            topology.append(1)
            leaves.append(node.code)
            codes[node.code] = path
            return
        topology.append(0)
        assert node.left is not None and node.right is not None
        visit(node.left, (*path, 0))
        visit(node.right, (*path, 1))

    visit(root, ())
    topology.flush()
    size = len(leaves) + (len(leaves) >> 1) + (len(leaves) & 1)
    array = bytearray(size)
    for leaf, code in enumerate(leaves):
        if not 0 <= code <= MAX_CODE:
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"Golden Sun code {code:#x}")
        position = size - (leaf + (leaf >> 1))
        if leaf & 1:
            array[position - 1] |= code >> 8
            array[position - 2] = code & 0xFF
        else:
            array[position - 1] = code >> 4
            array[position - 2] |= (code & 0x0F) << 4
    return bytes(array), bytes(topology.output), codes


def _transitions(strings: Iterable[Sequence[int]]) -> dict[int, Counter[int]]:
    transitions: dict[int, Counter[int]] = defaultdict(Counter)
    for string in strings:
        if any(code == END for code in string):
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, "Golden Sun strings cannot contain the end code"
            )
        previous = 0
        for code in (*string, END):
            if not 0 <= code <= MAX_CODE:
                raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"Golden Sun code {code:#x}")
            transitions[previous][code] += 1
            previous = code
    return transitions


def _append_trees(
    output: bytearray,
    address: int,
    transitions: dict[int, Counter[int]],
    table: int,
    tree_blocks: int,
) -> dict[int, dict[int, tuple[int, ...]]]:
    """Append each block's u16 offsets and trees; fill the tree pointer table at ``table``."""
    code_bits: dict[int, dict[int, tuple[int, ...]]] = {}
    for block in range(tree_blocks):
        offsets_position = len(output)
        output += bytes(2 * CONTEXTS_PER_BLOCK)
        trees_base = len(output)
        for index in range(CONTEXTS_PER_BLOCK):
            context = block * CONTEXTS_PER_BLOCK + index
            if context not in transitions:
                struct.pack_into("<H", output, offsets_position + 2 * index, NO_TREE)
                continue
            leaves, topology, bits = _serialize_tree(_huffman_tree(transitions[context]))
            output += leaves
            offset = len(output) - trees_base
            if offset >= NO_TREE:
                raise ClassicRetroError(
                    ErrorCode.RELOCATION_OVERFLOW,
                    "Golden Sun Huffman trees exceed 32 KiB per block",
                )
            struct.pack_into("<H", output, offsets_position + 2 * index, offset)
            output += topology
            code_bits[context] = bits
        struct.pack_into(
            "<II", output, table + 8 * block, address + trees_base, address + offsets_position
        )
        if len(output) % 2:
            output.append(0)
    return code_bits


def _compress(string: Sequence[int], code_bits: dict[int, dict[int, tuple[int, ...]]]) -> bytes:
    writer = _BitWriter()
    previous = 0
    for code in (*string, END):
        for bit in code_bits[previous][code]:
            writer.append(bit)
        previous = code
    writer.flush()
    return bytes(writer.output)


def build_text_bank(strings: Sequence[Sequence[int]], address: int) -> BuiltTextBank:
    """Compress ``strings`` with fresh trees into one relocatable block at ``address``.

    Layout: tree pointer table, per block its u16 offsets and trees, then the
    string groups with their length bytes, then the string pointer table.
    """
    transitions = _transitions(strings)
    tree_blocks = max(transitions) // CONTEXTS_PER_BLOCK + 1
    output = bytearray(8 * tree_blocks)
    code_bits = _append_trees(output, address, transitions, 0, tree_blocks)

    groups: list[tuple[int, int]] = []
    for first in range(0, len(strings), STRINGS_PER_BLOCK):
        data_position = len(output)
        lengths = bytearray()
        for string in strings[first : first + STRINGS_PER_BLOCK]:
            compressed = _compress(string, code_bits)
            output += compressed
            length = len(compressed)
            while length >= 0xFF:
                lengths.append(0xFF)
                length -= 0xFF
            lengths.append(length)
        lengths_position = len(output)
        output += lengths
        groups.append((address + data_position, address + lengths_position))

    while len(output) % 4:
        output.append(0)
    string_table = address + len(output)
    for data_address, lengths_address in groups:
        output += struct.pack("<II", data_address, lengths_address)
    output += bytes(8)
    return BuiltTextBank(
        address=address,
        data=bytes(output),
        tree_table=address,
        string_table=string_table,
        tree_blocks=tree_blocks,
    )


STORE_TREE_BLOCKS = 2
STORE_INDEX_OFFSET = 8 * STORE_TREE_BLOCKS
STORE_INDEX_END = 0xFFFF


@dataclass(frozen=True, slots=True)
class BuiltStringStore:
    """A few strings with their own trees, found by string index.

    Layout at ``address``: a tree pointer table with two entries (contexts
    ``0x000..0x1FF``), then the index (``u16 string, u16 0, u32 data``, sorted,
    ended by string ``0xFFFF``), then the trees, then each string's data on a
    word boundary.
    """

    address: int
    data: bytes
    entries: dict[int, int]

    @property
    def tree_table(self) -> int:
        return self.address

    @property
    def index(self) -> int:
        return self.address + STORE_INDEX_OFFSET


def build_string_store(strings: dict[int, Sequence[int]], address: int) -> BuiltStringStore:
    if address % 4:
        raise ClassicRetroError(ErrorCode.REFERENCE_ALIGNMENT_ERROR, "String store is unaligned")
    order = sorted(strings)
    if any(not 0 <= index < STORE_INDEX_END for index in order):
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "String index out of range")
    transitions = _transitions(strings[index] for index in order)
    if max(transitions) >= STORE_TREE_BLOCKS * CONTEXTS_PER_BLOCK:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A Golden Sun string store holds codes below 0x200"
        )
    output = bytearray(STORE_INDEX_OFFSET + 8 * (len(order) + 1))
    code_bits = _append_trees(output, address, transitions, 0, STORE_TREE_BLOCKS)
    entries: dict[int, int] = {}
    for position, index in enumerate(order):
        while len(output) % 4:
            output.append(0)
        entries[index] = address + len(output)
        struct.pack_into(
            "<HHI", output, STORE_INDEX_OFFSET + 8 * position, index, 0, entries[index]
        )
        output += _compress(strings[index], code_bits)
    struct.pack_into("<HHI", output, STORE_INDEX_OFFSET + 8 * len(order), STORE_INDEX_END, 0, 0)
    while len(output) % 4:
        output.append(0)
    return BuiltStringStore(address=address, data=bytes(output), entries=entries)


def read_string_store(image: bytes, address: int) -> dict[int, tuple[int, ...]]:
    """Decode every string of a store at ``address`` (an absolute ROM address)."""
    offset = address - ROM_BASE
    model = read_huffman_model(image, offset, STORE_TREE_BLOCKS)
    strings: dict[int, tuple[int, ...]] = {}
    entry = offset + STORE_INDEX_OFFSET
    while True:
        index, _, data = struct.unpack_from("<HHI", image, entry)
        if index == STORE_INDEX_END:
            return strings
        strings[index] = decode_string(model, image, data - ROM_BASE)
        entry += 8


@dataclass(frozen=True, slots=True)
class GoldenSunGlyph:
    advance: int
    rows: tuple[int, ...]

    def pixel(self, x: int, y: int) -> bool:
        return bool(self.rows[y] & 0x8000 >> x)


@dataclass(frozen=True, slots=True)
class GoldenSunFont:
    """The dialogue font: glyphs for codes ``0x20..0x8F``."""

    glyphs: tuple[GoldenSunGlyph, ...]

    @classmethod
    def parse(cls, rom: bytes, offset: int) -> GoldenSunFont:
        glyphs = []
        for index in range(FONT_GLYPHS):
            position = offset + index * FONT_GLYPH_BYTES
            advance = struct.unpack_from("<H", rom, position)[0]
            rows = struct.unpack_from(f"<{FONT_ROWS}H", rom, position + 2)
            glyphs.append(GoldenSunGlyph(advance, rows))
        return cls(tuple(glyphs))

    def glyph(self, code: int) -> GoldenSunGlyph:
        if not FONT_FIRST <= code < FONT_FIRST + FONT_GLYPHS:
            raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"Golden Sun has no glyph {code:#x}")
        return self.glyphs[code - FONT_FIRST]
