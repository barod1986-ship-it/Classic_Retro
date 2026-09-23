from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision, SourceBuildSpec


class PokemonFireRedRev1GameAdapter(GameAdapter):
    id = "pokemon-firered-rev1-en"
    title = "Pokémon FireRed Version (USA, Europe) (Rev 1)"
    platform_id = "gba"
    engine_id = "gba.pokemon-gen3"
    revisions = (
        GameRevision(
            sha256="729041b940afe031302d630fdbe57c0c145f3f7b6d9b8eca5e98678d0ca4d059",
            size=16_777_216,
            region="USA, Europe",
            revision="1",
        ),
    )
    source_build = SourceBuildSpec(
        repository_url="https://github.com/pret/pokefirered",
        commit="c75f352304d529f6ba92d4f74b9cf8b5c3810788",
        build_target="firered_rev1",
        verify_target="compare_firered_rev1",
        expected_sha1="dd5945db9b930750cb39d00c84da8571feebf417",
    )

    game_code = "BPRE"
    header_revision = 1
