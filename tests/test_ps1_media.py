from __future__ import annotations

from io import BytesIO

import pycdlib

from classic_retro.adapters.discovery import detect_input
from classic_retro.adapters.registry import build_registry


def _build_ps1_iso() -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1)

    system_cnf = b"BOOT = cdrom:\\SLUS_000.00;1\r\n"
    executable = b"PS-X EXE" + bytes(2048)

    iso.add_fp(BytesIO(system_cnf), len(system_cnf), "/SYSTEM.CNF;1")
    iso.add_fp(BytesIO(executable), len(executable), "/SLUS_000.00;1")

    output = BytesIO()
    iso.write_fp(output)
    iso.close()
    return output.getvalue()


def _mode2_raw(cooked_iso: bytes) -> bytes:
    output = bytearray()
    for offset in range(0, len(cooked_iso), 2048):
        payload = cooked_iso[offset : offset + 2048].ljust(2048, b"\x00")
        output.extend(bytes(24))
        output.extend(payload)
        output.extend(bytes(280))
    return bytes(output)


def test_detect_ps1_bin_cue_from_iso_and_boot_signature(tmp_path):
    bin_path = tmp_path / "disc.bin"
    bin_path.write_bytes(_mode2_raw(_build_ps1_iso()))

    cue_path = tmp_path / "disc.cue"
    cue_path.write_text(
        'FILE "disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n',
        encoding="utf-8",
    )

    report = detect_input(cue_path, build_registry(load_external=False))

    assert report.platform.id == "ps1"
    assert report.platform.metadata["boot_executable"] == "/SLUS_000.00;1"
    assert report.supported is False
