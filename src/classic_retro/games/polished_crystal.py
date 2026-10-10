from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision, SourceBuildSpec


class PolishedCrystal323GameAdapter(GameAdapter):
    id = "polished-crystal-323"
    title = "Pokémon Polished Crystal v3.2.3"
    platform_id = "gbc"
    engine_id = "gbc.polished-crystal"
    revisions = (
        GameRevision(
            sha256="f06dbebe3fd20db54e7804605f7a55ad05b8ca203c62209705290d8880864803",
            size=2_097_152,
            revision="3.2.3",
        ),
    )
    source_build = SourceBuildSpec(
        repository_url="https://github.com/Rangi42/polishedcrystal",
        commit="3fa43192379df5c3e7b09a08e4d5d79af4f02f42",
        build_target="crystal",
        verify_target="crystal",
        expected_sha1="6930b48af5844d373e3c9130f26d6dd1084cf4ed",
    )
