from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class CastlevaniaSotnUsaGameAdapter(GameAdapter):
    id = "castlevania-sotn-usa"
    title = "Castlevania: Symphony of the Night (USA)"
    platform_id = "ps1"
    engine_id = "ps1.sotn-cutscene"
    revisions = (
        # Redump "Castlevania - Symphony of the Night (USA)" (SLUS-00067): its CUE
        # sheet with the data track and the audio track, as one media set.
        GameRevision(
            media_sha256="62c5b23ec3cab2279629b156eca8c9d72b3e2c0caca56ba66a3b3a69c59cc48c",
            region="USA",
        ),
        # Its data track alone, the file the Arabic patch applies to.
        GameRevision(
            sha256="ce01203a9df93e001b88ef4c350889c19f11ffba89d20f214bdd8dec0b2d8d7c",
            size=538_655_040,
            region="USA",
        ),
    )
    # sotn-decomp decompiles the game but takes its data from the original disc:
    # the Arabic overlay patches this exact data track
    # (classic_retro.rom.sotn_arabic) and ships as a BPS patch.
    source_build = None

    serial = "SLUS-00067"
