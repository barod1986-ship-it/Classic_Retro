"""MIO0, the LZ compression of Nintendo 64 games (Super Mario 64, Mario Kart 64).

Layout, all big-endian: ``MIO0``, the decompressed size, the offset of the
match stream and the offset of the literal stream (both from the start of the
block), then from byte 16 the layout bits, most significant bit first, one per
item: the next byte of the literal stream (bit 1), or a match (bit 0) of two
bytes of the match stream, ``(length - 3) << 4 | (distance - 1) >> 8`` then
``(distance - 1) & 0xFF``, with lengths 3..18 and distances 1..4096. A match
may run on into the bytes it produces. The layout bits are padded so that the
match stream starts on a 4-byte boundary; the literal stream follows it
directly and ends the block.

``compress_mio0`` takes the cheapest sequence of items (``lz_parse``), as
``compress_lz77_optimal`` does. ``find_mio0`` lists the blocks of an image:
Super Mario 64's segments are stored this way, so a scan of the raw image sees
none of what they hold.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.lz_parse import MIN_MATCH, parse_items

MIO0_MAGIC = b"MIO0"
HEADER_SIZE = 16
WINDOW = 0x1000
MAX_SIZE = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class Mio0Block:
    """A block at ``offset`` of an image: the bytes it occupies and the bytes it holds."""

    offset: int
    packed_size: int
    size: int


def _refuse(message: str) -> ClassicRetroError:
    return ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, message)


def _decode(data: bytes, offset: int) -> tuple[bytes, int]:
    """What the block at ``offset`` holds, and how many bytes of ``data`` it takes.

    The output grows item by item and never from the declared size alone, so a
    header that declares far more than the data could hold is refused as soon
    as a stream runs out.
    """
    if not 0 <= offset <= len(data) - HEADER_SIZE:
        raise _refuse("MIO0 header is cut short")
    if data[offset : offset + 4] != MIO0_MAGIC:
        raise _refuse("Not MIO0 data")
    size, match_offset, literal_offset = struct.unpack_from(">III", data, offset + 4)
    end = len(data) - offset
    if not (HEADER_SIZE <= match_offset <= end and HEADER_SIZE <= literal_offset <= end):
        raise _refuse("MIO0 stream offsets are out of range")
    layout = offset + HEADER_SIZE
    matches = offset + match_offset
    literals = offset + literal_offset
    output = bytearray()
    bit = 0
    while len(output) < size:
        if layout + bit // 8 >= len(data):
            raise _refuse("MIO0 layout bits are cut short")
        if data[layout + bit // 8] & 0x80 >> bit % 8:
            if literals >= len(data):
                raise _refuse("MIO0 literal stream is cut short")
            output.append(data[literals])
            literals += 1
        else:
            if matches + 2 > len(data):
                raise _refuse("MIO0 match stream is cut short")
            first, second = data[matches], data[matches + 1]
            matches += 2
            length = (first >> 4) + MIN_MATCH
            distance = ((first & 0xF) << 8 | second) + 1
            if distance > len(output):
                raise _refuse("MIO0 reference before the start")
            for _ in range(length):
                output.append(output[-distance])
        bit += 1
    layout_end = layout + -(-bit // 8)
    return bytes(output[:size]), max(layout_end, matches, literals) - offset


def decompress_mio0(data: bytes, offset: int = 0) -> bytes:
    """What the block that starts at ``offset`` holds; broken data is refused."""
    return _decode(data, offset)[0]


def mio0_packed_size(data: bytes, offset: int = 0) -> int:
    """The bytes the block at ``offset`` occupies: header, layout bits and both streams."""
    return _decode(data, offset)[1]


def compress_mio0(data: bytes) -> bytes:
    """Optimally parsed MIO0; the match stream is aligned, the block is not padded."""
    if len(data) > MAX_SIZE:
        raise _refuse("MIO0 input exceeds 4 GiB")
    items = parse_items(data, min_distance=1, max_distance=WINDOW)
    layout = bytearray(-(-len(items) // 8))
    matches = bytearray()
    literals = bytearray()
    for number, (length, distance, literal) in enumerate(items):
        if distance:
            token = (length - MIN_MATCH) << 12 | (distance - 1)
            matches += token.to_bytes(2, "big")
        else:
            layout[number // 8] |= 0x80 >> number % 8
            literals.append(literal)
    layout += bytes(-len(layout) % 4)
    match_offset = HEADER_SIZE + len(layout)
    header = MIO0_MAGIC + struct.pack(">III", len(data), match_offset, match_offset + len(matches))
    return header + bytes(layout) + bytes(matches) + bytes(literals)


def find_mio0(data: bytes) -> list[Mio0Block]:
    """Every block of an image whose magic decodes without error, in order."""
    blocks: list[Mio0Block] = []
    offset = data.find(MIO0_MAGIC)
    while offset >= 0:
        try:
            output, packed_size = _decode(data, offset)
        except ClassicRetroError:
            pass
        else:
            blocks.append(Mio0Block(offset, packed_size, len(output)))
        offset = data.find(MIO0_MAGIC, offset + 1)
    return blocks
