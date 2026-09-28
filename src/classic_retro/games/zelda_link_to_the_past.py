from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class ZeldaLinkToThePastUsaGameAdapter(GameAdapter):
    id = "zelda-link-to-the-past-usa"
    title = "The Legend of Zelda: A Link to the Past (USA)"
    platform_id = "snes"
    engine_id = "snes.alttp-dialogue"
    revisions = (
        # No-Intro "Legend of Zelda, The - A Link to the Past (USA)" (SNS-ZL-USA),
        # without a copier header.
        GameRevision(
            sha256="66871d66be19ad2c34c927d6b14cd8eb6fc3181965b6e517cb361f7316009cfb",
            size=1024 * 1024,
            region="USA",
        ),
    )
    # The spannerisms/usdasm disassembly rebuilds this ROM, but it takes the
    # ROM's data from the original: the Arabic overlay patches this exact ROM
    # (classic_retro.rom.alttp_arabic) and ships as a BPS patch.
    source_build = None

    serial = "SNS-ZL-USA"
