from __future__ import annotations

from classic_retro.adapters.base import GameAdapter, GameRevision


class ChronoTriggerUsaGameAdapter(GameAdapter):
    id = "chrono-trigger-usa"
    title = "Chrono Trigger (USA)"
    platform_id = "snes"
    engine_id = "snes.chrono-trigger-dialogue"
    revisions = (
        # No-Intro "Chrono Trigger (USA)" (SNS-ACTE-USA), without a copier header.
        GameRevision(
            sha256="06d1c2b06b716052c5596aaa0c2e5632a027fee1a9a28439e509f813c30829a9",
            size=4 * 1024 * 1024,
            region="USA",
        ),
    )
    # The dscotton/ct_disassembly disassembly matches this ROM, but it takes
    # the ROM's data from the original at fixed addresses: the Arabic overlay
    # patches this exact ROM (classic_retro.rom.chrono_trigger_arabic) and
    # ships as a BPS patch.
    source_build = None

    serial = "SNS-ACTE-USA"
