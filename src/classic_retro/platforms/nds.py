from __future__ import annotations

import struct

from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource
from classic_retro.patching.nitro import NINTENDO_LOGO_CRC, crc16


def _ascii_code(data: bytes) -> bool:
    return len(data) > 0 and all(byte == 0 or 0x20 <= byte <= 0x7E for byte in data)


class NDSPlatformAdapter(PlatformAdapter):
    id = "nds"
    display_name = "Nintendo DS"

    def probe(self, source: ProbeSource) -> ProbeResult:
        header = source.read_at(0, 0x160)
        if len(header) != 0x160:
            return ProbeResult.no_match()
        logo_crc, header_crc = struct.unpack_from("<HH", header, 0x15C)
        if logo_crc != NINTENDO_LOGO_CRC or crc16(header[:0x15E]) != header_crc:
            return ProbeResult.no_match()
        if not _ascii_code(header[0:12]) or not _ascii_code(header[12:16]):
            return ProbeResult.no_match()
        arm9_offset, _, _, arm9_size = struct.unpack_from("<4I", header, 0x20)
        if arm9_offset < 0x4000 or arm9_offset + arm9_size > source.size:
            return ProbeResult.no_match()

        title = header[0:12].rstrip(b"\x00 ").decode("ascii", errors="replace")
        game_code = header[12:16].decode("ascii", errors="replace")
        return ProbeResult(
            0.99,
            ("DS logo CRC is 0xCF56", "DS header CRC-16 is valid"),
            {"title": title, "game_code": game_code},
        )
