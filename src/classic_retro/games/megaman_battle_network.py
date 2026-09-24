from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class MegaManBattleNetworkUsaGameAdapter(GameAdapter):
    id = "megaman-battle-network-usa"
    title = "Mega Man Battle Network (USA)"
    platform_id = "gba"
    engine_id = "gba.mmbn"
    revisions = (
        GameRevision(
            sha256="87bc7257f2f9ed0acc9f4874177e474e3d339d1e23a0b621d2d8edd73c1a09ed",
            size=8_388_608,
            region="USA",
            revision="0",
        ),
    )
    # The Silenthal/bn1 disassembly matches this image, but its assets are
    # extracted from the original; the Arabic overlay patches this exact image
    # (classic_retro.rom.mmbn_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "AREE"
    header_revision = 0
