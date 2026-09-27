"""Text engine of *Gran Turismo* (PlayStation): the license tests' briefings.

The game's texts live in GT-ARC archives: ``"@(#)GT-ARC"`` and two zero bytes,
the archive's kind (1: files stored as they are; with 0x8000, packed with
GT-ZIP, ``rebuild.gtzip``), the number of files, then three words for each
file: its offset, the bytes stored and its size. MESSAGES.DAT holds four
kinds of text in six languages; its file 18 is the US English briefings of
the license tests (``LICENSE_FILE``): 24 offsets of two bytes (from the file's
start), then 24 texts, each padded to an even length, in the order of the
tests: license B's eight, then A's, then International A's.

A briefing is its paragraph count, then its title and its paragraphs, each a
list of words: a word count, then each word as its length (the zero that ends
it included), its characters and the zero. The title is a list of one word,
spaces and all. The game draws the title centred in its font 2 and lays each
paragraph out word by word in font 1 (``engines.gran_turismo_arabic``).

A briefing's notation is its title on the first line, then a line for each
paragraph, its words separated by spaces.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.gtzip import decompress_gtzip

GT_ARC_MAGIC = b"@(#)GT-ARC\x00\x00"
GT_ARC_PACKED = 0x8000
GT_ARC_ENTRY = 12
LICENSE_FILE = 18
BRIEFINGS = 24
# The tests in the order of the briefings, "B-1" first.
LICENSE_TESTS = tuple(f"{license}-{test}" for license in ("B", "A", "IA") for test in range(1, 9))


class GranTurismoEngineAdapter(EngineAdapter):
    id = "ps1.gran-turismo-license"
    display_name = "Gran Turismo license test briefings"
    platform_ids = ("ps1",)


def _refuse(message: str) -> ClassicRetroError:
    return ClassicRetroError(ErrorCode.INVALID_REFERENCE, message)


@dataclass(frozen=True, slots=True)
class GtArcFile:
    """A file of a GT-ARC archive: where it starts, the bytes stored and its size."""

    offset: int
    stored: int
    size: int


def read_gt_arc(data: bytes) -> tuple[int, tuple[GtArcFile, ...]]:
    """The archive's kind and its files; anything else is refused."""
    if len(data) < 16 or data[:12] != GT_ARC_MAGIC:
        raise _refuse("Not a GT-ARC archive")
    kind, count = struct.unpack_from("<HH", data, 12)
    table_end = 16 + GT_ARC_ENTRY * count
    if table_end > len(data):
        raise _refuse("The GT-ARC table runs past the archive")
    files = tuple(
        GtArcFile(*struct.unpack_from("<III", data, 16 + GT_ARC_ENTRY * index))
        for index in range(count)
    )
    for file in files:
        if file.offset < table_end or file.offset + file.stored > len(data):
            raise _refuse("A GT-ARC file lies outside the archive")
    return kind, files


def gt_arc_file(data: bytes, index: int) -> bytes:
    """File ``index`` of the archive, unpacked when the archive is packed."""
    kind, files = read_gt_arc(data)
    if not 0 <= index < len(files):
        raise _refuse(f"The GT-ARC archive has no file {index}")
    file = files[index]
    stored = data[file.offset : file.offset + file.stored]
    if kind & GT_ARC_PACKED:
        return decompress_gtzip(stored, file.size)
    if file.stored != file.size:
        raise _refuse(f"GT-ARC file {index} is stored with another size")
    return stored


def gt_arc_room(data: bytes, index: int) -> int:
    """The bytes file ``index`` may take: up to the next file, or the archive's end."""
    _, files = read_gt_arc(data)
    start = files[index].offset
    after = [file.offset for file in files if file.offset > start]
    return min(after, default=len(data)) - start


def replace_gt_arc_file(data: bytes, index: int, content: bytes) -> bytes:
    """The archive with file ``index`` replaced in its own room (the rest zero-filled)."""
    kind, files = read_gt_arc(data)
    if kind & GT_ARC_PACKED:
        raise _refuse("Only an archive of stored files can take a new file")
    if not 0 <= index < len(files):
        raise _refuse(f"The GT-ARC archive has no file {index}")
    room = gt_arc_room(data, index)
    if len(content) > room:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"GT-ARC file {index} needs {len(content)} bytes; its room holds {room}",
        )
    output = bytearray(data)
    start = files[index].offset
    output[start : start + room] = content + bytes(room - len(content))
    struct.pack_into("<II", output, 16 + GT_ARC_ENTRY * index + 4, len(content), len(content))
    return bytes(output)


def split_briefings(data: bytes) -> tuple[bytes, ...]:
    """The 24 texts of a license file, each with its padding."""
    table = 2 * BRIEFINGS
    if len(data) < table:
        raise _refuse("The license file is too short")
    offsets = struct.unpack_from(f"<{BRIEFINGS}H", data)
    ends = (*offsets[1:], len(data))
    if offsets[0] != table or any(end < start for start, end in zip(offsets, ends, strict=True)):
        raise _refuse("The license file's offsets are out of order")
    if ends[-1] > len(data):
        raise _refuse("The license file's offsets run past it")
    return tuple(data[start:end] for start, end in zip(offsets, ends, strict=True))


def join_briefings(texts: Sequence[bytes]) -> bytes:
    """A license file from its 24 texts, each padded to an even length."""
    if len(texts) != BRIEFINGS:
        raise _refuse(f"A license file holds {BRIEFINGS} texts, not {len(texts)}")
    table = bytearray()
    body = bytearray()
    for text in texts:
        padded = text + bytes(len(text) % 2)
        table += struct.pack("<H", 2 * BRIEFINGS + len(body))
        body += padded
    if 2 * BRIEFINGS + len(body) > 0xFFFF:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The license file passes 64 KiB")
    return bytes(table + body)


@dataclass(frozen=True, slots=True)
class Briefing:
    """A briefing's title and paragraphs, each word as the game's bytes."""

    title: bytes
    paragraphs: tuple[tuple[bytes, ...], ...]


def _words(data: bytes, position: int) -> tuple[tuple[bytes, ...], int]:
    count = data[position]
    position += 1
    words = []
    for _ in range(count):
        length = data[position]
        end = position + 1 + length
        word = data[position + 1 : end]
        if length < 1 or len(word) != length or word[-1] != 0 or 0 in word[:-1]:
            raise _refuse(f"A briefing's word at {position:#x} is broken")
        words.append(bytes(word[:-1]))
        position = end
    return tuple(words), position


def parse_briefing(data: bytes) -> Briefing:
    """A briefing's text, its padding (one zero at most) allowed after it."""
    try:
        count = data[0]
        title, position = _words(data, 1)
        paragraphs = []
        for _ in range(count):
            words, position = _words(data, position)
            paragraphs.append(words)
    except IndexError:
        raise _refuse("A briefing is cut short") from None
    if len(title) != 1 or data[position:] not in (b"", b"\x00"):
        raise _refuse("A briefing has something else than one title and its paragraphs")
    return Briefing(title[0], tuple(paragraphs))


def briefing_bytes(briefing: Briefing) -> bytes:
    """A briefing as the game stores it, without padding."""

    def words(items: Sequence[bytes]) -> bytes:
        if len(items) > 0xFF:
            raise ClassicRetroError(ErrorCode.TEXT_OVERFLOW, "A paragraph holds 255 words at most")
        output = bytearray((len(items),))
        for word in items:
            if not word or len(word) > 0xFE or 0 in word:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT, f"A word of {len(word)} bytes cannot be stored"
                )
            output += bytes((len(word) + 1,)) + word + b"\x00"
        return bytes(output)

    if not briefing.paragraphs or len(briefing.paragraphs) > 0xFF:
        raise ClassicRetroError(ErrorCode.TEXT_OVERFLOW, "A briefing holds 1 to 255 paragraphs")
    output = bytes((len(briefing.paragraphs),)) + words((briefing.title,))
    return output + b"".join(words(paragraph) for paragraph in briefing.paragraphs)


def briefing_notation(briefing: Briefing) -> str:
    """The title, then a line for each paragraph (the game's text is ASCII)."""
    lines = [briefing.title, *(b" ".join(words) for words in briefing.paragraphs)]
    try:
        return "\n".join(line.decode("ascii") for line in lines)
    except UnicodeDecodeError:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "The briefing has characters outside ASCII"
        ) from None


def parse_notation(text: str) -> tuple[str, tuple[tuple[str, ...], ...]]:
    """A briefing's notation as its title and its paragraphs' words."""
    title, *lines = text.split("\n")
    if not title.strip() or not lines:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A briefing is a title line, then a line per paragraph"
        )
    paragraphs = tuple(tuple(line.split()) for line in lines)
    if any(not words for words in paragraphs):
        raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "A briefing has an empty paragraph")
    return title.strip(), paragraphs
