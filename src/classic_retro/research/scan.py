"""Scanners over a game image: free space, pointers, pointer tables, text, patterns.

Every scanner reads the image as bytes and reports offsets into it, within
``start``..``end`` when given. The caller turns an offset into the address the
console sees (``base + offset``; a Game Boy Advance cartridge starts at
``0x08000000``). Pointers are read as linear addresses, which fits the GBA and
any flat mapping; banked mappings (such as the SNES LoROM) are not modelled.
"""

from __future__ import annotations

import re
import sys
from array import array
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.research.tables import TextTable


@dataclass(frozen=True, slots=True)
class FreeRun:
    offset: int
    size: int
    fill: int


@dataclass(frozen=True, slots=True)
class Reference:
    """A pointer-sized value at ``offset`` that equals a searched address."""

    offset: int
    value: int


@dataclass(frozen=True, slots=True)
class PointerTable:
    """Consecutive entries, ``stride`` bytes apart, that all point into the image."""

    offset: int
    count: int
    stride: int
    lowest: int
    highest: int
    # Each entry at or above the one before it (a table of strings in order).
    ascending: bool
    # Entries with bit 0 set: on ARM, pointers to Thumb code.
    odd: int


@dataclass(frozen=True, slots=True)
class TextRun:
    offset: int
    size: int
    text: str
    # ASCII: a zero byte follows. Table: the string ended on an end code.
    terminated: bool


@dataclass(frozen=True, slots=True)
class RelativeMatch:
    """Where a word sits in an unknown encoding whose letters are consecutive codes."""

    offset: int
    # The code of the word's first letter, and of "A" (or "a") it implies.
    code: int
    alphabet: int


def _span(data: bytes, start: int, end: int | None) -> tuple[int, int]:
    stop = len(data) if end is None else end
    if not 0 <= start <= stop <= len(data):
        raise ClassicRetroError(
            ErrorCode.INVALID_BYTE_RANGE,
            f"0x{start:X}..0x{stop:X} is outside the image (0x{len(data):X} bytes)",
        )
    return start, stop


def free_space(
    data: bytes,
    *,
    fills: Sequence[int] = (0xFF, 0x00),
    min_size: int = 256,
    align: int = 1,
    start: int = 0,
    end: int | None = None,
) -> list[FreeRun]:
    """Runs of one fill byte, at least ``min_size`` long once aligned to ``align``."""
    first, stop = _span(data, start, end)
    runs = []
    for fill in fills:
        pattern = re.compile(re.escape(bytes([fill])) + b"{%d,}" % max(min_size, 1))
        for match in pattern.finditer(data, first, stop):
            offset = -(-match.start() // align) * align
            if match.end() - offset >= min_size:
                runs.append(FreeRun(offset, match.end() - offset, fill))
    return sorted(runs, key=lambda run: run.offset)


def _values(
    data: bytes, width: int, byteorder: str, align: int, start: int, end: int
) -> tuple[int, Sequence[int]]:
    """The first aligned offset, and the value of every ``width`` bytes from each aligned offset."""
    first = -(-start // align) * align
    count = max(0, (end - width - first) // align + 1)
    typecode = {2: "H", 4: "I"}.get(width)
    if typecode is not None and align == width and array(typecode).itemsize == width:
        values = array(typecode, data[first : first + count * width])
        if byteorder != sys.byteorder:
            values.byteswap()
        return first, values
    return first, array(
        "Q",
        (
            int.from_bytes(data[offset : offset + width], byteorder)
            for offset in range(first, first + count * align, align)
        ),
    )


def find_references(
    data: bytes,
    targets: Sequence[tuple[int, int]],
    *,
    width: int = 4,
    byteorder: str = "little",
    align: int = 4,
    start: int = 0,
    end: int | None = None,
) -> list[Reference]:
    """Every aligned value in one of the ``targets`` ranges (low inclusive, high exclusive)."""
    first, stop = _span(data, start, end)
    base, values = _values(data, width, byteorder, align, first, stop)
    exact = {low for low, high in targets if high == low + 1}
    ranges = [(low, high) for low, high in targets if high != low + 1]
    found = []
    for index, value in enumerate(values):
        if value in exact or any(low <= value < high for low, high in ranges):
            found.append(Reference(base + index * align, value))
    return found


def pointer_tables(
    data: bytes,
    *,
    target: tuple[int, int],
    width: int = 4,
    byteorder: str = "little",
    align: int = 4,
    stride: int | None = None,
    min_count: int = 8,
    start: int = 0,
    end: int | None = None,
) -> list[PointerTable]:
    """Runs of at least ``min_count`` entries, ``stride`` apart, all inside ``target``."""
    step = stride or width
    if step % align:
        raise ClassicRetroError(
            ErrorCode.INVALID_SEARCH_PATTERN, "the stride must be a multiple of the alignment"
        )
    first, stop = _span(data, start, end)
    base, values = _values(data, width, byteorder, align, first, stop)
    low, high = target
    slots = step // align
    tables = []
    for phase in range(slots):
        run: list[int] = []
        first_index = phase
        # One slot past the end closes the last run.
        for index in range(phase, len(values) + slots, slots):
            if index < len(values) and low <= values[index] < high:
                if not run:
                    first_index = index
                run.append(values[index])
                continue
            if len(run) >= min_count:
                tables.append(
                    PointerTable(
                        offset=base + first_index * align,
                        count=len(run),
                        stride=step,
                        lowest=min(run),
                        highest=max(run),
                        ascending=all(a <= b for a, b in pairwise(run)),
                        odd=sum(entry & 1 for entry in run),
                    )
                )
            run = []
    return sorted(tables, key=lambda table: table.offset)


def ascii_strings(
    data: bytes, *, min_length: int = 8, start: int = 0, end: int | None = None
) -> list[TextRun]:
    """Runs of printable ASCII."""
    first, stop = _span(data, start, end)
    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % max(min_length, 1))
    return [
        TextRun(
            match.start(),
            match.end() - match.start(),
            match.group().decode("ascii"),
            match.end() < len(data) and data[match.end()] == 0,
        )
        for match in pattern.finditer(data, first, stop)
    ]


def table_strings(
    data: bytes,
    table: TextTable,
    *,
    min_length: int = 8,
    start: int = 0,
    end: int | None = None,
) -> Iterator[TextRun]:
    """Runs the table decodes, with at least ``min_length`` entries before any end code.

    Strings are read greedily from the left: a run that starts inside another is
    not reported again.
    """
    offset, stop = _span(data, start, end)
    view = data[:stop]
    if table.longest == 1:
        yield from _byte_table_strings(view, table, min_length, offset)
        return
    firsts = _byte_class(code[0] for code in table.entries)
    while offset < stop:
        found_start = firsts.search(view, offset)
        if found_start is None:
            return
        offset = position = found_start.start()
        parts = []
        length = 0
        terminated = False
        while position < stop:
            found = table.match(view, position)
            if found is None:
                break
            code, text = found
            position += len(code)
            parts.append(text)
            if code in table.ends:
                terminated = True
                break
            length += 1
        if length >= min_length:
            yield TextRun(offset, position - offset, "".join(parts), terminated)
        offset = max(position, offset + 1)


def _byte_class(values: Iterable[int]) -> re.Pattern[bytes]:
    return re.compile(
        b"[" + b"".join(re.escape(bytes([value])) for value in sorted(set(values))) + b"]"
    )


def _byte_table_strings(
    view: bytes, table: TextTable, min_length: int, offset: int
) -> Iterator[TextRun]:
    """``table_strings`` for a table of one-byte codes: the same runs, found by a regex."""
    texts = {code[0]: text for code, text in table.entries.items()}
    ends = {code[0] for code in table.ends}
    body = _byte_class(set(texts) - ends).pattern
    tail = _byte_class(ends).pattern + b"?" if ends else b""
    pattern = re.compile(body + b"{%d,}" % max(min_length, 1) + tail)
    for match in pattern.finditer(view, offset):
        run = match.group()
        terminated = run[-1] in ends
        yield TextRun(match.start(), len(run), "".join(texts[byte] for byte in run), terminated)


_WORD = re.compile(r"[A-Z]{3,}|[a-z]{3,}")


def relative_search(
    data: bytes, word: str, *, start: int = 0, end: int | None = None
) -> list[RelativeMatch]:
    """Where ``word`` sits if its letters are consecutive codes in some unknown order base.

    The word is three or more letters of one case. Each match gives the code of
    the word's first letter and of the "A" (or "a") it implies, a start for a
    text table.
    """
    if not _WORD.fullmatch(word):
        raise ClassicRetroError(
            ErrorCode.INVALID_SEARCH_PATTERN,
            "a relative search takes a word of three or more letters, all of one case",
        )
    first, stop = _span(data, start, end)
    letter = "A" if word.isupper() else "a"
    deltas = [ord(character) - ord(word[0]) for character in word]
    matches = []
    for code in range(256):
        codes = [code + delta for delta in deltas]
        if min(codes) < 0 or max(codes) > 0xFF:
            continue
        pattern = bytes(codes)
        offset = data.find(pattern, first, stop)
        while offset != -1:
            matches.append(RelativeMatch(offset, code, code - (ord(word[0]) - ord(letter))))
            offset = data.find(pattern, offset + 1, stop)
    return sorted(matches, key=lambda match: match.offset)


def parse_pattern(text: str) -> re.Pattern[bytes]:
    """Hex bytes with ``??`` for any byte (``"01 02 ?? 04"``), matched at every offset."""
    compact = "".join(text.split())
    if not compact or len(compact) % 2:
        raise ClassicRetroError(
            ErrorCode.INVALID_SEARCH_PATTERN, "a pattern is hex bytes, two digits each (?? for any)"
        )
    parts = []
    for index in range(0, len(compact), 2):
        pair = compact[index : index + 2]
        if pair == "??":
            parts.append(b".")
            continue
        try:
            parts.append(re.escape(bytes.fromhex(pair)))
        except ValueError:
            raise ClassicRetroError(
                ErrorCode.INVALID_SEARCH_PATTERN, f"{pair!r} is not a hex byte or ??"
            ) from None
    return re.compile(b"(?=" + b"".join(parts) + b")", re.DOTALL)


def find_pattern(
    data: bytes, pattern: re.Pattern[bytes], *, start: int = 0, end: int | None = None
) -> list[int]:
    first, stop = _span(data, start, end)
    return [match.start() for match in pattern.finditer(data, first, stop)]
