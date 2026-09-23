from __future__ import annotations

from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource


def _ascii_code(data: bytes) -> bool:
    return len(data) > 0 and all(byte == 0 or 0x20 <= byte <= 0x7E for byte in data)


class GBAPlatformAdapter(PlatformAdapter):
    id = "gba"
    display_name = "Game Boy Advance"

    def probe(self, source: ProbeSource) -> ProbeResult:
        header = source.read_at(0, 0xC0)
        if len(header) != 0xC0 or header[0xB2] != 0x96:
            return ProbeResult.no_match()

        checksum = (-sum(header[0xA0:0xBD]) - 0x19) & 0xFF
        if checksum != header[0xBD]:
            return ProbeResult.no_match()

        if not _ascii_code(header[0xA0:0xAC]) or not _ascii_code(header[0xAC:0xB2]):
            return ProbeResult.no_match()

        title = header[0xA0:0xAC].rstrip(b"\x00 ").decode("ascii", errors="replace")
        game_code = header[0xAC:0xB0].decode("ascii", errors="replace")
        return ProbeResult(
            0.99,
            ("GBA fixed byte 0x96 is present", "GBA complement header checksum is valid"),
            {"title": title, "game_code": game_code},
        )
