"""The twenty-two reference targets, in the order their command groups appear."""

from __future__ import annotations

from classic_retro.localization.targets import LocalizationTarget


def builtin_targets() -> tuple[LocalizationTarget, ...]:
    from classic_retro.localization.builtin import (
        advance_wars,
        chrono_trigger,
        ff6a,
        final_fantasy_ii,
        fire_emblem,
        firered,
        fomt,
        golden_sun,
        gran_turismo,
        link_to_the_past,
        metroid_fusion,
        minish_cap,
        mlss,
        mmbn,
        nsmb,
        phantom_hourglass,
        platinum,
        pmd_red,
        ridge_racer,
        shining_force_2,
        sotn,
        tactics_ogre,
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
        metroid_fusion.TARGET,
        tactics_ogre.TARGET,
        nsmb.TARGET,
        platinum.TARGET,
        phantom_hourglass.TARGET,
        sotn.TARGET,
        gran_turismo.TARGET,
        ridge_racer.TARGET,
        chrono_trigger.TARGET,
        link_to_the_past.TARGET,
        shining_force_2.TARGET,
        final_fantasy_ii.TARGET,
    )
