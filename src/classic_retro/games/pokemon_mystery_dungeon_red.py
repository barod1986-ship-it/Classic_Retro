from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class PokemonMysteryDungeonRedUsaGameAdapter(GameAdapter):
    id = "pokemon-mystery-dungeon-red-usa"
    title = "Pokémon Mystery Dungeon: Red Rescue Team (USA, Australia)"
    platform_id = "gba"
    engine_id = "gba.pmd"
    revisions = (
        GameRevision(
            sha256="ad316814c77ed083734d816ebcde2ece390efae8d15bcb6c66d7c2862d82eb68",
            size=33_554_432,
            region="USA, Australia",
            revision="0",
        ),
    )
    # The pret/pmd-red decompilation rebuilds this image, but its data is
    # still extracted from the original; the Arabic overlay patches this exact
    # image (classic_retro.rom.pmd_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "B24E"
    header_revision = 0
