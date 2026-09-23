from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class GoldenSunUsaEuropeGameAdapter(GameAdapter):
    id = "golden-sun-usa-europe"
    title = "Golden Sun (USA, Europe)"
    platform_id = "gba"
    engine_id = "gba.golden-sun"
    revisions = (
        GameRevision(
            sha256="c14f1151897e8d73f25ffdd67e21eebb6dc57973ff2458872ee89fa9060aaca1",
            size=8_388_608,
            region="USA, Europe",
            revision="0",
        ),
    )
    # The gsret/goldensun disassembly rebuilds this image but cannot relocate
    # data yet; the Arabic overlay patches this exact image
    # (classic_retro.rom.golden_sun_arabic) and ships as a BPS patch.
    source_build = None

    game_code = "AGSE"
    header_revision = 0
