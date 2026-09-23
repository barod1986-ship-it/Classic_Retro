"""Final Fantasy VI Advance (GBA) text engine.

Facts below come from the USA ROM (game code ``BZ6E``) and were checked by
disassembling its event text renderer (``0x0815115C``) and tracing it in an
emulator:

- Dialogue lives in a ``TEXT`` bank: a zero word, the magic ``TEXT``, a word
  ``(message_count << 8) | languages``, the end offset, then one u32 offset
  per message and language, all relative to the bank start. A message ends
  where the next one starts.
- Messages are a byte stream of *codes* in a UTF-8-like form: a byte below
  ``0x80`` is one code, lead bytes ``0x80..0xDF`` take one continuation byte
  (11 bits) and ``0xE0..0xEF`` take two (16 bits).
- Codes ``0x000..0x10C`` are glyph indices in the ``FONT`` resource; larger
  codes are commands (newline ``0x10E``, end ``0x10F``, ...). Unknown commands
  are skipped by the renderer, which is what makes new codes safe to add.
- A ``FONT`` resource is a zero word, the magic ``FONT``, height, a flag byte,
  the glyph count, a 128-entry ASCII-to-glyph table and one u32 offset per
  glyph. A glyph is its advance, its row size in bytes, then ``height`` rows of
  2-bit pixels (1 = ink, 2 = shadow), least significant pixel first.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

TEXT_MAGIC = b"TEXT"
FONT_MAGIC = b"FONT"
FONT_ASCII_ENTRIES = 128
FONT_HEADER_SIZE = 12 + 2 * FONT_ASCII_ENTRIES
FONT_NO_GLYPH = 0xFFFF
MAX_GLYPH_ROW_BYTES = 4

LAST_GLYPH = 0x10C
NEWLINE = 0x10E
END = 0x10F
PORTRAIT_FIRST = 0x110
PORTRAIT_LAST = 0x126
CHARACTER_NAME_FIRST = 0x127
CHARACTER_NAME_LAST = 0x134
WAIT_SECOND = 0x135
TIMED_CLOSE = 0x136
CLOSE = 0x137
KEY_PAGE = 0x138
CHOICE = 0x139
PAUSE = 0x13A
NUMBER = 0x13B
PARTY_NAME = 0x13C
ITEM_NAME = 0x13D
PAGE = 0x13E
CENTER = 0x140
NARRATION = 0x142
TAB = 0x143
VALUE_BASE = 0x144
SYMBOL_FIRST = 0x244
SYMBOL_LAST = 0x260

# Commands that only lay out the current page; a translation may add or drop them.
LAYOUT_COMMANDS = frozenset({NEWLINE, CENTER})
# Commands whose next code is an argument (a VALUE_BASE + n duration).
COMMANDS_WITH_ARGUMENT = frozenset({TIMED_CLOSE, PAUSE})
# Commands that insert text decided at runtime (names, numbers, items).
RUNTIME_TEXT_COMMANDS = frozenset(
    {*range(CHARACTER_NAME_FIRST, CHARACTER_NAME_LAST + 1), NUMBER, PARTY_NAME, ITEM_NAME}
    | set(range(SYMBOL_FIRST, SYMBOL_LAST + 1))
)

COMMAND_NAMES = {
    NEWLINE: "NEWLINE",
    END: "END",
    WAIT_SECOND: "WAIT_SECOND",
    TIMED_CLOSE: "TIMED_CLOSE",
    CLOSE: "CLOSE",
    KEY_PAGE: "KEY_PAGE",
    CHOICE: "CHOICE",
    PAUSE: "PAUSE",
    NUMBER: "NUMBER",
    PARTY_NAME: "PARTY_NAME",
    ITEM_NAME: "ITEM_NAME",
    PAGE: "PAGE",
    CENTER: "CENTER",
    NARRATION: "NARRATION",
    TAB: "TAB",
}


class Ff6aEngineAdapter(EngineAdapter):
    id = "gba.ff6a"
    display_name = "Final Fantasy VI Advance text engine"
    platform_ids = ("gba",)


def encode_code(value: int) -> bytes:
    """Encode one code the way the renderer's reader (0x081509B8) decodes it."""
    if not 0 <= value <= 0xFFFF:
        raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"FF6A code out of range: {value:#x}")
    if value < 0x80:
        return bytes((value,))
    if value < 0x800:
        return bytes((0xC0 | value >> 6, 0x80 | value & 0x3F))
    return bytes((0xE0 | value >> 12, 0x80 | value >> 6 & 0x3F, 0x80 | value & 0x3F))


def encode_codes(values: Iterable[int]) -> bytes:
    return b"".join(encode_code(value) for value in values)


def decode_codes(data: bytes) -> tuple[int, ...]:
    """Decode a message byte stream; fails on bytes the reader cannot consume."""
    codes: list[int] = []
    position = 0
    while position < len(data):
        lead = data[position]
        if lead < 0x80:
            codes.append(lead)
            position += 1
        elif lead <= 0xDF:
            if position + 2 > len(data):
                raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, "Truncated FF6A code")
            codes.append((lead & 0x1F) << 6 | data[position + 1] & 0x3F)
            position += 2
        elif lead <= 0xEF:
            if position + 3 > len(data):
                raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, "Truncated FF6A code")
            codes.append(
                (lead & 0x0F) << 12 | (data[position + 1] & 0x3F) << 6 | data[position + 2] & 0x3F
            )
            position += 3
        else:
            raise ClassicRetroError(
                ErrorCode.UNKNOWN_TEXT_BYTE, f"FF6A reader has no length for lead byte {lead:#04x}"
            )
    return tuple(codes)


def split_message(data: bytes) -> tuple[tuple[int, ...], bytes]:
    """Codes up to and including the first END, and the unread bytes after it."""
    position = 0
    codes: list[int] = []
    while position < len(data):
        lead = data[position]
        size = 1 if lead < 0x80 else 2 if lead <= 0xDF else 3
        code = decode_codes(data[position : position + size])[0]
        codes.append(code)
        position += size
        if code == END:
            return tuple(codes), data[position:]
    raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "FF6A message has no END command")


def command_skeleton(codes: Sequence[int]) -> tuple[int, ...]:
    """Commands in execution order with their arguments; glyphs and layout commands dropped."""
    skeleton: list[int] = []
    expect_argument = False
    for code in codes:
        if expect_argument:
            skeleton.append(code)
            expect_argument = False
            continue
        if code <= LAST_GLYPH or code in LAYOUT_COMMANDS:
            continue
        skeleton.append(code)
        expect_argument = code in COMMANDS_WITH_ARGUMENT
    return tuple(skeleton)


def command_notation(code: int) -> str:
    name = COMMAND_NAMES.get(code)
    return f"{{{code:03X}}}" if name is None else f"{{{code:03X}:{name}}}"


@dataclass(frozen=True, slots=True)
class Ff6aTextBank:
    """A ``TEXT`` resource: raw message bytes for every (message, language)."""

    languages: int
    messages: tuple[bytes, ...]
    leading_word: int = 0

    @property
    def message_count(self) -> int:
        return len(self.messages) // self.languages

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> Ff6aTextBank:
        if len(data) < offset + 16 or data[offset + 4 : offset + 8] != TEXT_MAGIC:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "No FF6A TEXT bank at offset")
        leading, _, packed, end = struct.unpack_from("<I4sII", data, offset)
        languages = packed & 0xFF
        entries = (packed >> 8) * languages
        if languages == 0 or entries == 0:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "Empty FF6A TEXT bank")
        table_end = 16 + 4 * entries
        if offset + max(end, table_end) > len(data):
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "FF6A TEXT bank exceeds data")
        starts = struct.unpack_from(f"<{entries}I", data, offset + 16)
        bounds = (*starts, end)
        messages = []
        for start, stop in zip(bounds, bounds[1:], strict=False):
            if not table_end <= start <= stop <= end:
                raise ClassicRetroError(
                    ErrorCode.INVALID_REFERENCE, "FF6A TEXT offsets are not ordered"
                )
            messages.append(bytes(data[offset + start : offset + stop]))
        return cls(languages=languages, messages=tuple(messages), leading_word=leading)

    def message(self, index: int, language: int = 0) -> bytes:
        return self.messages[index * self.languages + language]

    def replace(self, replacements: dict[int, bytes], language: int = 0) -> Ff6aTextBank:
        messages = list(self.messages)
        for index, data in replacements.items():
            messages[index * self.languages + language] = data
        return Ff6aTextBank(self.languages, tuple(messages), self.leading_word)

    def build(self) -> bytes:
        table_end = 16 + 4 * len(self.messages)
        offsets = []
        position = table_end
        for message in self.messages:
            offsets.append(position)
            position += len(message)
        header = struct.pack(
            "<I4sII",
            self.leading_word,
            TEXT_MAGIC,
            self.message_count << 8 | self.languages,
            position,
        )
        return header + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(self.messages)


@dataclass(frozen=True, slots=True)
class Ff6aGlyph:
    """One glyph: advance, bytes per row and ``height`` rows of 2-bit pixels."""

    advance: int
    row_bytes: int
    rows: tuple[int, ...]

    def pixel(self, x: int, y: int) -> int:
        return self.rows[y] >> 2 * x & 3

    def encode(self) -> bytes:
        if not 1 <= self.row_bytes <= MAX_GLYPH_ROW_BYTES:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED, f"FF6A glyph rows must be 1..4 bytes: {self.row_bytes}"
            )
        if not 0 <= self.advance <= 0xFF:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "FF6A glyph advance out of range")
        return bytes((self.advance, self.row_bytes)) + b"".join(
            row.to_bytes(self.row_bytes, "little") for row in self.rows
        )


@dataclass(frozen=True, slots=True)
class Ff6aFont:
    height: int
    flags: int
    ascii_map: tuple[int, ...]
    glyphs: tuple[Ff6aGlyph, ...]

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> Ff6aFont:
        if data[offset + 4 : offset + 8] != FONT_MAGIC:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "No FF6A FONT at offset")
        height, flags, count = struct.unpack_from("<BBH", data, offset + 8)
        ascii_map = struct.unpack_from(f"<{FONT_ASCII_ENTRIES}H", data, offset + 12)
        starts = struct.unpack_from(f"<{count}I", data, offset + FONT_HEADER_SIZE)
        glyphs = []
        for start in starts:
            position = offset + start
            advance, row_bytes = data[position], data[position + 1] & 0x1F
            rows = tuple(
                int.from_bytes(data[row : row + row_bytes], "little")
                for row in range(position + 2, position + 2 + height * row_bytes, row_bytes)
            )
            glyphs.append(Ff6aGlyph(advance, row_bytes, rows))
        return cls(height=height, flags=flags, ascii_map=ascii_map, glyphs=tuple(glyphs))

    def build(self) -> bytes:
        if len(self.ascii_map) != FONT_ASCII_ENTRIES:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "FF6A font needs 128 ASCII slots")
        body = bytearray()
        offsets = []
        table_end = FONT_HEADER_SIZE + 4 * len(self.glyphs)
        for glyph in self.glyphs:
            if len(glyph.rows) != self.height:
                raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "FF6A glyph height mismatch")
            offsets.append(table_end + len(body))
            body += glyph.encode()
            if len(body) % 2:
                body.append(0)
        header = struct.pack("<I4sBBH", 0, FONT_MAGIC, self.height, self.flags, len(self.glyphs))
        header += struct.pack(f"<{FONT_ASCII_ENTRIES}H", *self.ascii_map)
        return header + struct.pack(f"<{len(offsets)}I", *offsets) + bytes(body)

    def character_codes(self) -> dict[str, int]:
        """Printable ASCII characters that have a glyph, mapped to their glyph code."""
        codes: dict[str, int] = {}
        for value in range(0x20, 0x7F):
            glyph = self.ascii_map[value]
            if glyph != FONT_NO_GLYPH and glyph < len(self.glyphs):
                codes[chr(value)] = glyph
        return codes
