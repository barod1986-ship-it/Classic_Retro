"""Raw CD-ROM data tracks: Mode 2 sectors, their EDC and ECC, and ISO 9660 file records.

A disc's data track, as a CDRWIN BIN file holds it, is a run of 2352-byte
sectors. Each starts with a 12-byte sync pattern and a 4-byte header: the
sector's address as BCD minutes, seconds and frames (LBA 0 is 00:02:00, 150
frames in) and the mode. A CD-ROM XA Mode 2 sector, the kind a PlayStation
disc holds, goes on with an 8-byte subheader: file, channel, submode and
coding, written twice. A Form 1 sector (submode bit 5 clear) then holds 2048
bytes of data, an EDC and 276 bytes of ECC:

- the EDC is a CRC-32 (polynomial 0x8001801B, reflected, no inversion) of the
  subheader and the data, stored little-endian;
- the ECC is the Reed-Solomon product code of ECMA-130 annex A: 172 bytes of P
  parity over the header, subheader, data and EDC, then 104 bytes of Q parity
  over those and P. A Mode 2 sector computes both as though its header were
  zero, so a sector moved elsewhere on the disc keeps its EDC and ECC.

A drive corrects what it reads through these codes, so every sector written
back gets both (``form1_sector``). ``RawTrack`` holds a whole track in memory,
reads the data of a run of sectors and rewrites them, and tells a run of empty
sectors (zeros after a valid header, the gap the mastering left) from used
ones. ``iso_file`` finds a file's directory record in the track's ISO 9660
file system and ``set_file_extent`` points it at other sectors, which is how a
file that grows moves to free sectors. A game that finds its files by sector,
from tables of its own, needs those tables repointed too: that is the work of
the game's overlay.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

SECTOR_SIZE = 2352
DATA_SIZE = 2048
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"
# The first sector of the program area is 00:02:00.
LBA_FRAMES = 150
MODE2 = 2
_HEADER = slice(12, 16)
_SUBHEADER = slice(16, 24)
_DATA = slice(24, 24 + DATA_SIZE)
_EDC = slice(2072, 2076)
_ECC = slice(2076, SECTOR_SIZE)
# Subheader submode bits (CD-ROM XA).
SUBMODE_EOR = 0x01
SUBMODE_DATA = 0x08
SUBMODE_FORM2 = 0x20
SUBMODE_EOF = 0x80

# ISO 9660: the primary volume descriptor's sector, and where its fields are.
PVD_LBA = 16
_PVD_VOLUME_SPACE = 80
_PVD_ROOT_RECORD = 156
# Directory record fields: extent and data length, little- then big-endian.
_RECORD_EXTENT = 2
_RECORD_SIZE = 10
_RECORD_FLAGS = 25
_RECORD_NAME_LENGTH = 32
_RECORD_NAME = 33
_DIRECTORY = 0x02


def _edc_table() -> tuple[int, ...]:
    table = []
    for value in range(256):
        for _ in range(8):
            value = value >> 1 ^ (0xD8018001 if value & 1 else 0)
        table.append(value)
    return tuple(table)


_EDC_TABLE = _edc_table()


def edc(data: bytes) -> int:
    """The CD-ROM EDC of ``data``."""
    value = 0
    for byte in data:
        value = value >> 8 ^ _EDC_TABLE[(value ^ byte) & 0xFF]
    return value


def _ecc_tables() -> tuple[bytes, bytes]:
    forward = bytearray(256)
    backward = bytearray(256)
    for value in range(256):
        doubled = (value << 1 ^ (0x11D if value & 0x80 else 0)) & 0xFF
        forward[value] = doubled
        backward[value ^ doubled] = value
    return bytes(forward), bytes(backward)


_ECC_F, _ECC_B = _ecc_tables()


def _parity(
    source: bytes, major_count: int, minor_count: int, major_mult: int, minor_inc: int
) -> bytes:
    """One of the two parity blocks: ``2 * major_count`` bytes over ``source``."""
    size = major_count * minor_count
    low = bytearray(major_count)
    high = bytearray(major_count)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = ecc_b = 0
        for _ in range(minor_count):
            value = source[index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a = _ECC_F[ecc_a ^ value]
            ecc_b ^= value
        ecc_a = _ECC_B[_ECC_F[ecc_a] ^ ecc_b]
        low[major] = ecc_a
        high[major] = ecc_a ^ ecc_b
    return bytes(low + high)


def ecc(sector: bytes) -> bytes:
    """The 276 bytes of P and Q parity of a Mode 2 Form 1 ``sector`` (its header read as zero)."""
    if len(sector) < _ECC.start:
        raise ValueError("a sector is 2352 bytes")
    covered = bytes(4) + bytes(sector[16 : _ECC.start])
    p_parity = _parity(covered, 86, 24, 2, 86)
    q_parity = _parity(covered + p_parity, 52, 43, 86, 88)
    return p_parity + q_parity


def bcd(value: int) -> int:
    return value // 10 << 4 | value % 10


def header(lba: int, mode: int = MODE2) -> bytes:
    """The 4-byte header of the sector at ``lba``: its minute, second and frame, then the mode."""
    minutes, frames = divmod(lba + LBA_FRAMES, 75 * 60)
    seconds, frames = divmod(frames, 75)
    if not 0 <= minutes < 100:
        raise ClassicRetroError(ErrorCode.WRITE_OUT_OF_BOUNDS, f"LBA {lba} has no address")
    return bytes((bcd(minutes), bcd(seconds), bcd(frames), mode))


def subheader(submode: int, file: int = 0, channel: int = 0, coding: int = 0) -> bytes:
    return bytes((file, channel, submode, coding)) * 2


def form1_sector(lba: int, data: bytes, sub: bytes = subheader(SUBMODE_DATA)) -> bytes:
    """A whole Mode 2 Form 1 sector: sync, header, subheader, ``data``, EDC and ECC."""
    if len(data) != DATA_SIZE:
        raise ValueError("a Form 1 sector holds 2048 bytes")
    if len(sub) != 8 or sub[:4] != sub[4:] or sub[2] & SUBMODE_FORM2:
        raise ValueError("a Form 1 subheader is four bytes twice, form bit clear")
    body = sub + data
    sector = SYNC + header(lba) + body + struct.pack("<I", edc(body))
    return sector + ecc(sector)


def check_form1(sector: bytes, lba: int) -> None:
    """Refuse a sector that is not a sound Mode 2 Form 1 sector at ``lba``."""
    if len(sector) != SECTOR_SIZE or sector[:12] != SYNC or sector[_HEADER] != header(lba):
        raise ClassicRetroError(ErrorCode.INVALID_MEDIA_LAYOUT, f"No Mode 2 sector at LBA {lba}")
    sub = sector[_SUBHEADER]
    if sub[:4] != sub[4:] or sub[2] & SUBMODE_FORM2:
        raise ClassicRetroError(ErrorCode.INVALID_MEDIA_LAYOUT, f"LBA {lba} is not Form 1")
    if struct.unpack("<I", sector[_EDC])[0] != edc(sector[16 : _EDC.start]):
        raise ClassicRetroError(ErrorCode.INVALID_MEDIA_LAYOUT, f"LBA {lba}: EDC mismatch")
    if sector[_ECC] != ecc(sector):
        raise ClassicRetroError(ErrorCode.INVALID_MEDIA_LAYOUT, f"LBA {lba}: ECC mismatch")


def sector_count(size: int) -> int:
    """The sectors ``size`` bytes of data take."""
    return -(-size // DATA_SIZE)


class RawTrack:
    """A data track of raw 2352-byte sectors, in memory, whose first sector is LBA ``start``."""

    def __init__(self, image: bytes | bytearray, start: int = 0) -> None:
        if len(image) % SECTOR_SIZE:
            raise ClassicRetroError(
                ErrorCode.INVALID_MEDIA_LAYOUT, "A raw track is a whole number of 2352-byte sectors"
            )
        self.image = image
        self.start = start

    @property
    def end(self) -> int:
        """The LBA after the track's last sector."""
        return self.start + len(self.image) // SECTOR_SIZE

    def _offset(self, lba: int, count: int = 1) -> int:
        if not self.start <= lba <= self.end - count or count < 0:
            raise ClassicRetroError(
                ErrorCode.RESOURCE_OUT_OF_BOUNDS, f"LBA {lba} (+{count}) is outside the track"
            )
        return (lba - self.start) * SECTOR_SIZE

    def sector(self, lba: int) -> bytes:
        start = self._offset(lba)
        return bytes(self.image[start : start + SECTOR_SIZE])

    def subheader(self, lba: int) -> bytes:
        start = self._offset(lba)
        return bytes(self.image[start + _SUBHEADER.start : start + _SUBHEADER.stop])

    def read(self, lba: int, size: int) -> bytes:
        """``size`` bytes of data from the Form 1 sectors starting at ``lba``."""
        count = sector_count(size)
        self._offset(lba, count)
        data = b"".join(self.sector(lba + index)[_DATA] for index in range(count))
        return data[:size]

    def verify(self, lba: int, count: int) -> None:
        """Every sector of the run is a sound Form 1 sector (sync, header, EDC and ECC)."""
        for index in range(count):
            check_form1(self.sector(lba + index), lba + index)

    def empty(self, lba: int, count: int) -> bool:
        """Whether the run holds nothing: a sync and its own header, then zeros."""
        self._offset(lba, count)
        blank = bytes(SECTOR_SIZE - 16)
        for index in range(count):
            sector = self.sector(lba + index)
            if sector[:12] != SYNC or sector[_HEADER] != header(lba + index):
                return False
            if sector[16:] != blank:
                return False
        return True

    def write(self, lba: int, data: bytes, subheaders: list[bytes]) -> None:
        """``data`` into Form 1 sectors from ``lba``, zero-padded, with the given subheaders."""
        if not isinstance(self.image, bytearray):
            raise TypeError("the track is read-only: give RawTrack a bytearray")
        count = sector_count(len(data))
        if len(subheaders) != count:
            raise ValueError(f"{count} sectors need {count} subheaders")
        start = self._offset(lba, count)
        padded = data + bytes(count * DATA_SIZE - len(data))
        for index in range(count):
            chunk = padded[index * DATA_SIZE : (index + 1) * DATA_SIZE]
            sector = form1_sector(lba + index, chunk, subheaders[index])
            at = start + index * SECTOR_SIZE
            self.image[at : at + SECTOR_SIZE] = sector

    def write_file(self, lba: int, data: bytes) -> None:
        """A file's data from ``lba``: data sectors, the last marking the end of the record."""
        count = sector_count(len(data))
        subheaders = [subheader(SUBMODE_DATA)] * (count - 1)
        subheaders.append(subheader(SUBMODE_EOF | SUBMODE_DATA | SUBMODE_EOR))
        self.write(lba, data, subheaders)

    def patch(self, lba: int, offset: int, data: bytes) -> None:
        """Replace ``data`` at ``offset`` in the data of the sectors from ``lba``, codes and all."""
        first = lba + offset // DATA_SIZE
        count = sector_count(offset % DATA_SIZE + len(data))
        subheaders = [self.subheader(first + index) for index in range(count)]
        current = bytearray(self.read(first, count * DATA_SIZE))
        at = offset % DATA_SIZE
        current[at : at + len(data)] = data
        self.write(first, bytes(current), subheaders)


# ---------------------------------------------------------------------------
# ISO 9660


@dataclass(frozen=True, slots=True)
class IsoRecord:
    """A directory record: its name, extent and size, and where the record itself is."""

    name: str
    lba: int
    size: int
    directory: bool
    record_lba: int
    record_offset: int

    @property
    def sectors(self) -> int:
        return sector_count(self.size)


def _record(data: bytes, offset: int, record_lba: int, record_offset: int) -> IsoRecord:
    length = data[offset + _RECORD_NAME_LENGTH]
    raw = data[offset + _RECORD_NAME : offset + _RECORD_NAME + length]
    name = {b"\x00": ".", b"\x01": ".."}.get(raw) or raw.decode("ascii", "replace")
    return IsoRecord(
        name=name,
        lba=struct.unpack_from("<I", data, offset + _RECORD_EXTENT)[0],
        size=struct.unpack_from("<I", data, offset + _RECORD_SIZE)[0],
        directory=bool(data[offset + _RECORD_FLAGS] & _DIRECTORY),
        record_lba=record_lba,
        record_offset=record_offset,
    )


def root_record(track: RawTrack) -> IsoRecord:
    pvd = track.read(PVD_LBA, DATA_SIZE)
    if pvd[:6] != b"\x01CD001":
        raise ClassicRetroError(ErrorCode.INVALID_MEDIA_LAYOUT, "No ISO 9660 volume descriptor")
    return _record(pvd, _PVD_ROOT_RECORD, PVD_LBA, _PVD_ROOT_RECORD)


def volume_space(track: RawTrack) -> int:
    """The sectors the ISO 9660 volume says it spans."""
    return struct.unpack_from("<I", track.read(PVD_LBA, DATA_SIZE), _PVD_VOLUME_SPACE)[0]


def directory(track: RawTrack, record: IsoRecord) -> Iterator[IsoRecord]:
    """The records of a directory, ``.`` and ``..`` left out. A record never crosses a sector."""
    for index in range(record.sectors):
        lba = record.lba + index
        data = track.read(lba, DATA_SIZE)
        offset = 0
        while offset < DATA_SIZE and data[offset]:
            entry = _record(data, offset, lba, offset)
            if entry.name not in (".", ".."):
                yield entry
            offset += data[offset]


def iso_file(track: RawTrack, path: str) -> IsoRecord:
    """The record of ``path`` (``/ST/ST0/ST0.BIN;1``), its name compared without case."""
    record = root_record(track)
    for part in path.strip("/").split("/"):
        wanted = part.upper()
        found = next((entry for entry in directory(track, record) if entry.name == wanted), None)
        if found is None:
            raise ClassicRetroError(ErrorCode.INPUT_NOT_FOUND, f"{path} is not on the disc")
        record = found
    return record


def walk(
    track: RawTrack, record: IsoRecord | None = None, prefix: str = ""
) -> Iterator[tuple[str, IsoRecord]]:
    """Every file and directory under ``record`` (the root by default), by path."""
    for entry in directory(track, record or root_record(track)):
        path = f"{prefix}/{entry.name}"
        yield path, entry
        if entry.directory:
            yield from walk(track, entry, path)


def claimed(track: RawTrack, lba: int, count: int) -> list[str]:
    """The files and directories whose extents meet ``lba``..``lba + count``."""
    return [
        path
        for path, entry in walk(track)
        if entry.lba < lba + count and lba < entry.lba + max(entry.sectors, 1)
    ]


def set_file_extent(track: RawTrack, record: IsoRecord, lba: int, size: int) -> IsoRecord:
    """Point a file's directory record at ``size`` bytes from ``lba`` (both byte orders)."""
    fields = struct.pack("<I", lba) + struct.pack(">I", lba)
    fields += struct.pack("<I", size) + struct.pack(">I", size)
    track.patch(record.record_lba, record.record_offset + _RECORD_EXTENT, fields)
    return IsoRecord(
        record.name, lba, size, record.directory, record.record_lba, record.record_offset
    )
