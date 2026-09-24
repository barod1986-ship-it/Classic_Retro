from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class HarvestMoonFomtUsaGameAdapter(GameAdapter):
    id = "harvest-moon-fomt-usa"
    title = "Harvest Moon: Friends of Mineral Town (USA)"
    platform_id = "gba"
    engine_id = "gba.fomt"
    revisions = (
        GameRevision(
            sha256="ca6cebe7211b6f2693af210709f76222204bf9f7621dec08b30ca268117460dd",
            size=8_388_608,
            region="USA",
            revision="0",
        ),
    )
    # No decompilation builds this image; the Arabic overlay patches this exact
    # image (classic_retro.rom.fomt_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "A4NE"
    header_revision = 0
