from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class RidgeRacerUsaGameAdapter(GameAdapter):
    id = "ridge-racer-usa"
    title = "Ridge Racer (USA)"
    platform_id = "ps1"
    engine_id = "ps1.ridge-racer-strings"
    revisions = (
        # Redump "Ridge Racer (USA)" (SCUS-94300): its CUE sheet with the data
        # track and the 13 audio tracks, as one media set.
        GameRevision(
            media_sha256="e4fbdfea2e79cdf8b49b2b1fa9ffff8ac12d87fc67dea9d3d1a7eda5effbf306",
            region="USA",
        ),
        # Its data track alone, the file the Arabic patch applies to.
        GameRevision(
            sha256="087896cebcc2892be651a2f3e59d963daa35e2f861e25ab46e8ecfaf7c8e1c68",
            size=3_683_232,
            region="USA",
        ),
    )
    # No decompilation: the Arabic overlay patches this exact data track
    # (classic_retro.rom.ridge_racer_arabic) and ships as a BPS patch.
    source_build = None

    serial = "SCUS-94300"
