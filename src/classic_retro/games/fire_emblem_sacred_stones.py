from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class FireEmblemSacredStonesUsaGameAdapter(GameAdapter):
    id = "fire-emblem-sacred-stones-usa"
    title = "Fire Emblem: The Sacred Stones (USA, Australia)"
    platform_id = "gba"
    engine_id = "gba.fire-emblem"
    revisions = (
        GameRevision(
            sha256="638cda9d9b72657220fbf7e7a500cd3b64d9686c36e8a56fca69d26d13886f2f",
            size=16_777_216,
            region="USA, Australia",
            revision="0",
        ),
    )
    # The fireemblem8u decompilation rebuilds this image, but most of its data
    # is still binary; the Arabic overlay patches this exact image
    # (classic_retro.rom.fire_emblem_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "BE8E"
    header_revision = 0
