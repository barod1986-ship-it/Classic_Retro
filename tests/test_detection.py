from __future__ import annotations

import pytest

from classic_retro.adapters.base import ProbeSource
from classic_retro.adapters.discovery import detect_platform
from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.patching.nitro import crc16

_GB_LOGO = bytes.fromhex(
    "CE ED 66 66 CC 0D 00 0B 03 73 00 83 00 0C 00 0D "
    "00 08 11 1F 88 89 00 0E DC CC 6E E6 DD DD D9 99 "
    "BB BB 67 63 6E 0E EC CC DD DC 99 9F BB B9 33 3E"
)


def _detect(tmp_path, payload: bytes):
    path = tmp_path / "input.bin"
    path.write_bytes(payload)
    registry = build_registry(load_external=False)
    return detect_platform(ProbeSource(path), registry)


def _gb_rom(*, cgb_flag: int) -> bytes:
    data = bytearray(0x150)
    data[0x104:0x134] = _GB_LOGO
    data[0x134:0x143] = b"CLASSICRETRO123"
    data[0x143] = cgb_flag
    checksum = 0
    for byte in data[0x134:0x14D]:
        checksum = (checksum - byte - 1) & 0xFF
    data[0x14D] = checksum
    return bytes(data)


def _gba_rom() -> bytes:
    data = bytearray(0xC0)
    data[0xA0:0xAC] = b"CLASSICRETRO"
    data[0xAC:0xB0] = b"CRTE"
    data[0xB0:0xB2] = b"01"
    data[0xB2] = 0x96
    data[0xBD] = (-sum(data[0xA0:0xBD]) - 0x19) & 0xFF
    return bytes(data)


def _nds_rom(*, header_crc_ok: bool = True) -> bytes:
    data = bytearray(0x4400)
    data[0:12] = b"CLASSICRETRO"
    data[12:16] = b"CRTE"
    data[16:18] = b"01"
    data[0x20:0x30] = (0x4000).to_bytes(4, "little") + bytes(8) + (0x400).to_bytes(4, "little")
    data[0x15C:0x15E] = (0xCF56).to_bytes(2, "little")
    crc = crc16(data[:0x15E]) ^ (0 if header_crc_ok else 1)
    data[0x15E:0x160] = crc.to_bytes(2, "little")
    return bytes(data)


def _snes_rom() -> bytes:
    data = bytearray(0x8000)
    header = 0x7FC0
    data[header : header + 21] = b"CLASSIC RETRO TEST   "
    data[header + 0x15] = 0x20
    data[header + 0x1C : header + 0x1E] = (0xEDCB).to_bytes(2, "little")
    data[header + 0x1E : header + 0x20] = (0x1234).to_bytes(2, "little")
    data[header + 0x3C : header + 0x3E] = (0x8000).to_bytes(2, "little")
    return bytes(data)


def test_detect_nes_by_content(tmp_path):
    assert _detect(tmp_path, b"NES\x1a" + bytes(32)).id == "nes"


def test_detect_gb_and_gbc_from_header(tmp_path):
    assert _detect(tmp_path, _gb_rom(cgb_flag=0x00)).id == "gb"
    assert _detect(tmp_path, _gb_rom(cgb_flag=0x80)).id == "gbc"


def test_detect_gba_from_header(tmp_path):
    result = _detect(tmp_path, _gba_rom())
    assert result.id == "gba"
    assert result.metadata["game_code"] == "CRTE"


def test_detect_nds_from_header(tmp_path):
    result = _detect(tmp_path, _nds_rom())
    assert result.id == "nds"
    assert result.metadata == {"title": "CLASSICRETRO", "game_code": "CRTE"}
    with pytest.raises(ClassicRetroError) as caught:
        _detect(tmp_path, _nds_rom(header_crc_ok=False))
    assert caught.value.code is ErrorCode.PLATFORM_NOT_DETECTED


def test_detect_megadrive_from_system_field(tmp_path):
    data = bytearray(0x200)
    data[0x100:0x110] = b"SEGA MEGA DRIVE "
    assert _detect(tmp_path, bytes(data)).id == "megadrive"


def test_detect_n64_byte_orders(tmp_path):
    for magic in (b"\x80\x37\x12\x40", b"\x37\x80\x40\x12", b"\x40\x12\x37\x80"):
        assert _detect(tmp_path, magic + bytes(64)).id == "n64"


def test_detect_snes_header_heuristic(tmp_path):
    result = _detect(tmp_path, _snes_rom())
    assert result.id == "snes"
    assert result.metadata["mapping_candidate"] == "LoROM"


def test_detect_psx_exe(tmp_path):
    assert _detect(tmp_path, b"PS-X EXE" + bytes(2048)).id == "ps1"
