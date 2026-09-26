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

A NitroSDK ARM9 binary is followed in the image by a 12-byte footer whose
second word is the offset of its module parameters. They give the autoload
blocks: code and data the start-up code copies from the end of the binary to
fast memory (ITCM, DTCM) before it clears the static BSS. ``Arm9Binary``
reads them and grows a block, which is how an overlay adds code that stays in
memory whatever the game loads. The ARM9 overlay table (the overlays' load
addresses and files), which only the header points to, can move past the used
area (``move_arm9_overlay_table``) so the binary can grow into its place
(``replace_arm9``).
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
ARM9_OVERLAY_TABLE = 0x50
# The footer after a NitroSDK ARM9 binary: this magic, then the offset of the
# module parameters from the binary's start, then a third word.
NITROCODE = 0xDEC00621
ARM9_FOOTER_SIZE = 12
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
    arm7_offset: int
    arm7_size: int
    fnt_offset: int
    fnt_size: int
    fat_offset: int
    fat_size: int
    arm9_overlay_offset: int
    arm9_overlay_size: int
    arm7_overlay_offset: int
    arm7_overlay_size: int
    banner_offset: int
    used_size: int
    secure_area_crc: int
    logo_crc: int
    header_crc: int

    @classmethod
    def read(cls, image: bytes) -> NdsHeader:
        if len(image) < 0x200:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "A DS header is 0x200 bytes")
        arm9 = struct.unpack_from("<4I", image, 0x20)
        arm7 = struct.unpack_from("<4I", image, 0x30)
        fnt_fat = struct.unpack_from("<4I", image, 0x40)
        overlays = struct.unpack_from("<4I", image, ARM9_OVERLAY_TABLE)
        return cls(
            title=image[0:12].rstrip(b"\x00 ").decode("ascii", errors="replace"),
            game_code=image[12:16].decode("ascii", errors="replace"),
            maker_code=image[16:18].decode("ascii", errors="replace"),
            arm9_offset=arm9[0],
            arm9_entry=arm9[1],
            arm9_ram=arm9[2],
            arm9_size=arm9[3],
            arm7_offset=arm7[0],
            arm7_size=arm7[3],
            fnt_offset=fnt_fat[0],
            fnt_size=fnt_fat[1],
            fat_offset=fnt_fat[2],
            fat_size=fnt_fat[3],
            arm9_overlay_offset=overlays[0],
            arm9_overlay_size=overlays[1],
            arm7_overlay_offset=overlays[2],
            arm7_overlay_size=overlays[3],
            banner_offset=struct.unpack_from("<I", image, 0x68)[0],
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


@dataclass(frozen=True, slots=True)
class Overlay:
    """An entry of the ARM9 overlay table: where the overlay loads, and its file."""

    id: int
    ram: int
    size: int
    bss_size: int
    file_id: int


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

    def read(self, path: str | int) -> bytes:
        """A file's bytes, by path or by id (an overlay's file has no path)."""
        file_id = path if isinstance(path, int) else self.file_id(path)
        start, end = self.file_range(file_id)
        return bytes(self.image[start:end])

    def arm9(self) -> bytes:
        start = self.header.arm9_offset
        return bytes(self.image[start : start + self.header.arm9_size])

    def arm9_footer(self) -> bytes:
        """The 12 bytes after the ARM9 binary when they are a NitroSDK footer; else none."""
        end = self.header.arm9_offset + self.header.arm9_size
        footer = bytes(self.image[end : end + ARM9_FOOTER_SIZE])
        if len(footer) == ARM9_FOOTER_SIZE and struct.unpack_from("<I", footer)[0] == NITROCODE:
            return footer
        return b""

    def overlays(self) -> tuple[Overlay, ...]:
        """The ARM9 overlay table's entries, in order."""
        start = self.header.arm9_overlay_offset
        count = self.header.arm9_overlay_size // 32
        if start + 32 * count > len(self.image):
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "Overlay table out of the image")
        return tuple(
            Overlay(entry[0], entry[1], entry[2], entry[3], entry[6])
            for entry in (
                struct.unpack_from("<8I", self.image, start + 32 * n) for n in range(count)
            )
        )

    def next_region(self, start: int) -> int:
        """Where the next part the header or the FAT places after ``start`` begins.

        The parts are the binaries, the file system's tables, the overlay tables,
        the banner and every file; past the last one, the used size.
        """
        header = self.header
        starts = [header.arm9_offset, header.arm7_offset, header.fnt_offset, header.fat_offset]
        if header.arm9_overlay_size:
            starts.append(header.arm9_overlay_offset)
        if header.arm7_overlay_size:
            starts.append(header.arm7_overlay_offset)
        if header.banner_offset:
            starts.append(header.banner_offset)
        for file_id in range(header.file_count):
            begin, end = self.file_range(file_id)
            if end > begin:
                starts.append(begin)
        return min(
            (begin for begin in starts if begin > start), default=max(header.used_size, start)
        )


def _signature(image: bytes | bytearray, used: int) -> bytes:
    """The RSA signature right after the used area, if the image has one."""
    signature = bytes(image[used : used + SIGNATURE_SIZE])
    return signature if signature.startswith(SIGNATURE_MAGIC) else b""


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
    signature = _signature(image, used)
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


def move_arm9_overlay_table(image: bytearray) -> int:
    """Copy the ARM9 overlay table past the used area and point the header at it.

    The ARM9 binary may then grow over the table's old place (``replace_arm9``).
    The image's signature, if it has one, moves after the table; the used size
    and the header CRC follow. Returns where the table is now.
    """
    header = NdsHeader.read(image)
    used = header.used_size
    signature = _signature(image, used)
    start = header.arm9_overlay_offset
    table = bytes(image[start : start + header.arm9_overlay_size])
    moved = -(-used // FILE_ALIGNMENT) * FILE_ALIGNMENT
    stop = moved + len(table)
    if stop + len(signature) > len(image):
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW, "The ARM9 overlay table does not fit in the image"
        )
    image[used:moved] = b"\xff" * (moved - used)
    image[moved:stop] = table
    image[stop : stop + len(signature)] = signature
    struct.pack_into("<I", image, ARM9_OVERLAY_TABLE, moved)
    struct.pack_into("<I", image, USED_SIZE, stop)
    set_header_crc(image)
    return moved


def replace_arm9(image: bytearray, arm9: bytes) -> None:
    """Write ``arm9`` over the ARM9 binary, with its footer after it.

    The binary may grow up to the next part of the image (``NitroImage.next_region``):
    move the ARM9 overlay table first when it follows the binary. A smaller binary
    leaves 0xFF behind it. The header's ARM9 size and CRC follow.
    """
    nitro = NitroImage(bytes(image))
    header = nitro.header
    footer = nitro.arm9_footer()
    start = header.arm9_offset
    old_end = start + header.arm9_size + len(footer)
    new_end = start + len(arm9) + len(footer)
    limit = nitro.next_region(start)
    if new_end > limit:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The ARM9 binary needs {new_end - start:#x} bytes; {limit - start:#x} are free",
        )
    image[start:new_end] = arm9 + footer
    image[new_end:old_end] = b"\xff" * max(0, old_end - new_end)
    struct.pack_into("<I", image, ARM9_SIZE, len(arm9))
    set_header_crc(image)


# ---------------------------------------------------------------------------
# The ARM9 binary's autoload blocks


@dataclass(frozen=True, slots=True)
class Autoload:
    """An autoload block: copied to ``address`` (``size`` bytes), then ``bss`` zeroed."""

    address: int
    size: int
    bss: int


@dataclass(frozen=True, slots=True)
class Arm9Binary:
    """An uncompressed NitroSDK ARM9 binary loaded at ``ram``, and its module parameters.

    The module parameters start with the autoload table's start and end and
    the first block's data (addresses); their sixth word is where a compressed
    binary's packed part ends, zero for one stored as it runs. The blocks' data
    follows the static code, in the table's order, and the table follows them.
    """

    data: bytes
    ram: int
    params_offset: int

    @classmethod
    def from_image(cls, nitro: NitroImage) -> Arm9Binary:
        footer = nitro.arm9_footer()
        if not footer:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE, "The ARM9 binary has no NitroSDK footer"
            )
        binary = cls(nitro.arm9(), nitro.header.arm9_ram, struct.unpack_from("<I", footer, 4)[0])
        binary.autoloads()
        return binary

    def _params(self) -> tuple[int, ...]:
        if not 0 <= self.params_offset <= len(self.data) - 24:
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "No ARM9 module parameters")
        return struct.unpack_from("<6I", self.data, self.params_offset)

    @property
    def autoload_table(self) -> tuple[int, int]:
        """Where the table of autoload blocks is (addresses), start and end."""
        start, end = self._params()[:2]
        return start, end

    @property
    def autoload_start(self) -> int:
        """Where the first block's data is (an address): the end of the static code."""
        return self._params()[2]

    def offset(self, address: int) -> int:
        offset = address - self.ram
        if not 0 <= offset <= len(self.data):
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"{address:#x} is outside the ARM9 binary"
            )
        return offset

    def autoloads(self) -> tuple[Autoload, ...]:
        if self._params()[5]:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE,
                "The ARM9 binary is compressed; unpack it first (rebuild.blz)",
            )
        start, end = self.autoload_table
        table = self.offset(start)
        if end < start or (end - start) % 12 or table + (end - start) > len(self.data):
            raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "Bad ARM9 autoload table")
        blocks = tuple(
            Autoload(*struct.unpack_from("<III", self.data, table + 12 * number))
            for number in range((end - start) // 12)
        )
        if self.offset(self.autoload_start) + sum(block.size for block in blocks) != table:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE, "The autoload blocks do not end at their table"
            )
        return blocks

    def block_data_offset(self, index: int) -> int:
        """Where block ``index``'s data starts in the binary."""
        return self.offset(self.autoload_start) + sum(
            block.size for block in self.autoloads()[:index]
        )

    def read(self, address: int, length: int) -> bytes:
        start = self.offset(address)
        return self.data[start : start + length]

    def patched(self, writes: Mapping[int, bytes]) -> Arm9Binary:
        """The binary with ``writes`` (address: bytes) applied to its static code."""
        data = bytearray(self.data)
        static_end = self.offset(self.autoload_start)
        for address, chunk in writes.items():
            start = self.offset(address)
            if start + len(chunk) > static_end:
                raise ClassicRetroError(
                    ErrorCode.WRITE_OUT_OF_BOUNDS, f"{address:#x} is not in the static ARM9 code"
                )
            data[start : start + len(chunk)] = chunk
        return Arm9Binary(bytes(data), self.ram, self.params_offset)

    def with_block_grown(self, index: int, data: bytes) -> Arm9Binary:
        """Block ``index`` with ``data`` after its bytes; the later blocks and the table move.

        The block must have no BSS, which would move with its end: its code and
        data keep their addresses, and ``data`` lands at the block's old end.
        """
        blocks = list(self.autoloads())
        block = blocks[index]
        if block.bss:
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW, "Growing an autoload block with a BSS would move it"
            )
        insert = self.block_data_offset(index) + block.size
        grown = bytearray(self.data[:insert] + data + self.data[insert:])
        blocks[index] = Autoload(block.address, block.size + len(data), block.bss)
        start, end = self.autoload_table
        table = self.offset(start) + len(data)
        for number, entry in enumerate(blocks):
            struct.pack_into(
                "<III", grown, table + 12 * number, entry.address, entry.size, entry.bss
            )
        struct.pack_into("<II", grown, self.params_offset, start + len(data), end + len(data))
        return Arm9Binary(bytes(grown), self.ram, self.params_offset)


# ---------------------------------------------------------------------------
# NARC archives


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

    def member(self, data: bytes, index: int) -> bytes:
        """File ``index``'s bytes, from the data the archive was read from."""
        start, end = self.ranges[index]
        return bytes(data[self.data_offset + start : self.data_offset + end])

    def rebuilt(self, data: bytes, members: Mapping[int, bytes]) -> bytes:
        """The archive's bytes with ``members`` (by index) replaced, one after another.

        A member stays where it was when it fits up to the next member's start
        (or the end of the data), 0xFF after it; else it goes after the last
        member, 4-byte aligned with 0xFF between, and its old place stays as it
        was. The other members keep their offsets. The file table, the data's
        size and the archive's size follow; everything else is kept as read, so
        an archive rebuilt with no change is the same bytes.
        """
        gmif_size = struct.unpack_from("<I", data, self.data_offset - 4)[0]
        if self.data_offset - 8 + gmif_size != self.offset + self.size:
            raise ClassicRetroError(
                ErrorCode.CONTAINER_REBUILD_FAILED, "The NARC's data is not its last block"
            )
        body = bytearray(data[self.data_offset : self.offset + self.size])
        ranges = list(self.ranges)
        for index, member in members.items():
            if not 0 <= index < len(ranges):
                raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No NARC member {index}")
            start, end = ranges[index]
            room = min((other for other, _ in ranges if other > start), default=_aligned(len(body)))
            if start + len(member) <= room:
                body[start : start + len(member)] = member
                body[start + len(member) : end] = b"\xff" * max(0, end - start - len(member))
            else:
                body += b"\xff" * (_aligned(len(body)) - len(body))
                start = len(body)
                body += member
            ranges[index] = (start, start + len(member))
        body += b"\xff" * (_aligned(len(body)) - len(body))
        head = bytearray(data[self.offset : self.data_offset])
        for number, (start, end) in enumerate(ranges):
            struct.pack_into("<II", head, self.fat_offset - self.offset + 8 * number, start, end)
        struct.pack_into("<I", head, len(head) - 4, 8 + len(body))
        struct.pack_into("<I", head, 8, len(head) + len(body))
        return bytes(head + body)


def _aligned(length: int) -> int:
    """``length`` up to a multiple of 4: NARC members start on words."""
    return (length + 3) & ~3
