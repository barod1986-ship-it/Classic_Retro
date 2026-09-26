from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision, SourceBuildSpec


class PokemonPlatinumUsaGameAdapter(GameAdapter):
    id = "pokemon-platinum-usa"
    title = "Pokémon Platinum Version (USA)"
    platform_id = "nds"
    engine_id = "nds.pokemon-gen4"
    revisions = (
        # No-Intro Rev 0, which pret/pokeplatinum builds.
        GameRevision(
            sha256="ede62292aa7f7014ff27d42097e769753380531739889c29b968b67b80f80678",
            size=134_217_728,
            region="USA",
            revision="0",
        ),
        # The same, with the header's reserved bytes 0x378..0x3A0 and
        # 0xF80..0x1000 cleared, as some dumps have them.
        GameRevision(
            sha256="67de86a1bc8e7eb6479dbbbd6e8f5edfc2fa160576a38e40e06d2180ed63b110",
            size=134_217_728,
            region="USA",
            revision="0",
        ),
    )
    # pret/pokeplatinum builds Rev 0 from source (ROM_REVISION=0), with the
    # Metrowerks compiler; the Arabic overlay patches the user's image instead
    # (classic_retro.rom.platinum_arabic) and ships as a BPS patch.
    source_build = SourceBuildSpec(
        repository_url="https://github.com/pret/pokeplatinum",
        commit="c248fb3f8cc9934ded800e489567c5c0eeee92eb",
        build_target="rom (ROM_REVISION=0)",
        verify_target="check",
        expected_sha1="ce81046eda7d232513069519cb2085349896dec7",
    )

    game_code = "CPUE"
    header_revision = 0
