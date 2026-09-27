"""Arabic translation of three program strings of *Ridge Racer* (USA).

The translation takes three strings of the game's program, chosen to be
unlike: the title screen's prompt to press Start (the small font, blinking,
centred on the English), the main menu's help line (the small font with two
buttons of the pad, drawn twice by the game, the second time a pixel right
and down in a darker palette as a shadow) and the title of the memory card
screen that loads the fastest laps (the large font, ending where the
English's mirror ends). Every other string stays in English.

Each original is pinned by its address in SCUS-943.00, its room (the string,
its zero and the zeros after it up to the next string) and the SHA-256 of the
room's bytes, so the translation can be checked without the disc and the
build refuses another program. An entry also says which routine draws the
string, how the hook places the Arabic (``engines.ridge_racer_arabic``:
centred on the English's n cells, or ending at its mirror) and where the game
draws it, for the checks and the previews.

The Arabic lives in ``classic_retro/translations/ridge-racer.json``: logical
Unicode Arabic in the engine's notation (``engines.ridge_racer``), one line,
the pad's buttons as the symbols they draw.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.ridge_racer_arabic import CENTRE, LARGE, MIRROR, MIRROR_BIAS, SMALL
from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class RidgeRacerString:
    """A translated string: its entry, where it lives and is drawn, and its original's
    SHA-256."""

    key: str
    address: int
    room: int
    font: str
    mode: int
    parameter: int
    x: int
    y: int
    source_sha256: str
    notation: str


# key: (address, room, font, mode, parameter, x, y, SHA-256 of the room's bytes)
# The parameter is the English's length for CENTRE, 128 and the move for MIRROR.
# fmt: off
_SOURCES: dict[str, tuple[int, int, str, int, int, int, int, str]] = {
    "title.start": (
        0x80010188, 20, SMALL, CENTRE, 17, 0x60, 0x90,
        "daaf864f18e67fb6a4d64b1186213c40902818c0bcdad97ffe7e44724cc024a5",
    ),
    "menu.exit_pad": (
        0x8001027C, 20, SMALL, CENTRE, 18, 0x58, 0xD0,
        "d536aced6f394e967c57bc345e1ff842e9954e86feb31e50a6ac87fd5cd51fde",
    ),
    "card.load_title": (
        0x80010614, 20, LARGE, MIRROR, MIRROR_BIAS, 0x20, 0x20,
        "82dc502d7acc821fdc4b7a191166944e31fa5fa6d579d847b86267d529888e81",
    ),
}
# fmt: on

TARGET = "ridge-racer"


def ridge_racer_arabic_strings(
    translations: TranslationSet | None = None,
) -> tuple[RidgeRacerString, ...]:
    """Every translated string, in the order of the program."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        RidgeRacerString(key, *source, notation=texts[key]) for key, source in _SOURCES.items()
    )
