from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class FinalFantasyIIUsaGameAdapter(GameAdapter):
    id = "final-fantasy-ii-usa"
    title = "Final Fantasy II (USA, Rev 1)"
    platform_id = "snes"
    engine_id = "snes.ff4-dialogue"
    revisions = (
        # No-Intro "Final Fantasy II (USA) (Rev 1)" (SNS-F4-USA, version 1.1),
        # without a copier header.
        GameRevision(
            sha256="414bacc05a18a6137c0de060b4094ab6d1b75105342b0bb36a42e45d945a0e4d",
            size=1024 * 1024,
            region="USA",
        ),
    )
    # The everything8215/ff4 disassembly rebuilds this ROM (its "Final Fantasy II
    # 1.1 (U)"), but it takes the ROM's data from the original: the Arabic overlay
    # patches this exact ROM (classic_retro.rom.ff4_arabic) and ships as a BPS patch.
    source_build = None

    serial = "SNS-F4-USA"
