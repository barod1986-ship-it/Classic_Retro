"""The ten reference targets, in the order their command groups appear."""

from __future__ import annotations

from classic_retro.localization.targets import LocalizationTarget


def builtin_targets() -> tuple[LocalizationTarget, ...]:
    from classic_retro.localization.builtin import (
        advance_wars,
        ff6a,
        fire_emblem,
        firered,
        fomt,
        golden_sun,
        minish_cap,
        mlss,
        mmbn,
        pmd_red,
    )

    return (
        firered.TARGET,
        minish_cap.TARGET,
        ff6a.TARGET,
        golden_sun.TARGET,
        fire_emblem.TARGET,
        pmd_red.TARGET,
        mmbn.TARGET,
        mlss.TARGET,
        fomt.TARGET,
        advance_wars.TARGET,
    )
