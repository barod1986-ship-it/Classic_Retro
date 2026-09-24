from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class MarioLuigiSuperstarSagaUsaGameAdapter(GameAdapter):
    id = "mario-luigi-superstar-saga-usa"
    title = "Mario & Luigi: Superstar Saga (USA)"
    platform_id = "gba"
    engine_id = "gba.mlss"
    revisions = (
        GameRevision(
            sha256="af9066e7eacdab919e92987db8856d038e4b75d4ed011259c893702085a886be",
            size=16_777_216,
            region="USA",
            revision="0",
        ),
    )
    # The jellees/mlss decompilation matches this image, but its data is
    # extracted from the original; the Arabic overlay patches this exact image
    # (classic_retro.rom.mlss_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "A88E"
    header_revision = 0
