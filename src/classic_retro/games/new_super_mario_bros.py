from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class NewSuperMarioBrosUsaGameAdapter(GameAdapter):
    id = "new-super-mario-bros-usa"
    title = "New Super Mario Bros. (USA)"
    platform_id = "nds"
    engine_id = "nds.nsmb"
    revisions = (
        GameRevision(
            sha256="9f67fef1b4c73e966767f6153431ada3751dc1b0da2c70f386c14a5e3017f354",
            size=33_554_432,
            region="USA",
            revision="0",
        ),
    )
    # The NSMB-Decomp/nsmb decompilation cannot build a ROM yet: the Arabic
    # overlay patches this exact image (classic_retro.rom.nsmb_arabic) and ships
    # as a BPS patch.
    source_build = None

    game_code = "A2DE"
    header_revision = 0
