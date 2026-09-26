"""Text engine of the fourth-generation Pokémon games (Nintendo DS).

Diamond, Pearl and Platinum keep their text in message banks, the members of
a NARC (Platinum's ``/msgdata/pl_msg.narc``). A bank is:

- ``count`` and ``seed`` (16 bits each);
- ``count`` entries of a 32-bit offset (from the bank's start) and a 32-bit
  length in characters, each XORed with ``key | key << 16``, where ``key`` is
  ``seed * 765 * (index + 1)`` (16 bits);
- the strings: 16-bit characters, each XORed with a key that starts at
  ``(index + 1) * 596947`` and grows by 18749 a character (16 bits).

A string is 16-bit character codes up to ``FFFF``:

- ``0001``..``01FD`` are glyphs of the fonts: ``0121``..``012A`` the digits,
  ``012B`` the Latin capitals, ``0145`` the small letters, then accented
  letters and punctuation (``LATIN``); ``01DE`` is the space;
- ``E000`` ends a line; ``25BC`` waits for A and clears the window (a new
  page); ``25BD`` waits for A and scrolls the window up a line;
- ``FFFE`` starts a command: its type, the number of arguments, then the
  arguments. ``01xx`` inserts a string variable ``xx`` (the player's name, a
  rival's); ``0200`` shows a touch-screen icon; ``FF00`` sets a colour.
- ``F100`` starts a string packed in 9-bit codes, which this engine does not
  read.

The notation writes the Latin glyphs as text, ``E000`` as a line end (``\\n``),
``25BC`` as ``\\r`` and ``25BD`` as ``\\f`` (as pret/pokeplatinum does), a
command as ``{NAME a, b}`` (``{STRVAR_1 3, 0, 0}`` for type ``0103`` with
arguments 0 and 0, ``{YESNO 0}``, ``{CMD_XXXX a}`` for the others) and any
other glyph as ``{char XXXX}``.

A font (NFGR, in Platinum's ``/graphic/pl_font.narc``) is a 16-byte header (its
size, the width table's offset, the glyph count, the largest width and height,
the glyph's width and height in tiles), the glyphs (2 bits a pixel, 8x8 tiles
left to right and top to bottom) and a width for each glyph. Glyph ``n`` draws
character code ``n + 1``; a code past the last glyph draws ``?``. A pixel is 0
(transparent), 1 (the text colour), 2 (its shadow) or 3 (the background).

The renderer (``RenderText``) draws a glyph at a time at the printer's pen,
from the left of a line, and moves the pen by the glyph's width. A line end
takes the pen back to the line's start and down 16 pixels.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

EOS = 0xFFFF
FORMAT = 0xFFFE
NEWLINE = 0xE000
CLEAR = 0x25BC
SCROLL = 0x25BD
COMPRESSED = 0xF100
SPACE = 0x01DE
QUESTION = 0x01AC
# Line breaks and their notation (pret/pokeplatinum's).
BREAKS = {NEWLINE: "\n", CLEAR: "\r", SCROLL: "\f"}
_BREAK_CODES = {text: code for code, text in BREAKS.items()}
# Commands after FFFE.
YESNO = 0x0200
CURSOR_X = 0x0203
COLOR = 0xFF00
# String variables (``{STRVAR_1 n, ...}`` is type ``01nn``) and named commands.
_STRVARS = frozenset((0x01, 0x03, 0x04, 0x06, 0x34))
_NAMED = {
    0x0200: "YESNO",
    0x0201: "PAUSE",
    0x0202: "WAIT",
    0x0203: "CURSOR_X",
    0x0204: "CURSOR_Y",
    0x0205: "ALN_CENTER",
    0x0206: "ALN_RIGHT",
    0xFF00: "COLOR",
    0xFF01: "SIZE",
}
_BY_NAME = {name: code for code, name in _NAMED.items()}

LINE_HEIGHT = 16
KEY_START = 596947
KEY_STEP = 18749

LATIN: dict[int, str] = {
    **{0x0121 + digit: str(digit) for digit in range(10)},
    **{0x012B + letter: chr(ord("A") + letter) for letter in range(26)},
    **{0x0145 + letter: chr(ord("a") + letter) for letter in range(26)},
    # À to ÿ in Latin-1's order.
    **{0x015F + offset: chr(0xC0 + offset) for offset in range(0x40)},
    **dict(
        zip(
            range(0x019F, 0x01C6),
            "ŒœŞşªº¹²³$¡¿!?,.…·/‘’“”„《》()♂♀+-*#=&~:;",
            strict=True,
        )
    ),
    SPACE: " ",
}
_CODES = {character: code for code, character in LATIN.items()}

_NOTATION_CHAR = re.compile(r"\{char ([0-9A-Fa-f]{4})\}")
_NOTATION_COMMAND = re.compile(r"\{([A-Z][A-Z0-9_]*)((?: \d+(?:, \d+)*)?)\}")


class PokemonGen4EngineAdapter(EngineAdapter):
    id = "nds.pokemon-gen4"
    display_name = "Pokémon Generation IV text engine"
    platform_ids = ("nds",)


# ---------------------------------------------------------------------------
# Message banks


@dataclass(frozen=True, slots=True)
class MessageBank:
    """A bank's seed and its strings, each a tuple of character codes (with its ``FFFF``)."""

    seed: int
    strings: tuple[tuple[int, ...], ...]

    @classmethod
    def read(cls, data: bytes) -> MessageBank:
        if len(data) < 4:
            raise ClassicRetroError(ErrorCode.CONTAINER_REBUILD_FAILED, "Not a message bank")
        count, seed = struct.unpack_from("<HH", data)
        strings = []
        for index in range(count):
            if 4 + 8 * index + 8 > len(data):
                raise ClassicRetroError(ErrorCode.CONTAINER_REBUILD_FAILED, "Bank table cut short")
            offset, length = struct.unpack_from("<II", data, 4 + 8 * index)
            key = _entry_key(seed, index)
            offset ^= key
            length ^= key
            if offset + 2 * length > len(data):
                raise ClassicRetroError(
                    ErrorCode.CONTAINER_REBUILD_FAILED, f"String {index} is outside its bank"
                )
            codes = struct.unpack_from(f"<{length}H", data, offset)
            strings.append(tuple(_crypt(codes, index)))
        return cls(seed, tuple(strings))

    def build(self) -> bytes:
        """The bank's bytes: the table, then every string in order, as the game's tool writes."""
        table = bytearray(struct.pack("<HH", len(self.strings), self.seed))
        body = bytearray()
        offset = 4 + 8 * len(self.strings)
        for index, codes in enumerate(self.strings):
            key = _entry_key(self.seed, index)
            table += struct.pack("<II", (offset + len(body)) ^ key, len(codes) ^ key)
            body += struct.pack(f"<{len(codes)}H", *_crypt(codes, index))
        return bytes(table + body)

    def replaced(self, strings: dict[int, tuple[int, ...]]) -> MessageBank:
        """The bank with the strings of ``strings`` (by index) replaced."""
        for index, codes in strings.items():
            if not 0 <= index < len(self.strings):
                raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No string {index}")
            if not codes or codes[-1] != EOS or EOS in codes[:-1]:
                raise ClassicRetroError(
                    ErrorCode.MISSING_TERMINATOR, f"String {index} must end at its only FFFF"
                )
        return MessageBank(
            self.seed,
            tuple(strings.get(index, codes) for index, codes in enumerate(self.strings)),
        )


def _entry_key(seed: int, index: int) -> int:
    key = seed * 765 * (index + 1) & 0xFFFF
    return key | key << 16


def _crypt(codes: Iterable[int], index: int) -> Iterable[int]:
    key = (index + 1) * KEY_START & 0xFFFF
    for code in codes:
        yield code ^ key
        key = key + KEY_STEP & 0xFFFF


# ---------------------------------------------------------------------------
# Text: characters, commands and the notation


@dataclass(frozen=True, slots=True)
class Gen4Command:
    """A line break (``code`` is ``E000``, ``25BC`` or ``25BD``) or a command after ``FFFE``."""

    code: int
    args: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.code in BREAKS:
            if self.args:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, "A line break takes no arguments"
                )
        elif not 0 <= self.code <= 0xFFFF or any(not 0 <= arg <= 0xFFFF for arg in self.args):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Bad command {self.code:#x} {self.args}"
            )

    @property
    def is_break(self) -> bool:
        return self.code in BREAKS

    @property
    def is_newline(self) -> bool:
        return self.code == NEWLINE

    @property
    def codes(self) -> tuple[int, ...]:
        if self.is_break:
            return (self.code,)
        return (FORMAT, self.code, len(self.args), *self.args)

    @property
    def notation(self) -> str:
        if self.is_break:
            return BREAKS[self.code]
        high, low = self.code >> 8, self.code & 0xFF
        if high in _STRVARS:
            name, args = f"STRVAR_{high:X}", (low, *self.args)
        else:
            name, args = _NAMED.get(self.code, f"CMD_{self.code:04X}"), self.args
        return "{" + name + ("" if not args else " " + ", ".join(map(str, args))) + "}"

    @property
    def is_string_variable(self) -> bool:
        return not self.is_break and self.code >> 8 in _STRVARS


Piece = str | Gen4Command


def split_text(codes: Sequence[int]) -> tuple[Piece, ...]:
    """Text runs and commands of a string, up to (without) its ``FFFF``."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0

    def command(piece: Gen4Command) -> None:
        if run:
            pieces.append("".join(run))
            run.clear()
        pieces.append(piece)

    while index < len(codes):
        code = codes[index]
        if code == EOS:
            break
        if code == COMPRESSED:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, "Packed (F100) strings are not read here"
            )
        if code in BREAKS:
            command(Gen4Command(code))
            index += 1
        elif code == FORMAT:
            if index + 2 >= len(codes) or index + 3 + codes[index + 2] > len(codes):
                raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, "A command is cut short")
            count = codes[index + 2]
            command(Gen4Command(codes[index + 1], tuple(codes[index + 3 : index + 3 + count])))
            index += 3 + count
        else:
            run.append(LATIN.get(code) or f"{{char {code:04X}}}")
            index += 1
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def text_notation(codes: Sequence[int]) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_text(codes)
    )


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation as text runs and commands (``{char XXXX}`` stays inside the runs)."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character in _BREAK_CODES:
            command = Gen4Command(_BREAK_CODES[character])
            index += 1
        elif character == "{":
            char = _NOTATION_CHAR.match(text, index)
            if char is not None:
                run.append(char.group(0))
                index = char.end()
                continue
            match = _NOTATION_COMMAND.match(text, index)
            if match is None:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command at {text[index:]!r}"
                )
            command = _command(match.group(1), match.group(2))
            index = match.end()
        elif character == "}":
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "Unmatched '}'")
        else:
            run.append(character)
            index += 1
            continue
        if run:
            pieces.append("".join(run))
            run.clear()
        pieces.append(command)
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def _command(name: str, arguments: str) -> Gen4Command:
    args = tuple(int(value) for value in arguments.replace(",", " ").split())
    if name.startswith("STRVAR_"):
        try:
            high = int(name.removeprefix("STRVAR_"), 16)
        except ValueError:
            high = -1
        if high not in _STRVARS or not args or not 0 <= args[0] <= 0xFF:
            raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Bad {{{name}}}")
        return Gen4Command(high << 8 | args[0], args[1:])
    if name.startswith("CMD_"):
        try:
            return Gen4Command(int(name.removeprefix("CMD_"), 16), args)
        except ValueError:
            pass
    if name in _BY_NAME:
        return Gen4Command(_BY_NAME[name], args)
    raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command {{{name}}}")


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Commands in order, without the line ends that follow text (which may move).

    A line end still follows text across a command inside a line (a name, a colour).
    """
    skeleton: list[str] = []
    after_text = False
    for piece in pieces:
        if isinstance(piece, str):
            after_text = after_text or bool(piece)
            continue
        if not (piece.is_newline and after_text):
            skeleton.append(piece.notation)
        if piece.is_break:
            after_text = False
    return tuple(skeleton)


def command_skeleton(codes: Sequence[int]) -> tuple[str, ...]:
    return notation_skeleton(split_text(codes))


def encode_text(text: str) -> tuple[int, ...]:
    """Codes of a text run in the game's glyphs (``LATIN`` and ``{char XXXX}``)."""
    codes: list[int] = []
    index = 0
    while index < len(text):
        char = _NOTATION_CHAR.match(text, index)
        if char is not None:
            code = int(char.group(1), 16)
            if code in BREAKS or code >= COMPRESSED:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{char.group(0)} is not a glyph"
                )
            codes.append(code)
            index = char.end()
            continue
        code = _CODES.get(text[index])
        if code is None:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"The game's font has no {text[index]!r}"
            )
        codes.append(code)
        index += 1
    return tuple(codes)


def pieces_codes(pieces: Iterable[Piece]) -> tuple[int, ...]:
    """A string's codes, ``FFFF`` included."""
    codes: list[int] = []
    for piece in pieces:
        codes.extend(encode_text(piece) if isinstance(piece, str) else piece.codes)
    return (*codes, EOS)


# ---------------------------------------------------------------------------
# Fonts (NFGR)

Pixels = tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class Gen4Font:
    """A font: its header's sizes, the 2bpp glyphs and a width for each glyph."""

    max_width: int
    max_height: int
    tiles_wide: int
    tiles_high: int
    glyphs: bytes
    widths: bytes

    @classmethod
    def read(cls, data: bytes) -> Gen4Font:
        if len(data) < 16:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Not a font")
        size, widths_at, count, max_width, max_height, wide, high = struct.unpack_from(
            "<IIIBBBB", data
        )
        glyph_bytes = 16 * wide * high
        if (
            size != 16
            or not 1 <= wide <= 2
            or not 1 <= high <= 2
            or widths_at != size + count * glyph_bytes
            or widths_at + count > len(data)
        ):
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Not an NFGR font")
        return cls(
            max_width,
            max_height,
            wide,
            high,
            bytes(data[size:widths_at]),
            bytes(data[widths_at : widths_at + count]),
        )

    @property
    def glyph_bytes(self) -> int:
        return 16 * self.tiles_wide * self.tiles_high

    @property
    def count(self) -> int:
        return len(self.widths)

    def build(self) -> bytes:
        header = struct.pack(
            "<IIIBBBB",
            16,
            16 + len(self.glyphs),
            self.count,
            self.max_width,
            self.max_height,
            self.tiles_wide,
            self.tiles_high,
        )
        return header + self.glyphs + self.widths

    def width(self, code: int) -> int:
        """The width the game gives character ``code``, as ``FontManager`` does."""
        index = code - 1 if 0 < code <= self.count else QUESTION - 1
        return self.widths[index]

    def glyph(self, code: int) -> Pixels:
        start = (code - 1) * self.glyph_bytes
        return unpack_2bpp(
            self.glyphs[start : start + self.glyph_bytes], self.tiles_wide, self.tiles_high
        )

    def with_glyphs(self, glyphs: Sequence[tuple[Pixels, int]]) -> Gen4Font:
        """The font with ``glyphs`` (pixels, width) after its own: codes from ``count + 1``."""
        data = b"".join(pack_2bpp(pixels, self.tiles_wide, self.tiles_high) for pixels, _ in glyphs)
        widths = bytes(width for _, width in glyphs)
        if any(not 0 <= width <= 8 * self.tiles_wide for width in widths):
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A glyph is wider than its cell")
        return Gen4Font(
            self.max_width,
            self.max_height,
            self.tiles_wide,
            self.tiles_high,
            self.glyphs + data,
            self.widths + widths,
        )


def unpack_2bpp(data: bytes, tiles_wide: int, tiles_high: int) -> Pixels:
    """Pixels of 2bpp tiles: each row a little-endian word, pixel 0 in its top bits."""
    rows = [[0] * (8 * tiles_wide) for _ in range(8 * tiles_high)]
    for tile in range(tiles_wide * tiles_high):
        left, top = 8 * (tile % tiles_wide), 8 * (tile // tiles_wide)
        for y in range(8):
            (word,) = struct.unpack_from("<H", data, 16 * tile + 2 * y)
            for x in range(8):
                rows[top + y][left + x] = word >> (14 - 2 * x) & 3
    return tuple(tuple(row) for row in rows)


def pack_2bpp(pixels: Pixels, tiles_wide: int, tiles_high: int) -> bytes:
    if len(pixels) != 8 * tiles_high or any(len(row) != 8 * tiles_wide for row in pixels):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A glyph is not its cell's size")
    data = bytearray()
    for tile in range(tiles_wide * tiles_high):
        left, top = 8 * (tile % tiles_wide), 8 * (tile // tiles_wide)
        for y in range(8):
            word = 0
            for x in range(8):
                value = pixels[top + y][left + x]
                if not 0 <= value <= 3:
                    raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A pixel is 0 to 3")
                word |= value << (14 - 2 * x)
            data += struct.pack("<H", word)
    return bytes(data)


# ---------------------------------------------------------------------------
# Layout: the lines of a string as the printer draws them


@dataclass(frozen=True, slots=True)
class Gen4Place:
    """A glyph at ``pen`` on its line, ``width`` wide; a name has no single code."""

    code: int | None
    pen: int
    width: int

    @property
    def end(self) -> int:
        return self.pen + self.width


@dataclass(frozen=True, slots=True)
class Gen4Line:
    """A line: its page, its row in the window, its glyphs; ``icon`` when it shows the icon.

    ``scrolled`` is set on a line that starts after a scroll (``25BD``): the
    rows above it moved up a row before it was drawn.
    """

    page: int
    row: int
    places: tuple[Gen4Place, ...]
    icon: bool = False
    scrolled: bool = False

    @property
    def width(self) -> int:
        return max((place.end for place in self.places), default=0)


def lay_out(
    codes: Sequence[int],
    width: Callable[[int], int],
    *,
    rows: int,
    name_width: int,
) -> tuple[Gen4Line, ...]:
    """The lines of a string's codes in a window of ``rows`` rows, from the left.

    ``E000`` moves to the next row; ``25BD`` scrolls, so it may only end the
    window's last row, and the next line takes that row again; ``25BC`` starts
    a new page at the first row. A string variable takes ``name_width``, the
    widest name it can hold. The touch-screen icon (``{YESNO}``) marks the
    lines of the page it is drawn on.
    """
    lines: list[Gen4Line] = []
    page = row = pen = 0
    places: list[Gen4Place] = []
    icon_pages: set[int] = set()
    scrolled = False

    def close() -> None:
        lines.append(Gen4Line(page, row, tuple(places), scrolled=scrolled))
        places.clear()

    index = 0
    while index < len(codes) and codes[index] != EOS:
        code = codes[index]
        if code == FORMAT:
            if index + 2 >= len(codes):
                raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, "A command is cut short")
            kind = codes[index + 1]
            index += 3 + codes[index + 2]
            if kind >> 8 in _STRVARS:
                places.append(Gen4Place(None, pen, name_width))
                pen += name_width
            elif kind == YESNO:
                icon_pages.add(page)
            continue
        index += 1
        if code == NEWLINE:
            close()
            row, pen, scrolled = row + 1, 0, False
            if row >= rows:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Page {page + 1} needs row {row + 1}; the window has {rows} "
                    "(end the last row with \\f to scroll)",
                )
        elif code == SCROLL:
            if row != rows - 1:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"\\f scrolls from the window's last row, not row {row + 1}",
                )
            close()
            pen, scrolled = 0, True
        elif code == CLEAR:
            close()
            page, row, pen, scrolled = page + 1, 0, 0, False
        else:
            glyph_width = width(code)
            places.append(Gen4Place(code, pen, glyph_width))
            pen += glyph_width
    close()
    return tuple(
        Gen4Line(line.page, line.row, line.places, line.page in icon_pages, line.scrolled)
        for line in lines
    )
