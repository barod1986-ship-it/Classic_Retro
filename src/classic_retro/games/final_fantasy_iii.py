from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class FinalFantasyIIIUsaGameAdapter(GameAdapter):
    id = "final-fantasy-iii-usa"
    title = "Final Fantasy III (USA)"
    platform_id = "snes"
    engine_id = "snes.ff6-dialogue"
    revisions = (
        # No-Intro "Final Fantasy III (USA)" (SNS-F6-USA, version 1.0, CRC32
        # A27F1C7A), without a copier header.
        GameRevision(
            sha256="0f51b4fca41b7fd509e4b8f9d543151f68efa5e97b08493e4b2a0c06f5d8d5e2",
            size=3 * 1024 * 1024,
            region="USA",
        ),
    )
    # The everything8215/ff6 disassembly rebuilds this ROM (its "Final Fantasy III
    # 1.0 (U)"), but it takes the ROM's data from the original: the Arabic overlay
    # patches this exact ROM (classic_retro.rom.ff6_arabic) and ships as a BPS patch.
    source_build = None

    serial = "SNS-F6-USA"
