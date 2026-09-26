"""Nintendo DS backward LZ ("BLZ"), the compression of ARM9 binaries and overlays.

A compressed binary starts with a part stored as it is (for an ARM9, at least
its first 0x4000 bytes: the secure area and the start-up code that
decompresses the rest) and ends with a footer of two words:

- ``compressed | header << 24``: how many bytes, counted from the end, the
  compressed part takes, and how many of them the footer takes (the eight
  bytes of the two words and the 0xFF padding before them);
- ``extra``: how much longer the binary is decompressed.

The start-up code decompresses in place, from the end: it reads the
compressed part backwards from below the footer and writes the output
backwards from ``extra`` bytes past the end. Read backwards, the part is a
sequence of flag bytes, each followed by eight items (most significant bit
first): a literal byte (flag 0), or a back-reference (flag 1) of two bytes,
``(length - 3) << 4 | (distance - 3) >> 8`` then ``(distance - 3) & 0xFF``,
with lengths 3..18 and distances 3..0x1002 (towards the end of the data, which
is decoded first).

Seen from the end, this is ordinary LZ77 over the reversed data.
``compress_blz`` keeps the cheapest sequence of literals and matches for it
(``lz_parse``: an optimal parse, not the greedy one of Nintendo's tool).
Writing in place must never overwrite a byte the decoder has not read yet;
that holds when the data decoded first saves no more than the whole part
does. The compressed part therefore ends where the saving is largest, and
whatever precedes it stays stored as it is.

``repack_blz`` packs a changed binary like its original instead: where the
two agree it keeps the original's items byte for byte, so a patch between the
two carries the changes and not the binary.
"""

from __future__ import annotations

import bisect
import struct
from collections.abc import Sequence

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.lz_parse import MIN_MATCH, closest_match, parse_items

MIN_DISTANCE = 3
MAX_DISTANCE = 0x1002
FOOTER_SIZE = 8
GROUP = 8
# The part of an ARM9 binary its start-up code needs stored as it is.
ARM9_STORED = 0x4000

# (1, 0, byte) for a literal, (length, distance, 0) for a match.
Item = tuple[int, int, int]


def _footer(data: bytes) -> tuple[int, int, int]:
    """The stored part's size, the footer's size and ``extra``."""
    if len(data) < FOOTER_SIZE:
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "BLZ data is too short")
    packed, extra = struct.unpack_from("<II", data, len(data) - FOOTER_SIZE)
    header = packed >> 24
    compressed = packed & 0xFFFFFF
    if not FOOTER_SIZE <= header <= compressed <= len(data):
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "BLZ footer is invalid")
    return len(data) - compressed, header, extra


def _read_items(data: bytes) -> tuple[int, list[Item]]:
    """The stored part's size and the compressed part's items, in decoding order."""
    stored, header, _ = _footer(data)
    source = data[stored : len(data) - header][::-1]
    items: list[Item] = []
    position = 0
    while position < len(source):
        flags = source[position]
        position += 1
        for bit in range(GROUP):
            if position >= len(source):
                break
            if flags & 0x80 >> bit:
                if position + 2 > len(source):
                    raise ClassicRetroError(
                        ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "BLZ data is cut short"
                    )
                first, second = source[position], source[position + 1]
                position += 2
                length = (first >> 4) + MIN_MATCH
                items.append((length, ((first & 0xF) << 8 | second) + MIN_DISTANCE, 0))
            else:
                items.append((1, 0, source[position]))
                position += 1
    return stored, items


def _decode(items: Sequence[Item]) -> bytes:
    """What the items produce, in decoding order (the binary's end first)."""
    output = bytearray()
    for length, distance, literal in items:
        if not distance:
            output.append(literal)
            continue
        if distance > len(output):
            raise ClassicRetroError(
                ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "BLZ reference past the end"
            )
        for _ in range(length):
            output.append(output[-distance])
    return bytes(output)


def decompress_blz(data: bytes) -> bytes:
    """The binary ``data`` holds, decompressed; data without a footer is refused."""
    stored, _, extra = _footer(data)
    output = _decode(_read_items(data)[1])
    size = len(data) - stored + extra
    if len(output) != size:
        raise ClassicRetroError(
            ErrorCode.COMPRESSION_ROUNDTRIP_FAILED,
            f"BLZ data decodes to {len(output)} bytes, not {size}",
        )
    return data[:stored] + output[::-1]


def _stream(items: Sequence[Item]) -> bytes:
    """The items with their flag bytes, in decoding order."""
    stream = bytearray()
    flag_index = 0
    for number, (length, distance, literal) in enumerate(items):
        if number % GROUP == 0:
            flag_index = len(stream)
            stream.append(0)
        if distance:
            stream[flag_index] |= 0x80 >> number % GROUP
            value = (length - MIN_MATCH) << 12 | (distance - MIN_DISTANCE)
            stream += value.to_bytes(2, "big")
        else:
            stream.append(literal)
    return bytes(stream)


def _savings(items: Sequence[Item]) -> list[int]:
    """Bytes saved after each item (decoded minus read, flag bytes included)."""
    saved = []
    total = 0
    for number, (length, distance, _) in enumerate(items):
        if number % GROUP == 0:
            total -= 1
        total += length - (2 if distance else 1)
        saved.append(total)
    return saved


def _packed(data: bytes, stored: int, items: Sequence[Item]) -> bytes:
    """``data[:stored]`` as it is, then the items, the padding and the footer."""
    stream = _stream(items)
    padding = -(stored + len(stream) + FOOTER_SIZE) % 4
    header = padding + FOOTER_SIZE
    compressed = len(stream) + header
    footer = struct.pack("<II", compressed | header << 24, len(data) - stored - compressed)
    return data[:stored] + stream[::-1] + b"\xff" * padding + footer


def compress_blz(data: bytes, *, stored: int = ARM9_STORED) -> bytes:
    """``data`` with its first ``stored`` bytes as they are and the rest compressed.

    The result can be decompressed in place (see the module notes), and its
    length is a multiple of 4. Data that nothing would shrink comes back as it
    is, without a footer.
    """
    if not 0 <= stored <= len(data):
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "Stored part out of range")
    items = parse_items(data[stored:][::-1], min_distance=MIN_DISTANCE, max_distance=MAX_DISTANCE)
    saved = _savings(items)
    best = max(range(len(items)), key=lambda number: saved[number], default=-1)
    if best < 0 or saved[best] <= 0:
        return bytes(data)
    kept = items[: best + 1]
    return _packed(data, len(data) - sum(length for length, _, _ in kept), kept)


def repack_blz(original: bytes, data: bytes) -> bytes:
    """``data`` packed like ``original``, the packed binary it changes in place.

    ``data`` has the length of what ``original`` holds. Items of the original
    that still produce the same bytes stay; a match that now copies changed
    bytes takes another distance where the same bytes lie; the groups of eight
    items around the changes are packed again (``lz_parse``), into whole groups
    of eight, so that every group after them keeps its flag byte. The stored
    part keeps its size. Refused when the result could not be decompressed in
    place.
    """
    stored, items = _read_items(original)
    before = decompress_blz(original)
    if len(before) != len(data):
        raise ClassicRetroError(
            ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "The changed binary has another length"
        )
    old = before[stored:][::-1]
    new = data[stored:][::-1]
    changed = _changed_ranges(old, new)
    positions = [0]
    for length, _, _ in items:
        positions.append(positions[-1] + length)

    def touches(start: int, end: int) -> bool:
        index = bisect.bisect_right(changed, (start, float("inf"))) - 1
        return any(
            begin < end and start < finish for begin, finish in changed[max(index, 0) : index + 2]
        )

    marked: set[int] = set()
    items = list(items)
    for number, (length, distance, _) in enumerate(items):
        start = positions[number]
        if touches(start, start + length):
            marked.add(number // GROUP)
        elif distance and touches(start - distance, start - distance + length):
            moved = closest_match(new, start, length, MIN_DISTANCE, MAX_DISTANCE)
            if moved is None:
                marked.add(number // GROUP)
            else:
                items[number] = (length, moved, 0)

    groups = -(-len(items) // GROUP)
    result: list[Item] = []
    group = 0
    while group < groups:
        if group not in marked:
            result += items[group * GROUP : (group + 1) * GROUP]
            group += 1
            continue
        end = group + 1
        while True:
            while end < groups and end in marked:
                end += 1
            first = positions[group * GROUP]
            last = positions[min(end * GROUP, len(items))]
            packed = parse_items(
                new, min_distance=MIN_DISTANCE, max_distance=MAX_DISTANCE, start=first, end=last
            )
            if end == groups:
                break
            aligned = _in_groups(packed, new, first)
            if aligned is not None:
                packed = aligned
                break
            end += 1
        result += packed
        group = end
    saved = _savings(result)
    if saved and max(saved) > saved[-1]:
        raise ClassicRetroError(
            ErrorCode.COMPRESSION_ROUNDTRIP_FAILED,
            "The repacked binary could not be decompressed in place",
        )
    return _packed(data, stored, result)


def _changed_ranges(old: bytes, new: bytes) -> list[tuple[int, int]]:
    """Where two equally long byte strings differ, as sorted (start, end) ranges."""
    ranges: list[tuple[int, int]] = []
    block = 256
    for start in range(0, len(new), block):
        if old[start : start + block] == new[start : start + block]:
            continue
        for position in range(start, min(start + block, len(new))):
            if old[position] != new[position]:
                if ranges and ranges[-1][1] == position:
                    ranges[-1] = (ranges[-1][0], position + 1)
                else:
                    ranges.append((position, position + 1))
    return ranges


def _in_groups(items: list[Item], data: bytes, start: int) -> list[Item] | None:
    """The items split until they fill whole groups of eight, or None when they cannot.

    A match of 6 or more becomes two of the same distance; one of 4 or 5, a
    literal and a match; one of 3, three literals.
    """
    items = list(items)
    while len(items) % GROUP:
        position = start
        for index, (length, distance, _) in enumerate(items):
            if distance and length > MIN_MATCH:
                if length >= 2 * MIN_MATCH:
                    parts = [(MIN_MATCH, distance, 0), (length - MIN_MATCH, distance, 0)]
                else:
                    parts = [(1, 0, data[position]), (length - 1, distance, 0)]
                items[index : index + 1] = parts
                break
            position += length
        else:
            position = start
            for index, (length, distance, _) in enumerate(items):
                if distance:
                    items[index : index + 1] = [(1, 0, data[position + k]) for k in range(length)]
                    break
                position += length
            else:
                return None
    return items


def decompress_blz_in_place(data: bytes) -> bytes:
    """Decompress as the start-up code does, in one buffer; refuse data it would corrupt."""
    stored, header, extra = _footer(data)
    buffer = bytearray(data) + bytearray(max(extra, 0))
    source = len(data) - header
    destination = len(data) + extra
    while source > stored:
        source -= 1
        flags = buffer[source]
        for bit in range(GROUP):
            if source <= stored:
                break
            if flags & 0x80 >> bit:
                first = buffer[source - 1]
                second = buffer[source - 2]
                source -= 2
                length = (first >> 4) + MIN_MATCH
                distance = ((first & 0xF) << 8 | second) + MIN_DISTANCE
                for _ in range(length):
                    destination -= 1
                    buffer[destination] = buffer[destination + distance]
            else:
                source -= 1
                destination -= 1
                buffer[destination] = buffer[source]
            if destination < source:
                raise ClassicRetroError(
                    ErrorCode.COMPRESSION_ROUNDTRIP_FAILED,
                    "BLZ data would overwrite itself while it decompresses in place",
                )
    if destination != stored:
        raise ClassicRetroError(
            ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "BLZ data does not end where it should"
        )
    return bytes(buffer)
