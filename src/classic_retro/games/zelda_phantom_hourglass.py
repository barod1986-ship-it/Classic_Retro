from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class ZeldaPhantomHourglassUsaGameAdapter(GameAdapter):
    id = "zelda-phantom-hourglass-usa"
    title = "The Legend of Zelda: Phantom Hourglass (USA)"
    platform_id = "nds"
    engine_id = "nds.zelda-ph"
    revisions = (
        # No-Intro "Legend of Zelda, The - Phantom Hourglass (USA) (En,Fr,Es)",
        # the image zeldaret/ph targets (ph_usa.sha1).
        GameRevision(
            sha256="2dd43288c1b7b428cbd09d9a74464b9a46fe0239eaed82849369f261678011f7",
            size=67_108_864,
            region="USA",
            revision="0",
        ),
    )
    # zeldaret/ph rebuilds the game from the user's own copy and is not
    # finished: the Arabic overlay patches this exact image
    # (classic_retro.rom.phantom_hourglass_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "AZEE"
    header_revision = 0
