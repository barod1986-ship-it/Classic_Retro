"""GBA BIOS LZ77 (type 0x10) compression.

Layout: ``0x10``, the decompressed size as 24 bits, then blocks of one flag
byte (most significant bit first) and eight items: a literal byte (flag 0) or a
back-reference (flag 1) of two bytes, ``(length - 3) << 12 | (distance - 1)``
stored high byte first, with lengths 3..18 and distances 1..4096.

``vram_safe`` avoids distance 1: the BIOS routine that writes VRAM writes 16
bits at a time and would read a byte it has not stored yet.

``compress_lz77`` is greedy (the longest match at each step); the targets'
builds depend on its exact output. ``compress_lz77_optimal`` takes the
cheapest sequence of items instead (``lz_parse``), for data that must fit the
place of an original packed by a better compressor than a greedy one.
"""

from __future__ import annotations

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.lz_parse import parse_items

LZ77_TYPE = 0x10
MIN_MATCH = 3
MAX_MATCH = 18
WINDOW = 0x1000
MAX_SIZE = 0xFFFFFF
_CHAIN_LIMIT = 256


def compress_lz77(data: bytes, *, vram_safe: bool = True) -> bytes:
    """Greedy LZ77 compression; the output is padded to a multiple of 4 bytes."""
    if len(data) > MAX_SIZE:
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "LZ77 input exceeds 16 MiB")
    minimum_distance = 2 if vram_safe else 1
    output = bytearray((LZ77_TYPE, *len(data).to_bytes(3, "little")))
    chains: dict[bytes, list[int]] = {}
    position = 0
    while position < len(data):
        flag_index = len(output)
        output.append(0)
        for bit in range(8):
            if position >= len(data):
                break
            length, distance = _longest_match(data, position, chains, minimum_distance)
            if length >= MIN_MATCH:
                output[flag_index] |= 0x80 >> bit
                token = (length - MIN_MATCH) << 12 | (distance - 1)
                output += token.to_bytes(2, "big")
                step = length
            else:
                output.append(data[position])
                step = 1
            for offset in range(position, position + step):
                key = data[offset : offset + MIN_MATCH]
                if len(key) == MIN_MATCH:
                    chains.setdefault(key, []).append(offset)
            position += step
    output += bytes(-len(output) % 4)
    return bytes(output)


def compress_lz77_optimal(data: bytes, *, vram_safe: bool = True) -> bytes:
    """Optimally parsed LZ77; the output is padded to a multiple of 4 bytes."""
    if len(data) > MAX_SIZE:
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "LZ77 input exceeds 16 MiB")
    items = parse_items(data, min_distance=2 if vram_safe else 1, max_distance=WINDOW)
    output = bytearray((LZ77_TYPE, *len(data).to_bytes(3, "little")))
    flag_index = 0
    for number, (length, distance, literal) in enumerate(items):
        if number % 8 == 0:
            flag_index = len(output)
            output.append(0)
        if distance:
            output[flag_index] |= 0x80 >> number % 8
            token = (length - MIN_MATCH) << 12 | (distance - 1)
            output += token.to_bytes(2, "big")
        else:
            output.append(literal)
    output += bytes(-len(output) % 4)
    return bytes(output)


def _longest_match(
    data: bytes, position: int, chains: dict[bytes, list[int]], minimum_distance: int
) -> tuple[int, int]:
    key = data[position : position + MIN_MATCH]
    candidates = chains.get(key)
    if len(key) < MIN_MATCH or not candidates:
        return 0, 0
    best_length = 0
    best_distance = 0
    limit = min(MAX_MATCH, len(data) - position)
    for start in reversed(candidates[-_CHAIN_LIMIT:]):
        distance = position - start
        if distance > WINDOW:
            break
        if distance < minimum_distance:
            continue
        length = 0
        while length < limit and data[start + length] == data[position + length]:
            length += 1
        if length > best_length:
            best_length, best_distance = length, distance
            if length == limit:
                break
    return best_length, best_distance


def decompress_lz77(data: bytes) -> bytes:
    if len(data) < 4 or data[0] != LZ77_TYPE:
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "Not LZ77 (type 0x10) data")
    size = int.from_bytes(data[1:4], "little")
    output = bytearray()
    position = 4
    while len(output) < size:
        if position >= len(data):
            raise ClassicRetroError(
                ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "LZ77 data is cut short"
            )
        flags = data[position]
        position += 1
        for bit in range(8):
            if len(output) >= size:
                break
            if flags & 0x80 >> bit:
                if position + 2 > len(data):
                    raise ClassicRetroError(
                        ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "LZ77 data is cut short"
                    )
                token = int.from_bytes(data[position : position + 2], "big")
                position += 2
                length = (token >> 12) + MIN_MATCH
                distance = (token & 0xFFF) + 1
                if distance > len(output):
                    raise ClassicRetroError(
                        ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "LZ77 reference before the start"
                    )
                for _ in range(length):
                    output.append(output[-distance])
            else:
                if position >= len(data):
                    raise ClassicRetroError(
                        ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "LZ77 data is cut short"
                    )
                output.append(data[position])
                position += 1
    return bytes(output[:size])
