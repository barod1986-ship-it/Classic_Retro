from __future__ import annotations

import random
import struct
from io import BytesIO

import pycdlib
import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.patching.cdrom import (
    DATA_SIZE,
    SECTOR_SIZE,
    SUBMODE_DATA,
    SUBMODE_EOF,
    SUBMODE_EOR,
    SUBMODE_FORM2,
    SYNC,
    RawTrack,
    check_form1,
    claimed,
    ecc,
    edc,
    form1_sector,
    header,
    iso_file,
    root_record,
    sector_count,
    set_file_extent,
    subheader,
    volume_space,
    walk,
)

# Sectors of zeros after the file system, as a mastering leaves them.
FREE = 12


def _times(a: int, b: int) -> int:
    """A product in GF(2^8) with x^8 + x^4 + x^3 + x^2 + 1, the field of the ECC."""
    product = 0
    for _ in range(8):
        if b & 1:
            product ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
    return product


def _syndromes(symbols: list[int]) -> tuple[int, int]:
    """The two syndromes of a codeword whose last two symbols are its parity."""
    first = second = 0
    for symbol in symbols:
        first ^= symbol
        second = _times(second, 2) ^ symbol
    return first, second


def _codewords(block: bytes, parity: bytes, count: int, length: int, start, step: int):
    """ECMA-130 annex A: each vector's ``length`` bytes of ``block``, then its two parity bytes."""
    for vector in range(count):
        symbols = [block[(start(vector) + step * k) % len(block)] for k in range(length)]
        yield symbols + [parity[vector], parity[vector + count]]


def test_the_edc_is_the_cd_rom_crc():
    # CRC-32/CD-ROM-EDC's check value, and its residue: the CRC over the data
    # and the EDC after it, little-endian, is zero.
    assert edc(b"123456789") == 0x6EC2EDC4
    data = random.Random(1).randbytes(2056)
    assert edc(data + struct.pack("<I", edc(data))) == 0


def test_every_p_and_q_vector_of_the_ecc_has_zero_syndromes():
    generator = random.Random(2)
    for lba, data in ((0, bytes(DATA_SIZE)), (150, generator.randbytes(DATA_SIZE))):
        sector = form1_sector(lba, data, subheader(SUBMODE_DATA, file=1, channel=2))
        # A Mode 2 sector's header counts as zero.
        covered = bytes(4) + sector[16:2076]
        p_parity, q_parity = sector[2076:2248], sector[2248:]
        # P: the 86 columns of 24 rows of 86 bytes; Q: 52 diagonals over those and P.
        p_vectors = _codewords(covered, p_parity, 86, 24, lambda n: n, 86)
        q_vectors = _codewords(
            covered + p_parity, q_parity, 52, 43, lambda n: (n >> 1) * 86 + (n & 1), 88
        )
        for symbols in (*p_vectors, *q_vectors):
            assert _syndromes(symbols) == (0, 0)


def test_a_sector_keeps_its_codes_when_its_header_changes():
    data = random.Random(3).randbytes(DATA_SIZE)
    here, there = form1_sector(100, data), form1_sector(228_870, data)
    assert here[:12] == there[:12] == SYNC
    assert here[12:16] == header(100) and there[12:16] == bytes.fromhex("50534502")
    assert here[16:] == there[16:]
    assert ecc(here) == here[2076:]


def test_headers_are_bcd_minutes_seconds_and_frames_from_two_seconds():
    assert header(0) == bytes.fromhex("00020002")
    assert header(74) == bytes.fromhex("00027402")
    assert header(4500 - 150) == bytes.fromhex("01000002")
    with pytest.raises(ClassicRetroError) as caught:
        header(100 * 4500)
    assert caught.value.code is ErrorCode.WRITE_OUT_OF_BOUNDS


def test_check_form1_refuses_a_damaged_or_misplaced_sector():
    sector = form1_sector(20, random.Random(4).randbytes(DATA_SIZE))
    check_form1(sector, 20)
    damaged = {
        "No Mode 2 sector at LBA 21": (sector, 21),
        "EDC mismatch": (sector[:100] + bytes((sector[100] ^ 1,)) + sector[101:], 20),
        "ECC mismatch": (sector[:-1] + bytes((sector[-1] ^ 1,)), 20),
    }
    for message, (bad, lba) in damaged.items():
        with pytest.raises(ClassicRetroError) as caught:
            check_form1(bad, lba)
        assert caught.value.code is ErrorCode.INVALID_MEDIA_LAYOUT
        assert message in str(caught.value)
    form2 = bytearray(sector)
    form2[18] = form2[22] = SUBMODE_FORM2
    with pytest.raises(ClassicRetroError, match="not Form 1"):
        check_form1(bytes(form2), 20)
    with pytest.raises(ValueError):
        form1_sector(0, bytes(DATA_SIZE), subheader(SUBMODE_FORM2))
    with pytest.raises(ValueError):
        form1_sector(0, bytes(DATA_SIZE - 1))


def _empty(lba: int) -> bytes:
    return SYNC + header(lba) + bytes(SECTOR_SIZE - 16)


def _track(cooked: bytes, free: int = FREE) -> bytearray:
    """Raw sectors of a 2048-byte-sector image, then ``free`` empty ones the volume spans."""
    count = len(cooked) // DATA_SIZE
    image = bytearray(cooked)
    struct.pack_into("<I", image, 16 * DATA_SIZE + 80, count + free)
    struct.pack_into(">I", image, 16 * DATA_SIZE + 84, count + free)
    raw = bytearray()
    for lba in range(count):
        raw += form1_sector(lba, bytes(image[lba * DATA_SIZE : (lba + 1) * DATA_SIZE]))
    for lba in range(count, count + free):
        raw += _empty(lba)
    return raw


def _iso() -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1)
    files = {
        "/SYSTEM.CNF;1": b"BOOT = cdrom:\\SLUS_000.00;1\r\n",
        "/DRA.BIN;1": bytes(range(256)) * 20,
        "/ST/ST0/ST0.BIN;1": b"stage" * 1000,
    }
    iso.add_directory("/ST")
    iso.add_directory("/ST/ST0")
    for path, data in files.items():
        iso.add_fp(BytesIO(data), len(data), path)
    output = BytesIO()
    iso.write_fp(output)
    iso.close()
    return output.getvalue()


def _cooked(track: RawTrack) -> bytes:
    return track.read(track.start, (track.end - track.start) * DATA_SIZE)


def _read_with_pycdlib(track: RawTrack, path: str) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.open_fp(BytesIO(_cooked(track)))
    output = BytesIO()
    iso.get_file_from_iso_fp(output, iso_path=path)
    iso.close()
    return output.getvalue()


def test_files_are_found_by_path_and_walked():
    track = RawTrack(_track(_iso()))
    assert root_record(track).directory
    stage = iso_file(track, "/st/st0/st0.bin;1")
    assert (stage.name, stage.size, stage.sectors) == ("ST0.BIN;1", 5000, 3)
    assert track.read(stage.lba, stage.size) == b"stage" * 1000
    paths = [path for path, _ in walk(track)]
    assert {"/ST", "/ST/ST0", "/ST/ST0/ST0.BIN;1", "/DRA.BIN;1", "/SYSTEM.CNF;1"} <= set(paths)
    assert claimed(track, stage.lba + 2, 1) == ["/ST/ST0/ST0.BIN;1"]
    assert claimed(track, track.end - FREE, FREE) == []
    assert volume_space(track) == track.end
    with pytest.raises(ClassicRetroError) as caught:
        iso_file(track, "/ST/ST1/ST1.BIN;1")
    assert caught.value.code is ErrorCode.INPUT_NOT_FOUND


def test_a_file_moves_to_free_sectors_with_its_record():
    image = _track(_iso())
    track = RawTrack(image)
    free = track.end - FREE
    assert track.empty(free, FREE) and not track.empty(free - 1, 2)
    stage = iso_file(track, "/ST/ST0/ST0.BIN;1")
    grown = b"arabic" * 1500
    track.write_file(free, grown)
    moved = set_file_extent(track, stage, free, len(grown))
    assert (moved.lba, moved.size, moved.record_lba) == (free, len(grown), stage.record_lba)
    assert iso_file(track, "/ST/ST0/ST0.BIN;1") == moved
    track.verify(free, moved.sectors)
    track.verify(stage.record_lba, 1)
    # The last sector ends the file and the record; pycdlib reads the moved file.
    assert track.subheader(free + moved.sectors - 1)[2] == SUBMODE_EOF | SUBMODE_DATA | SUBMODE_EOR
    assert track.subheader(free)[2] == SUBMODE_DATA
    assert _read_with_pycdlib(track, "/ST/ST0/ST0.BIN;1") == grown
    assert track.read(stage.lba, stage.size) == b"stage" * 1000


def test_a_patch_rewrites_only_the_sectors_it_touches():
    image = _track(_iso())
    original = bytes(image)
    track = RawTrack(image)
    dra = iso_file(track, "/DRA.BIN;1")
    track.patch(dra.lba, DATA_SIZE - 2, b"\xaa\xbb\xcc\xdd")
    data = track.read(dra.lba, dra.size)
    assert data[DATA_SIZE - 2 : DATA_SIZE + 2] == b"\xaa\xbb\xcc\xdd"
    changed = {
        lba
        for lba in range(track.end)
        if image[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
        != original[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
    }
    assert changed == {dra.lba, dra.lba + 1}
    track.verify(dra.lba, 2)
    assert track.subheader(dra.lba) == RawTrack(original).subheader(dra.lba)


def test_a_track_refuses_what_it_cannot_hold():
    with pytest.raises(ClassicRetroError) as caught:
        RawTrack(bytes(SECTOR_SIZE + 1))
    assert caught.value.code is ErrorCode.INVALID_MEDIA_LAYOUT
    track = RawTrack(bytearray(_empty(10) + _empty(11)), start=10)
    assert (track.start, track.end) == (10, 12)
    assert track.empty(10, 2)
    for lba, count in ((9, 1), (11, 2), (12, 1)):
        with pytest.raises(ClassicRetroError) as caught:
            track.read(lba, count * DATA_SIZE)
        assert caught.value.code is ErrorCode.RESOURCE_OUT_OF_BOUNDS
    with pytest.raises(ValueError):
        track.write(10, bytes(10), [])
    with pytest.raises(TypeError):
        RawTrack(bytes(SECTOR_SIZE)).write_file(0, b"x")
    assert sector_count(0) == 0 and sector_count(1) == 1 and sector_count(DATA_SIZE + 1) == 2
