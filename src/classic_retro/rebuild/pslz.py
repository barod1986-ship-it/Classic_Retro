"""PSLZ, the packing of *Gran Turismo*'s executables (PlayStation).

GTMAIN.EXE, the race program, is a PS-X EXE whose text holds the program
packed. Its entry point is a stub with a header of seven words before it:
``"PSLZ"``, the image's last byte, the image's size, the stream's last byte,
where the stub copies itself, the stub's size and the image's entry point. The
stub copies itself above the image and unpacks the image in place, from the
top down: it reads the stream backwards from its last byte and writes the
image backwards from its last byte. Before each flags byte but the first and
before each item it checks that it still reads below where it writes, and
stops when it does not: what lies below is the image's start, stored as it
is. Read from its end, the stream is GT-ZIP (``rebuild.gtzip``) of the image
read from its end.

The stub reads the whole stream and stops right after it when the items
before each check have saved (their output minus their input, flags bytes
counted) less than the whole stream does.

``repack_pslz`` packs a changed image in its original's place with
``gtzip.repack_items``: the stream keeps its length and its bytes but around
the changes, so a patch carries the changes and not the program.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.gtzip import (
    GROUP,
    MIN_MATCH,
    NEAR,
    Item,
    decode_items,
    item_size,
    parse_items,
    repack_items,
    write_items,
)

EXE_MAGIC = b"PS-X EXE"
EXE_HEADER = 0x800
PSLZ_MAGIC = b"PSLZ"
HEADER_SIZE = 0x1C


@dataclass(frozen=True, slots=True)
class PslzExecutable:
    """A packed PS-X EXE: where its text loads and what its stub's header says."""

    load: int
    text_size: int
    header: int
    image_end: int
    image_size: int
    stream_end: int
    stub_address: int
    stub_size: int
    entry: int

    def offset(self, address: int) -> int:
        """Where the byte at ``address`` of the text lies in the file."""
        return EXE_HEADER + address - self.load


def _refuse(message: str) -> ClassicRetroError:
    return ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, message)


def read_pslz(exe: bytes) -> PslzExecutable:
    """The packed executable's layout; anything else is refused."""
    if len(exe) < EXE_HEADER or exe[:8] != EXE_MAGIC:
        raise _refuse("Not a PS-X EXE")
    pc0, _, load, text_size = struct.unpack_from("<IIII", exe, 0x10)
    header = pc0 - HEADER_SIZE
    if len(exe) < EXE_HEADER + text_size or not load <= header <= load + text_size - HEADER_SIZE:
        raise _refuse("The executable's entry point is not in its text")
    fields = struct.unpack_from("<4s6I", exe, EXE_HEADER + header - load)
    magic, image_end, image_size, stream_end, stub_address, stub_size, entry = fields
    if magic != PSLZ_MAGIC:
        raise _refuse("The executable is not packed with PSLZ")
    if image_end + 1 - image_size != load or not load <= stream_end < header:
        raise _refuse("The PSLZ header does not fit the executable")
    return PslzExecutable(
        load, text_size, header, image_end, image_size, stream_end, stub_address, stub_size, entry
    )


def _decode(exe: bytes, info: PslzExecutable) -> tuple[int, list[Item]]:
    """The stored part's size and the stream's items, read as the stub reads them."""
    text = exe[EXE_HEADER : EXE_HEADER + info.text_size]
    source = info.stream_end - info.load
    destination = info.image_end - info.load

    def byte(at: int) -> int:
        if at < 0:
            raise _refuse("PSLZ stream runs below the executable's text")
        return text[at]

    items: list[Item] = []
    while True:
        flags = byte(source)
        source -= 1
        for bit in range(GROUP):
            if not source < destination:
                return destination + 1, items
            if not flags >> bit & 1:
                items.append((1, 0, byte(source)))
                source -= 1
                destination -= 1
                continue
            length = byte(source) + MIN_MATCH
            value = byte(source - 1)
            width = 1
            if value & NEAR:
                value = (value & 0x7F) << 8 | byte(source - 2)
                width = 2
            source -= 1 + width
            items.append((length, value + 1, width))
            destination -= length
            if destination < source:
                raise _refuse("PSLZ stream would overwrite itself")
        if not source < destination:
            return destination + 1, items


def unpack_pslz(exe: bytes) -> bytes:
    """The image the stub unpacks, from the load address to the image's end."""
    info = read_pslz(exe)
    stored, items = _decode(exe, info)
    output = decode_items(items)
    if len(output) != info.image_size - stored:
        raise _refuse("PSLZ stream does not make the image")
    return exe[EXE_HEADER : EXE_HEADER + stored] + output[::-1]


def unpack_in_place(exe: bytes) -> bytes:
    """Unpack as the stub does, in one buffer from the load address to the image's end.

    The stream is read from the same memory the image is written to, so a
    stream that would overwrite what it has not read yet unpacks wrong here as
    it would on the console.
    """
    info = read_pslz(exe)
    memory = bytearray(info.image_size)
    text = exe[EXE_HEADER : EXE_HEADER + min(info.text_size, info.image_size)]
    memory[: len(text)] = text
    source = info.stream_end - info.load
    destination = info.image_end - info.load

    def byte(at: int) -> int:
        if at < 0:
            raise _refuse("PSLZ stream runs below the executable's text")
        return memory[at]

    try:
        while True:
            flags = byte(source)
            source -= 1
            for bit in range(GROUP):
                if not source < destination:
                    return bytes(memory)
                if not flags >> bit & 1:
                    memory[destination] = byte(source)
                    source -= 1
                    destination -= 1
                    continue
                length = byte(source) + MIN_MATCH
                value = byte(source - 1)
                source -= 2
                if value & NEAR:
                    value = (value & 0x7F) << 8 | byte(source)
                    source -= 1
                at = destination + value + 1
                for _ in range(length):
                    memory[destination] = memory[at]
                    at -= 1
                    destination -= 1
            if not source < destination:
                return bytes(memory)
    except IndexError:
        raise _refuse("PSLZ match reaches past the image") from None


def _savings(items: Sequence[Item]) -> list[int]:
    """The bytes saved after each item: its output minus the stream read, flags bytes counted."""
    saved = []
    total = 0
    for number, item in enumerate(items):
        if number % GROUP == 0:
            total -= 1
        total += item[0] - item_size(item)
        saved.append(total)
    return saved


def unpacks_in_place(items: Sequence[Item]) -> bool:
    """Whether the stub reads every item and stops right after the last.

    Its check before an item, or before a flags byte, holds while the items
    before it saved less than the whole stream does; the first check follows
    the first flags byte (a saving of -1).
    """
    saved = _savings(items)
    return bool(saved) and max([-1, *saved[:-1]]) < saved[-1]


def pack_pslz(image: bytes) -> tuple[int, bytes]:
    """``image`` packed for the stub: the size of the stored part, and the stream as it lies
    in memory after it (the stub reads its last byte first).

    The stream ends after the item where the saving first peaks, so every
    check before it saved less; the image's start below stays stored.
    """
    items = parse_items(image[::-1])
    saved = _savings(items)
    if not saved or max(saved) <= 0:
        raise _refuse("Nothing in the image packs")
    kept = items[: saved.index(max(saved)) + 1]
    stored = len(image) - sum(length for length, _, _ in kept)
    return stored, write_items(kept)[::-1]


def packed_executable(exe: bytes, image: bytes, stored: int, stream: bytes) -> bytes:
    """``exe`` with ``image``'s stored part and ``stream`` in its text below the header."""
    info = read_pslz(exe)
    if len(image) != info.image_size or info.load + stored + len(stream) > info.header:
        raise _refuse("The packed image does not fit below the PSLZ header")
    output = bytearray(exe)
    below = info.offset(info.header)
    output[EXE_HEADER:below] = bytes(below - EXE_HEADER)
    output[EXE_HEADER : EXE_HEADER + stored] = image[:stored]
    output[EXE_HEADER + stored : EXE_HEADER + stored + len(stream)] = stream
    struct.pack_into("<I", output, below + 12, info.load + stored + len(stream) - 1)
    return bytes(output)


def repack_pslz(original: bytes, image: bytes) -> bytes:
    """``image`` packed in the place of ``original``'s: the same stored part's size and
    stream length, and the same bytes but around the changes."""
    info = read_pslz(original)
    stored, items = _decode(original, info)
    if len(image) != info.image_size:
        raise _refuse("The changed image has another length")
    result = repack_items(items, image[stored:][::-1])
    if not unpacks_in_place(result):
        raise _refuse("The repacked image could not be unpacked in place")
    stream = write_items(result)[::-1]
    output = bytearray(original)
    output[EXE_HEADER : EXE_HEADER + stored] = image[:stored]
    output[EXE_HEADER + stored : EXE_HEADER + stored + len(stream)] = stream
    if info.load + stored + len(stream) - 1 != info.stream_end:
        raise _refuse("The repacked stream changed its length")
    if unpack_in_place(bytes(output)) != image:
        raise _refuse("The repacked executable does not unpack to the image")
    return bytes(output)
