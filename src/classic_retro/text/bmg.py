"""BMG message files ("MESGbmg1"), the text files of many Nintendo DS games.

A BMG file is a 32-byte header (the magic, the file size, the number of
sections and the text encoding) and sections padded to 32 bytes:

- ``INF1``: the number of messages and the size of an entry, then one entry
  per message: the offset of its text in ``DAT1`` and, when entries are
  longer than 4 bytes, attributes the game reads;
- ``DAT1``: the texts, each ended by a zero. The first two bytes are an empty
  text.

``Bmg`` reads UTF-16 files (encoding 2). A text is code units, and an escape
is the unit 0x001A, a byte giving the escape's whole size in bytes, a byte
naming its kind and the bytes of its argument. ``Bmg.build`` writes the texts
one after the other in the order of their messages, which is how the files
this toolkit targets are laid out, so an unchanged file is rebuilt byte for
byte.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

MAGIC = b"MESGbmg1"
UTF16 = 2
ESCAPE = 0x1A
SECTION_ALIGNMENT = 32


@dataclass(frozen=True, slots=True)
class BmgEscape:
    """An escape inside a text: its kind and the bytes of its argument."""

    kind: int
    argument: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.kind <= 0xFF or len(self.argument) > 0xFF - 4:
            raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, "Invalid BMG escape")

    @property
    def notation(self) -> str:
        return f"{{{self.kind:02X}:{self.argument.hex().upper()}}}"

    def encode(self) -> bytes:
        return struct.pack("<HBB", ESCAPE, 4 + len(self.argument), self.kind) + self.argument


Piece = str | BmgEscape


def encode_text(pieces: Sequence[Piece]) -> bytes:
    """A text's units (without its final zero)."""
    data = bytearray()
    for piece in pieces:
        if isinstance(piece, BmgEscape):
            data += piece.encode()
            continue
        for character in piece:
            if character in ("\x00", chr(ESCAPE)) or ord(character) > 0xFFFF:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT, f"A BMG text cannot hold U+{ord(character):04X}"
                )
        data += piece.encode("utf-16-le")
    return bytes(data)


def decode_text(data: bytes, start: int) -> tuple[tuple[Piece, ...], int]:
    """The text at ``start`` and where its final zero ends."""
    pieces: list[Piece] = []
    run: list[str] = []
    position = start
    while True:
        if position + 2 > len(data):
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "A BMG text is not ended")
        (unit,) = struct.unpack_from("<H", data, position)
        if unit == 0:
            break
        if unit != ESCAPE:
            run.append(chr(unit))
            position += 2
            continue
        if position + 4 > len(data):
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "A BMG escape is cut short")
        size, kind = data[position + 2], data[position + 3]
        if size < 4 or position + size > len(data):
            raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, "Invalid BMG escape size")
        if run:
            pieces.append("".join(run))
            run.clear()
        pieces.append(BmgEscape(kind, bytes(data[position + 4 : position + size])))
        position += size
    if run:
        pieces.append("".join(run))
    return tuple(pieces), position + 2


def _padded(section: bytes) -> bytes:
    return section + bytes(-len(section) % SECTION_ALIGNMENT)


@dataclass(frozen=True, slots=True)
class Bmg:
    """A UTF-16 BMG file: its header fields, its entries' attributes and its texts."""

    header_tail: bytes
    info_field: int
    attributes: tuple[bytes, ...]
    texts: tuple[tuple[Piece, ...], ...]

    @classmethod
    def parse(cls, data: bytes) -> Bmg:
        if len(data) < 0x20 or data[:8] != MAGIC:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "Not a BMG file")
        size, sections = struct.unpack_from("<II", data, 8)
        if size != len(data) or sections != 2 or data[0x10] != UTF16:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE, "Only two-section UTF-16 BMG files are supported"
            )
        magic, info_size = struct.unpack_from("<4sI", data, 0x20)
        count, entry_size, info_field = struct.unpack_from("<HHI", data, 0x28)
        texts_at = 0x20 + info_size
        texts_magic, texts_size = struct.unpack_from("<4sI", data, texts_at)
        if (
            magic != b"INF1"
            or texts_magic != b"DAT1"
            or entry_size < 4
            or 0x30 + count * entry_size > texts_at
            or texts_at + texts_size != len(data)
        ):
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "Unexpected BMG sections")
        texts_data = data[texts_at + 8 : texts_at + texts_size]
        attributes: list[bytes] = []
        texts: list[tuple[Piece, ...]] = []
        for number in range(count):
            entry = 0x30 + number * entry_size
            (offset,) = struct.unpack_from("<I", data, entry)
            attributes.append(bytes(data[entry + 4 : entry + entry_size]))
            texts.append(decode_text(texts_data, offset)[0])
        return cls(bytes(data[0x10:0x20]), info_field, tuple(attributes), tuple(texts))

    def with_texts(self, texts: Sequence[Sequence[Piece]]) -> Bmg:
        if len(texts) != len(self.texts):
            raise ClassicRetroError(
                ErrorCode.RESOURCE_SET_MISMATCH,
                f"The file holds {len(self.texts)} messages, not {len(texts)}",
            )
        return Bmg(self.header_tail, self.info_field, self.attributes, tuple(map(tuple, texts)))

    def build(self) -> bytes:
        entry_size = 4 + (len(self.attributes[0]) if self.attributes else 0)
        texts = bytearray(2)
        entries = bytearray()
        for attributes, pieces in zip(self.attributes, self.texts, strict=True):
            entries += struct.pack("<I", len(texts)) + attributes
            texts += encode_text(pieces) + b"\x00\x00"
        info = struct.pack("<HHI", len(self.texts), entry_size, self.info_field) + entries
        info_section = _padded(struct.pack("<4sI", b"INF1", 0) + info)
        info_section = info_section[:4] + struct.pack("<I", len(info_section)) + info_section[8:]
        texts_section = _padded(struct.pack("<4sI", b"DAT1", 0) + texts)
        texts_section = (
            texts_section[:4] + struct.pack("<I", len(texts_section)) + texts_section[8:]
        )
        size = 0x20 + len(info_section) + len(texts_section)
        header = MAGIC + struct.pack("<II", size, 2) + self.header_tail
        return header + info_section + texts_section
