"""N64 byte orders, the header and the boot checksum (``patching.n64``), and the probe.

The image is built here and holds no game data: a header, a boot-code region
of a counting pattern (not a Nintendo boot code, so the toolkit does not know
it; the tests that need a known one teach it the pattern's CRC-32), the
checksummed megabyte from a multiplicative hash, then a few words past it.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from classic_retro.adapters.base import ProbeSource
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.patching import n64
from classic_retro.patching.n64 import (
    BOOT_CODE_END,
    BOOT_CODE_START,
    CHECKSUM,
    CHECKSUM_END,
    CHECKSUM_START,
    CIC_6102,
    HEADER_SIZE,
    MAGIC_N64,
    MAGIC_V64,
    MAGIC_Z64,
    N64Header,
    boot_code,
    header_checksum,
    header_checksum_valid,
    to_big_endian,
    with_header_checksum,
)
from classic_retro.platforms.n64 import N64PlatformAdapter

ENTRY_POINT = 0x80000400
# The words the synthetic header carries at 0x10 and 0x14: not its check code.
STORED_CHECKSUM = (0x11223344, 0x55667788)
# The check code of the synthetic megabyte, by the implementation that reproduces
# the header of a real CIC-NUS-6102 image.
EXPECTED_CHECKSUM = (0x81864DDB, 0xF4CB2088)
IMAGE_SIZE = CHECKSUM_END + 0x40


def _words(count: int) -> bytes:
    """``count`` big-endian words of a multiplicative hash: carries and every rotation."""
    return struct.pack(
        f">{count}I", *(((n * 0x9E3779B1) + 0x7F4A7C15) & 0xFFFFFFFF for n in range(count))
    )


def _image() -> bytes:
    image = bytearray(IMAGE_SIZE)
    image[0:4] = MAGIC_Z64
    struct.pack_into(">I", image, 0x08, ENTRY_POINT)
    struct.pack_into(">II", image, CHECKSUM, *STORED_CHECKSUM)
    image[0x20:0x34] = b"CLASSIC RETRO TEST  "
    image[0x3B:0x3F] = b"NCRE"
    image[0x3F] = 1
    counting = bytes(range(256)) * 16
    image[BOOT_CODE_START:BOOT_CODE_END] = counting[: BOOT_CODE_END - BOOT_CODE_START]
    image[CHECKSUM_START:] = _words((IMAGE_SIZE - CHECKSUM_START) // 4)
    return bytes(image)


def _hex_pair(checksum: tuple[int, int]) -> str:
    """The two check code words as the probe reports them."""
    return f"{checksum[0]:08X} {checksum[1]:08X}"


def _in_order(image: bytes, order: str) -> bytes:
    """A z64 ``image`` as a dump in ``order`` stores it: each 2- or 4-byte unit reversed."""
    if order == "z64":
        return image
    unit = 2 if order == "v64" else 4
    return b"".join(image[n : n + unit][::-1] for n in range(0, len(image), unit))


@pytest.fixture(scope="module")
def rom() -> bytes:
    return _image()


@pytest.fixture
def known_boot_code(rom, monkeypatch) -> None:
    """Teach the toolkit the synthetic boot-code region as CIC-NUS-6102."""
    monkeypatch.setitem(n64.BOOT_CODES, zlib.crc32(rom[BOOT_CODE_START:BOOT_CODE_END]), CIC_6102)


def test_the_header_is_read_from_a_big_endian_image(rom):
    header = N64Header.read(rom)
    assert header == N64Header(
        entry_point=ENTRY_POINT,
        checksum=STORED_CHECKSUM,
        title="CLASSIC RETRO TEST",
        game_code="NCRE",
        revision=1,
    )
    assert N64Header.read(rom[:HEADER_SIZE]) == header
    with pytest.raises(ClassicRetroError) as caught:
        N64Header.read(rom[: HEADER_SIZE - 1])
    assert caught.value.code is ErrorCode.INVALID_BYTE_RANGE
    with pytest.raises(ClassicRetroError) as caught:
        N64Header.read(_in_order(rom, "v64"))
    assert caught.value.code is ErrorCode.INVALID_BYTE_RANGE


def test_to_big_endian_takes_every_byte_order(rom):
    assert to_big_endian(rom) == rom
    for order in ("v64", "n64"):
        stored = _in_order(rom, order)
        assert stored != rom and stored[:4] == {"v64": MAGIC_V64, "n64": MAGIC_N64}[order]
        assert to_big_endian(stored) == rom
    # The swaps are their own inverse: the z64 image stored v64 reads back the same way.
    assert _in_order(_in_order(rom, "n64"), "n64") == rom


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (bytes(8), "not an N64 image"),
        (b"NES\x1a" + bytes(4), "another platform's magic"),
        (MAGIC_Z64[:3], "a cut magic"),
        (MAGIC_V64 + bytes(3), "a v64 image of odd length"),
        (MAGIC_N64 + bytes(2), "an n64 image not a whole number of words"),
    ],
)
def test_to_big_endian_refuses_other_data_and_cut_units(data, why):
    with pytest.raises(ClassicRetroError) as caught:
        to_big_endian(data)
    assert caught.value.code is ErrorCode.INVALID_BYTE_RANGE, why


def test_the_boot_code_is_named_by_its_crc32(rom, monkeypatch):
    assert boot_code(rom) is None
    assert boot_code(rom[: BOOT_CODE_END - 1]) is None
    crc = zlib.crc32(rom[BOOT_CODE_START:BOOT_CODE_END])
    monkeypatch.setitem(n64.BOOT_CODES, crc, CIC_6102)
    assert boot_code(rom) == CIC_6102
    assert boot_code(rom[:BOOT_CODE_END]) == CIC_6102
    changed = bytearray(rom)
    changed[BOOT_CODE_END - 1] ^= 1
    assert boot_code(bytes(changed)) is None


@pytest.mark.usefixtures("known_boot_code")
def test_the_checksum_covers_the_megabyte_after_the_boot_code(rom):
    assert header_checksum(rom) == EXPECTED_CHECKSUM
    assert not header_checksum_valid(rom)
    inside = bytearray(rom)
    inside[CHECKSUM_END - 1] ^= 0x80
    assert header_checksum(bytes(inside)) != EXPECTED_CHECKSUM
    first = bytearray(rom)
    first[CHECKSUM_START] ^= 0x01
    assert header_checksum(bytes(first)) != EXPECTED_CHECKSUM
    # The header and whatever follows the megabyte do not count.
    outside = bytearray(rom)
    outside[CHECKSUM_END] ^= 0xFF
    outside[CHECKSUM] ^= 0xFF
    assert header_checksum(bytes(outside)) == EXPECTED_CHECKSUM


def test_the_checksum_is_refused_for_an_unknown_boot_code(rom):
    with pytest.raises(ClassicRetroError) as caught:
        header_checksum(rom)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    with pytest.raises(ClassicRetroError) as caught:
        with_header_checksum(rom)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


@pytest.mark.usefixtures("known_boot_code")
def test_the_checksum_is_refused_for_a_truncated_image(rom):
    with pytest.raises(ClassicRetroError) as caught:
        header_checksum(rom[: CHECKSUM_END - 4])
    assert caught.value.code is ErrorCode.INVALID_BYTE_RANGE
    assert header_checksum(rom[:CHECKSUM_END]) == EXPECTED_CHECKSUM


@pytest.mark.usefixtures("known_boot_code")
def test_with_header_checksum_changes_only_the_two_header_words(rom):
    fixed = with_header_checksum(rom)
    assert len(fixed) == len(rom)
    assert fixed[:CHECKSUM] == rom[:CHECKSUM] and fixed[CHECKSUM + 8 :] == rom[CHECKSUM + 8 :]
    assert struct.unpack_from(">II", fixed, CHECKSUM) == EXPECTED_CHECKSUM
    assert N64Header.read(fixed).checksum == EXPECTED_CHECKSUM
    assert header_checksum_valid(fixed) and not header_checksum_valid(rom)
    assert with_header_checksum(fixed) == fixed


# ---------------------------------------------------------------------------
# The platform probe


def _probe(tmp_path, image: bytes, order: str = "z64"):
    path = tmp_path / f"input.{order}"
    path.write_bytes(_in_order(image, order))
    return N64PlatformAdapter().probe(ProbeSource(path))


@pytest.mark.usefixtures("known_boot_code")
def test_the_probe_reports_the_same_header_in_every_byte_order(rom, tmp_path):
    fixed = with_header_checksum(rom)
    results = {order: _probe(tmp_path, fixed, order) for order in ("z64", "v64", "n64")}
    for order, result in results.items():
        assert result.confidence == 1.0
        assert order in result.metadata["byte_order"]
        assert dict(result.metadata, byte_order="") == {
            "byte_order": "",
            "title": "CLASSIC RETRO TEST",
            "game_code": "NCRE",
            "revision": "1",
            "header_checksum": _hex_pair(EXPECTED_CHECKSUM),
            "boot_code": CIC_6102,
            "checksum_valid": "true",
        }
        assert any("check code matches" in line for line in result.evidence)


@pytest.mark.usefixtures("known_boot_code")
def test_the_probe_reports_a_check_code_that_does_not_match(rom, tmp_path):
    result = _probe(tmp_path, rom, "v64")
    assert result.confidence == 1.0
    assert result.metadata["header_checksum"] == _hex_pair(STORED_CHECKSUM)
    assert result.metadata["checksum_valid"] == "false"
    assert any("does not match" in line for line in result.evidence)


def test_the_probe_names_no_boot_code_it_does_not_know(rom, tmp_path):
    result = _probe(tmp_path, rom, "n64")
    assert result.confidence == 1.0
    assert result.metadata["title"] == "CLASSIC RETRO TEST"
    assert result.metadata["boot_code"] == "unknown"
    assert "checksum_valid" not in result.metadata
    assert result.evidence == ("Nintendo 64 ROM byte-order magic matched",)


@pytest.mark.usefixtures("known_boot_code")
def test_the_probe_reads_only_what_a_truncated_image_has(rom, tmp_path):
    # Header and boot code, but not the megabyte: the boot code is named, no verdict.
    result = _probe(tmp_path, rom[:0x2000])
    assert result.metadata["boot_code"] == CIC_6102
    assert result.metadata["title"] == "CLASSIC RETRO TEST"
    assert "checksum_valid" not in result.metadata
    # The header alone: its fields, and no boot code to name.
    result = _probe(tmp_path, rom[:HEADER_SIZE], "v64")
    assert result.metadata["game_code"] == "NCRE" and result.metadata["boot_code"] == "unknown"
    # Less than a header: the byte order only, as before.
    result = _probe(tmp_path, rom[: HEADER_SIZE - 4], "n64")
    assert result.confidence == 1.0 and set(result.metadata) == {"byte_order"}
