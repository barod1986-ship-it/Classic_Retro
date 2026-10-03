"""Nintendo 64 cartridge images: the byte order, the header and the boot checksum.

An N64 image is a stream of 32-bit big-endian words. A dump stores them in
one of three byte orders, told apart by the first word (``80 37 12 40`` as the
console reads it): ``z64`` keeps the words as they are, ``v64`` swaps the two
bytes of each 16-bit half (``37 80 40 12``) and ``n64`` stores each word
little-endian (``40 12 37 80``). Everything else here reads the ``z64`` order;
``to_big_endian`` gets there from any of the three.

The header is the first 0x40 bytes: PI configuration and clock rate, the
entry point at 0x08, the libultra version, the two check code words at 0x10
and 0x14, the title at 0x20 (20 bytes, ASCII, padded with spaces), the game
code at 0x3B (a category letter, two unique letters, a destination letter)
and the revision at 0x3F. The boot code (IPL3) follows at 0x40..0x1000. It
is one of a few variants, each paired with a CIC lockout chip and told apart
by the CRC-32 of its bytes; ``BOOT_CODES`` names the ones the toolkit knows.

The boot code computes a check code over the megabyte after it,
0x1000..0x101000, as big-endian words, and does not start an image whose
header words differ from it. For CIC-NUS-6102, the boot code of Super Mario
64 and most games, six accumulators start at the seed 0xF8CA4DDC and take
each word w in turn: t6 += w, and t4 counts the carries out of t6; t3 ^= w;
t5 += w rotated left by its low five bits; t2 ^= that rotation when t2 > w,
else t6 ^ w; t1 += t5 ^ w. The check code is (t6 ^ t4 ^ t3, t5 ^ t2 ^ t1),
everything mod 2**32. The other boot codes (6101, 6103, 6105, 6106) seed,
step or combine the accumulators differently and are not implemented:
``header_checksum`` refuses an image whose boot code it does not know rather
than compute a wrong pair.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

HEADER_SIZE = 0x40
ENTRY_POINT = 0x08
CHECKSUM = 0x10
TITLE = 0x20
TITLE_SIZE = 20
GAME_CODE = 0x3B
REVISION = 0x3F
BOOT_CODE_START = 0x40
BOOT_CODE_END = 0x1000
# The check code covers the megabyte after the boot code.
CHECKSUM_START = 0x1000
CHECKSUM_END = 0x101000

# The first word of an image as each byte order stores it.
MAGIC_Z64 = b"\x80\x37\x12\x40"
MAGIC_V64 = b"\x37\x80\x40\x12"
MAGIC_N64 = b"\x40\x12\x37\x80"
# How many bytes each order reverses at a time.
_SWAP_UNITS = {MAGIC_Z64: 1, MAGIC_V64: 2, MAGIC_N64: 4}

CIC_6102 = "CIC-NUS-6102"
# Known boot codes by the CRC-32 of their bytes (0x40..0x1000).
BOOT_CODES: dict[int, str] = {0x90BB6CB5: CIC_6102}
# The check code's seed, for the boot codes whose check code ``header_checksum``
# computes. Only 6102's steps are implemented; a boot code that steps or
# combines differently needs more than an entry here.
CHECKSUM_SEEDS: dict[str, int] = {CIC_6102: 0xF8CA4DDC}
_MASK = 0xFFFFFFFF


def to_big_endian(image: bytes) -> bytes:
    """``image`` in z64 order, from whichever of the three byte orders it is in."""
    unit = _SWAP_UNITS.get(bytes(image[:4]))
    if unit is None:
        raise ClassicRetroError(
            ErrorCode.INVALID_BYTE_RANGE, "Not a Nintendo 64 image in the z64, v64 or n64 order"
        )
    if len(image) % unit:
        raise ClassicRetroError(
            ErrorCode.INVALID_BYTE_RANGE,
            f"The image is {len(image)} bytes, not a whole number of {unit}-byte units",
        )
    if unit == 1:
        return bytes(image)
    swapped = bytearray(len(image))
    for position in range(unit):
        swapped[position::unit] = image[unit - 1 - position :: unit]
    return bytes(swapped)


@dataclass(frozen=True, slots=True)
class N64Header:
    """The fields of an N64 header the toolkit reads, from a z64 image."""

    entry_point: int
    checksum: tuple[int, int]
    title: str
    game_code: str
    revision: int

    @classmethod
    def read(cls, image: bytes) -> N64Header:
        if len(image) < HEADER_SIZE:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "An N64 header is 0x40 bytes")
        if image[:4] != MAGIC_Z64:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE, "The header is read from a z64 image (to_big_endian)"
            )
        crc1, crc2 = struct.unpack_from(">II", image, CHECKSUM)
        title = image[TITLE : TITLE + TITLE_SIZE].rstrip(b" \x00")
        return cls(
            entry_point=struct.unpack_from(">I", image, ENTRY_POINT)[0],
            checksum=(crc1, crc2),
            title=title.decode("ascii", errors="replace"),
            game_code=image[GAME_CODE : GAME_CODE + 4].decode("ascii", errors="replace"),
            revision=image[REVISION],
        )


def boot_code(image: bytes) -> str | None:
    """The name of the boot code at 0x40..0x1000 when it is a known one, else None."""
    if len(image) < BOOT_CODE_END:
        return None
    return BOOT_CODES.get(zlib.crc32(image[BOOT_CODE_START:BOOT_CODE_END]))


def header_checksum(image: bytes) -> tuple[int, int]:
    """The check code the boot code computes over 0x1000..0x101000 of a z64 image."""
    if len(image) < CHECKSUM_END:
        raise ClassicRetroError(
            ErrorCode.INVALID_BYTE_RANGE,
            f"The check code covers the image up to {CHECKSUM_END:#x}; it ends at {len(image):#x}",
        )
    seed = CHECKSUM_SEEDS.get(boot_code(image) or "")
    if seed is None:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The boot code is not one whose check code the toolkit computes (CIC-NUS-6102)",
        )
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    for (word,) in struct.iter_unpack(">I", image[CHECKSUM_START:CHECKSUM_END]):
        total = t6 + word
        if total > _MASK:
            t4 = (t4 + 1) & _MASK
        t6 = total & _MASK
        t3 ^= word
        shift = word & 0x1F
        rotated = ((word << shift) | (word >> (32 - shift))) & _MASK
        t5 = (t5 + rotated) & _MASK
        t2 ^= rotated if t2 > word else t6 ^ word
        t1 = (t1 + (t5 ^ word)) & _MASK
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def header_checksum_valid(image: bytes) -> bool:
    """Whether the header's check code words are the ones the boot code would compute."""
    return N64Header.read(image).checksum == header_checksum(image)


def with_header_checksum(image: bytes) -> bytes:
    """``image`` with the check code words at 0x10 and 0x14 computed again."""
    checksum = header_checksum(image)
    fixed = bytearray(image)
    struct.pack_into(">II", fixed, CHECKSUM, *checksum)
    return bytes(fixed)
