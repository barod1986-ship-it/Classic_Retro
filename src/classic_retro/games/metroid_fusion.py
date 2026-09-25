from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class MetroidFusionUsaGameAdapter(GameAdapter):
    id = "metroid-fusion-usa"
    title = "Metroid Fusion (USA)"
    platform_id = "gba"
    engine_id = "gba.metroid-fusion"
    revisions = (
        GameRevision(
            sha256="a56ce3d7f8f3f4f4d0468d421fff5dd3ee3aec99a58244377e43aae769dc3fe8",
            size=8_388_608,
            region="USA",
            revision="0",
        ),
    )
    # The metroidret/mf decompilation matches this image, but it is not
    # shiftable and takes its data from the original: the Arabic overlay patches
    # this exact image (classic_retro.rom.metroid_fusion_arabic) and ships as a
    # BPS patch.
    source_build = None

    game_code = "AMTE"
    header_revision = 0
