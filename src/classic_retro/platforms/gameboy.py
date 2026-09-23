from __future__ import annotations

import hashlib

from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource

_LOGO_SHA256 = "daf4cabdc852baa0291849203f0b41fd0b4ecd58e0d7aff4a509f5de4d7f9a2e"


def _valid_header(source: ProbeSource) -> tuple[bool, int]:
    header = source.read_at(0x100, 0x50)
    if len(header) != 0x50:
        return False, 0

    logo = header[0x04:0x34]
    if hashlib.sha256(logo).hexdigest() != _LOGO_SHA256:
        return False, 0

    checksum = 0
    for byte in header[0x34:0x4D]:
        checksum = (checksum - byte - 1) & 0xFF
    if checksum != header[0x4D]:
        return False, 0

    return True, header[0x43]


class GameBoyPlatformAdapter(PlatformAdapter):
    id = "gb"
    display_name = "Game Boy"

    def probe(self, source: ProbeSource) -> ProbeResult:
        valid, cgb_flag = _valid_header(source)
        if not valid or cgb_flag in (0x80, 0xC0):
            return ProbeResult.no_match()
        return ProbeResult(
            1.0,
            ("Game Boy Nintendo-logo hash and header checksum are valid",),
            {"cgb_mode": "dmg"},
        )


class GameBoyColorPlatformAdapter(PlatformAdapter):
    id = "gbc"
    display_name = "Game Boy Color"

    def probe(self, source: ProbeSource) -> ProbeResult:
        valid, cgb_flag = _valid_header(source)
        if not valid or cgb_flag not in (0x80, 0xC0):
            return ProbeResult.no_match()
        mode = "compatible" if cgb_flag == 0x80 else "color-only"
        return ProbeResult(
            1.0,
            ("Game Boy Nintendo-logo hash and header checksum are valid", "CGB flag is set"),
            {"cgb_mode": mode},
        )
