from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class TacticsOgreUsaGameAdapter(GameAdapter):
    id = "tactics-ogre-usa"
    title = "Tactics Ogre: The Knight of Lodis (USA)"
    platform_id = "gba"
    engine_id = "gba.tactics-ogre"
    revisions = (
        GameRevision(
            sha256="c5b439c2530331f38e7a6e16857f58c554f270019641f825ac060f4e7866bae4",
            size=8_388_608,
            region="USA",
            revision="0",
        ),
    )
    # The jiangzhengwenjz/totkol disassembly matches this image, but it is not
    # shiftable and takes its data from the original: the Arabic overlay patches
    # this exact image (classic_retro.rom.tactics_ogre_arabic) and ships as a
    # BPS patch.
    source_build = None

    game_code = "ATOE"
    header_revision = 0
