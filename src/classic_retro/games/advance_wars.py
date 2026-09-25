from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class AdvanceWarsUsaGameAdapter(GameAdapter):
    id = "advance-wars-usa"
    title = "Advance Wars (USA, Rev 1)"
    platform_id = "gba"
    engine_id = "gba.advance-wars"
    revisions = (
        GameRevision(
            sha256="4dd4bd22441f29b22ca5af554f30bf0eb7d2b1a5daff0e2cd071a43e11383305",
            size=4_194_304,
            region="USA",
            revision="1",
        ),
    )
    # No decompilation is known: the Arabic overlay patches this exact image
    # (classic_retro.rom.advance_wars_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "AWRE"
    header_revision = 1
