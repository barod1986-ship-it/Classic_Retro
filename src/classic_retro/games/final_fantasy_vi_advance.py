from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class FinalFantasyVIAdvanceUsaGameAdapter(GameAdapter):
    id = "final-fantasy-vi-advance-usa"
    title = "Final Fantasy VI Advance (USA)"
    platform_id = "gba"
    engine_id = "gba.ff6a"
    revisions = (
        GameRevision(
            sha256="1310f2ad3c13f5446cf6c43d01d48aad640d6b8a4fbba2b92c776f4f6d90e6ff",
            size=8_388_608,
            region="USA",
            revision="0",
        ),
    )
    # No source-matching decompilation exists; the Arabic overlay patches this
    # exact image (classic_retro.rom.ff6a_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "BZ6E"
    header_revision = 0
