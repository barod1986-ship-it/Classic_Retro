from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class ShiningForce2UsaGameAdapter(GameAdapter):
    id = "shining-force-2-usa"
    title = "Shining Force II (USA)"
    platform_id = "megadrive"
    engine_id = "megadrive.sf2-dialogue"
    revisions = (
        # No-Intro "Shining Force II (USA)" (GM MK-1315 -00).
        GameRevision(
            sha256="9adf662d09881f58ec37d174ab01e87a7fcfb24700b5f84b26c0cd4f351509e9",
            size=2 * 1024 * 1024,
            region="USA",
        ),
    )
    # The ShiningForceCentral/SF2DISASM disassembly rebuilds this ROM, but it
    # takes the ROM's data (the text, the graphics) from the original: the
    # Arabic overlay patches this exact ROM (classic_retro.rom.sf2_arabic) and
    # ships as a BPS patch.
    source_build = None

    serial = "GM MK-1315 -00"
