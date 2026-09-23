from __future__ import annotations

from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource

_HEADER_LOCATIONS = (
    (0x7FC0, "LoROM"),
    (0xFFC0, "HiROM"),
    (0x40FFC0, "ExHiROM"),
)


def _printable_title(data: bytes) -> bool:
    stripped = data.rstrip(b" \x00")
    return bool(stripped) and all(0x20 <= byte <= 0x7E for byte in stripped)


def _candidate(source: ProbeSource, offset: int) -> bool:
    header = source.read_at(offset, 0x40)
    if len(header) != 0x40 or not _printable_title(header[:21]):
        return False

    complement = int.from_bytes(header[0x1C:0x1E], "little")
    checksum = int.from_bytes(header[0x1E:0x20], "little")
    if (complement + checksum) & 0xFFFF != 0xFFFF:
        return False

    reset_vector = int.from_bytes(header[0x3C:0x3E], "little")
    return reset_vector >= 0x8000


class SNESPlatformAdapter(PlatformAdapter):
    id = "snes"
    display_name = "Super Nintendo / Super Famicom"

    def probe(self, source: ProbeSource) -> ProbeResult:
        shifts = (0x200,) if source.size % 1024 == 512 else (0, 0x200)
        for base, mapping in _HEADER_LOCATIONS:
            for shift in shifts:
                offset = base + shift
                if _candidate(source, offset):
                    evidence = (
                        "SNES internal header candidate has printable title",
                        "SNES checksum/complement pair sums to 0xFFFF",
                        "SNES emulation reset vector points into ROM space",
                    )
                    return ProbeResult(
                        0.92,
                        evidence,
                        {"mapping_candidate": mapping, "header_offset": f"0x{offset:X}"},
                    )
        return ProbeResult.no_match()
