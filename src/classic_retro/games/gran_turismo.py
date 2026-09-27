from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class GranTurismoUsaGameAdapter(GameAdapter):
    id = "gran-turismo-usa"
    title = "Gran Turismo (USA) (Rev 1)"
    platform_id = "ps1"
    engine_id = "ps1.gran-turismo-license"
    revisions = (
        # Redump "Gran Turismo (USA) (Rev 1)" (SCUS-94194): its CUE sheet and
        # its one data track, as one media set.
        GameRevision(
            media_sha256="37db5b2390bf918f290bbb18f8ea5565d0b865b2ccb2ff687c19ac135d4bd94f",
            region="USA",
            revision="1",
        ),
        # The data track alone, the file the Arabic patch applies to.
        GameRevision(
            sha256="e1ba7def96b7f213637fa82658b53c34a3a5f6c54df7d7e5ab9c3f53a2d41f03",
            size=693_668_304,
            region="USA",
            revision="1",
        ),
    )
    # No decompilation: the Arabic overlay patches this exact data track
    # (classic_retro.rom.gran_turismo_arabic) and ships as a BPS patch.
    source_build = None

    serial = "SCUS-94194"
