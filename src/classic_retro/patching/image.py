"""The pinned identity of an input image, and reading it by address."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

# Where the Game Boy Advance maps cartridge ROM.
GBA_ROM_BASE = 0x08000000


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """The one image an overlay accepts: its title, SHA-256, size and base address."""

    title: str
    sha256: str
    size: int
    base: int = GBA_ROM_BASE

    def verify(self, rom: bytes) -> None:
        if len(rom) != self.size or hashlib.sha256(rom).hexdigest() != self.sha256:
            raise ClassicRetroError(
                ErrorCode.UNKNOWN_GAME_REVISION,
                f"Input is not {self.title} with SHA-256 {self.sha256}",
            )

    def offset(self, address: int) -> int:
        return address - self.base

    def word(self, rom: bytes, address: int) -> int:
        (value,) = struct.unpack_from("<I", rom, self.offset(address))
        return value

    def read(self, rom: bytes, address: int, length: int) -> bytes:
        start = self.offset(address)
        return bytes(rom[start : start + length])

    def filled(self, rom: bytes, start: int, end: int, fill: int) -> bool:
        """Whether ``start``..``end`` (addresses) holds nothing but ``fill``."""
        region = rom[self.offset(start) : self.offset(end)]
        return region.count(fill) == len(region)

    def references(self, rom: bytes, addresses: Iterable[int]) -> dict[int, list[int]]:
        """Every aligned little-endian word of the image equal to one of ``addresses``."""
        found: dict[int, list[int]] = {address: [] for address in addresses}
        for number, (value,) in enumerate(struct.iter_unpack("<I", rom[: len(rom) & ~3])):
            if value in found:
                found[value].append(self.base + 4 * number)
        return found


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
