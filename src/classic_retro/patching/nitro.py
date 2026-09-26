"""Nintendo DS cartridge images: the header, the NitroFS file system, NARC archives.

A DS image starts with a header that locates everything else: the ARM9 and
ARM7 binaries, the file name table (FNT) and the file allocation table (FAT)
of its file system, and how far the image is used. The FAT gives each file id
a start and an end in the image; the FNT gives the directories their files
and names. A NARC archive holds a small file system of its own in the same
formats (``BTAF`` is its FAT, ``BTNF`` its FNT, ``GMIF`` its file data).

The header carries two CRC-16 checksums (the MODBUS variant): one of the
header itself (``0x15E``, over ``0x000..0x15D``) and one of the secure area
(``0x6C``, over the first 0x4000 bytes of the ARM9, at 0x4000 of the image)
as the cartridge stores it: its first 2 KiB are encrypted there. A dump keeps
them decrypted, so the secure area's CRC cannot be computed again from the
dump; ``secure_area_crc`` updates it from the bytes that changed instead,
which works because a CRC is linear and the encrypted bytes never change.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

HEADER_CRC = 0x15E
HEADER_CRC_END = 0x15E
LOGO_CRC = 0x15C
NINTENDO_LOGO_CRC = 0xCF56
SECURE_AREA_CRC = 0x6C
SECURE_AREA_START = 0x4000
SECURE_AREA_END = 0x8000
# The first 2 KiB of the secure area are encrypted on a cartridge.
ENCRYPTED_SECURE_AREA_END = 0x4800
USED_SIZE = 0x80
ARM9_SIZE = 0x2C
# The RSA signature some images keep right after their used area (DS Download
# Play checks it): "ac", 0x01 0x00, then 0x84 bytes.
SIGNATURE_MAGIC = b"ac\x01\x00"
SIGNATURE_SIZE = 0x88
# Where a file that outgrows its place goes: past the used area, aligned.
FILE_ALIGNMENT = 0x200


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/MODBUS, the checksum of the DS header and secure area."""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


@dataclass(frozen=True, slots=True)
class NdsHeader:
    """The fields of a DS header the toolkit reads."""

    title: str
    game_code: str
    maker_code: str
    arm9_offset: int
    arm9_entry: int
    arm9_ram: int
    arm9_size: int
    fnt_offset: int
    fnt_size: int
    fat_offset: int
    fat_size: int
    used_size: int
    secure_area_crc: int
    logo_crc: int
    header_crc: int

    @classmethod
    def read(cls, image: bytes) -> NdsHeader:
        if len(image) < 0x200:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "A DS header is 0x200 bytes")
        arm9 = struct.unpack_from("<4I", image, 0x20)
        fnt_fat = struct.unpack_from("<4I", image, 0x40)
        return cls(
            title=image[0:12].rstrip(b"\x00 ").decode("ascii", errors="replace"),
            game_code=image[12:16].decode("ascii", errors="replace"),
            maker_code=image[16:18].decode("ascii", errors="replace"),
            arm9_offset=arm9[0],
            arm9_entry=arm9[1],
            arm9_ram=arm9[2],
            arm9_size=arm9[3],
            fnt_offset=fnt_fat[0],
            fnt_size=fnt_fat[1],
            fat_offset=fnt_fat[2],
            fat_size=fnt_fat[3],
            used_size=struct.unpack_from("<I", image, USED_SIZE)[0],
            secure_area_crc=struct.unpack_from("<H", image, SECURE_AREA_CRC)[0],
            logo_crc=struct.unpack_from("<H", image, LOGO_CRC)[0],
            header_crc=struct.unpack_from("<H", image, HEADER_CRC)[0],
        )

    @property
    def file_count(self) -> int:
        return self.fat_size // 8


def header_crc_valid(image: bytes) -> bool:
    return crc16(image[:HEADER_CRC_END]) == struct.unpack_from("<H", image, HEADER_CRC)[0]


def set_header_crc(image: bytearray) -> None:
    struct.pack_into("<H", image, HEADER_CRC, crc16(image[:HEADER_CRC_END]))


def secure_area_crc(original: bytes, changed: bytes, stored_crc: int) -> int:
    """The secure area's CRC after ``original`` became ``changed`` (both whole images).

    Only the unencrypted part may change. For messages of one length a CRC
    is affine: crc(a ^ b) = crc(a) ^ crc(b) ^ crc(zeros), so the new CRC is the
    stored one with the CRC of the difference and of zeros added.
    """
    before = original[SECURE_AREA_START:SECURE_AREA_END]
    after = changed[SECURE_AREA_START:SECURE_AREA_END]
    encrypted = ENCRYPTED_SECURE_AREA_END - SECURE_AREA_START
    if before[:encrypted] != after[:encrypted]:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The encrypted part of the secure area cannot change",
        )
    difference = bytes(a ^ b for a, b in zip(before, after, strict=True))
    zeros = bytes(len(difference))
    return stored_crc ^ crc16(difference) ^ crc16(zeros)


def file_name_table(data: bytes, base: int = 0) -> dict[str, int]:
    """Every file's path ("dir/name") and id, from an FNT at ``base``."""
    directories = struct.unpack_from("<H", data, base + 6)[0]
    if directories == 0 or base + 8 * directories > len(data):
        raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "Invalid file name table")
    paths: dict[str, int] = {}

    def walk(directory: int, prefix: str, depth: int) -> None:
        if depth > directories:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "File name table loops")
        entry = base + 8 * directory
        table, first_file = struct.unpack_from("<IH", data, entry)
        position = base + table
        file_id = first_file
        while True:
            if position >= len(data):
                raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "File name table is cut")
            kind = data[position]
            position += 1
            if kind == 0:
                return
            length = kind & 0x7F
            name = data[position : position + length].decode("ascii", errors="replace")
            position += length
            if kind & 0x80:
                (subdirectory,) = struct.unpack_from("<H", data, position)
                position += 2
                walk(subdirectory & 0x0FFF, f"{prefix}{name}/", depth + 1)
            else:
                paths[f"{prefix}{name}"] = file_id
                file_id += 1

    walk(0, "", 0)
    return paths


class NitroImage:
    """A DS image's header and file system, read from its bytes."""

    def __init__(self, image: bytes) -> None:
        self.image = image
        self.header = NdsHeader.read(image)
        header = self.header
        if header.fat_offset + header.fat_size > len(image) or (
            header.fnt_offset + header.fnt_size > len(image)
        ):
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "FAT or FNT out of the image")
        self.paths = file_name_table(image[header.fnt_offset : header.fnt_offset + header.fnt_size])

    def file_id(self, path: str) -> int:
        try:
            return self.paths[path]
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"No file {path} in the image"
            ) from None

    def file_range(self, file_id: int) -> tuple[int, int]:
        if not 0 <= file_id < self.header.file_count:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No file id {file_id}")
        start, end = struct.unpack_from("<II", self.image, self.header.fat_offset + 8 * file_id)
        if not start <= end <= len(self.image):
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, f"File {file_id} out of range")
        return start, end

    def read(self, path: str) -> bytes:
        start, end = self.file_range(self.file_id(path))
        return bytes(self.image[start:end])


def replace_files(image: bytearray, files: Mapping[int, bytes]) -> dict[int, tuple[int, int]]:
    """Write ``files`` (by id) into ``image`` and point the FAT at them.

    A file no longer than it was stays where it was, the rest of its place
    filled with 0xFF; a longer one goes past the used area, and the image's
    signature, if it has one, moves after it. The used size and the header
    CRC follow. Returns every written file's new start and end.
    """
    nitro = NitroImage(bytes(image))
    header = nitro.header
    used = header.used_size
    signature = bytes(image[used : used + SIGNATURE_SIZE])
    if not signature.startswith(SIGNATURE_MAGIC):
        signature = b""
    placed: dict[int, tuple[int, int]] = {}
    end_of_data = used
    for file_id, data in sorted(files.items()):
        start, end = nitro.file_range(file_id)
        if len(data) <= end - start:
            image[start:end] = data + b"\xff" * (end - start - len(data))
            placed[file_id] = (start, start + len(data))
            continue
        start = -(-end_of_data // FILE_ALIGNMENT) * FILE_ALIGNMENT
        stop = start + len(data)
        if stop + len(signature) > len(image):
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW, f"File {file_id} does not fit in the image"
            )
        image[end_of_data:start] = b"\xff" * (start - end_of_data)
        image[start:stop] = data
        placed[file_id] = (start, stop)
        end_of_data = stop
    for file_id, (start, stop) in placed.items():
        struct.pack_into("<II", image, header.fat_offset + 8 * file_id, start, stop)
    if end_of_data != used:
        image[end_of_data : end_of_data + len(signature)] = signature
        struct.pack_into("<I", image, USED_SIZE, end_of_data)
    set_header_crc(image)
    return placed


@dataclass(frozen=True, slots=True)
class Narc:
    """A NARC archive at ``offset`` in some data: its files by path and their ranges."""

    offset: int
    size: int
    fat_offset: int
    data_offset: int
    ranges: tuple[tuple[int, int], ...]
    paths: Mapping[str, int]

    @classmethod
    def read(cls, data: bytes, offset: int = 0) -> Narc:
        magic, bom, _, size, header_size, blocks = struct.unpack_from("<4sHHIHH", data, offset)
        if magic != b"NARC" or bom != 0xFFFE or blocks != 3:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, f"No NARC at {offset:#x}")
        found: dict[bytes, tuple[int, int]] = {}
        position = offset + header_size
        for _ in range(blocks):
            block, block_size = struct.unpack_from("<4sI", data, position)
            found[block] = (position, block_size)
            position += block_size
        if set(found) != {b"BTAF", b"BTNF", b"GMIF"} or position > offset + size:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "NARC blocks are not as known")
        fat, _ = found[b"BTAF"]
        (count,) = struct.unpack_from("<H", data, fat + 8)
        ranges = tuple(struct.unpack_from("<II", data, fat + 12 + 8 * n) for n in range(count))
        names, names_size = found[b"BTNF"]
        paths = file_name_table(data[names + 8 : names + names_size])
        return cls(
            offset=offset,
            size=size,
            fat_offset=fat + 12,
            data_offset=found[b"GMIF"][0] + 8,
            ranges=ranges,
            paths=paths,
        )

    def file_id(self, path: str) -> int:
        try:
            return self.paths[path]
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"No file {path} in the NARC"
            ) from None

    def file_range(self, path: str) -> tuple[int, int]:
        """Where ``path``'s data starts and ends in the data the archive was read from."""
        start, end = self.ranges[self.file_id(path)]
        return self.data_offset + start, self.data_offset + end

    def room(self, path: str) -> int:
        """How far a file may grow: up to the next file's start, or the end of the data."""
        file_id = self.file_id(path)
        start = self.ranges[file_id][0]
        later = [begin for begin, _ in self.ranges if begin > start]
        limit = min(later) if later else self.size - (self.data_offset - self.offset)
        return limit - start

    def set_end(self, data: bytearray, path: str, end: int) -> None:
        """Point ``path``'s FAT entry at a new end (``end`` in the data's offsets)."""
        file_id = self.file_id(path)
        struct.pack_into("<I", data, self.fat_offset + 8 * file_id + 4, end - self.data_offset)
