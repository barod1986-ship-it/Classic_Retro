from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision, SourceBuildSpec


class ZeldaMinishCapUsaGameAdapter(GameAdapter):
    id = "zelda-minish-cap-usa"
    title = "The Legend of Zelda: The Minish Cap (USA)"
    platform_id = "gba"
    engine_id = "gba.tmc"
    revisions = (
        GameRevision(
            sha256="bedc74df62755f705398273de8ed3bc59be610cf55760d0b9aa277f1f5035e73",
            size=16_777_216,
            region="USA",
            revision="0",
        ),
    )
    # The decompilation extracts its assets from this exact image (baserom.gba);
    # `make usa` verifies the rebuilt ROM against expected_sha1.
    source_build = SourceBuildSpec(
        repository_url="https://github.com/zeldaret/tmc",
        commit="d92d4581e202ae531bdcc206a7d6a90ddb8fd907",
        build_target="usa",
        verify_target="usa",
        expected_sha1="b4bd50e4131b027c334547b4524e2dbbd4227130",
    )

    game_code = "BZME"
    header_revision = 0
