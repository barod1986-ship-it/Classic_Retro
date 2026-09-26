"""Arabic translation of the *Castlevania: Symphony of the Night* (USA) prologue dialogue.

A new game opens in 1792, at the end of *Rondo of Blood*: Richter Belmont
climbs to Dracula's throne room and the two speak before the last battle.
That dialogue is the script of stage ST0's cutscene (``SCRIPT_ADDRESS`` in
ST/ST0/ST0.BIN, loaded at 0x80180000): six messages, Richter's and Dracula's
in turn, each voiced, each typed in the box at the top of the screen under
the speaker's portrait and name.

For each message the original is pinned by its place in the script, the
SHA-256 of its bytes and its commands, so the translation can be checked
without the disc and the build can refuse a different script. The speakers'
names are pinned the same way, by the address the game's table of names gives
and the SHA-256 of their bytes (the game's font codes, ASCII minus 0x20, ended
by ``FF 00``).

The Arabic lives in ``classic_retro/translations/sotn.json``: logical Unicode
Arabic in the engine's notation (``engines.sotn``). It keeps every command of
the original, in order: the waits, the speeds and the flags that start
Dracula's and Richter's animations with the text. Line ends are the
translation's own: a line holds at most 152 pixels, and the box shows three
lines, a fourth scrolling it.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.sotn import Piece, notation_skeleton, parse_notation
from classic_retro.localization.translations import TranslationSet, builtin_translation_set

# ST0's cutscene script: from its first command to the events that follow it.
SCRIPT_ADDRESS = 0x801829D8
SCRIPT_END = 0x80182C4A
SCRIPT_SHA256 = "f9021ceaeb6bf17414ebb219dd6ee4e4e076f55bdb6b561e3a79f6a43919ac66"
# The speakers' table of names (a pointer each), by the index their portrait command gives.
NAME_TABLE = 0x80180828


@dataclass(frozen=True, slots=True)
class SotnArabicMessage:
    key: str
    index: int
    source_address: int
    source_end: int
    speaker: int
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


@dataclass(frozen=True, slots=True)
class SotnArabicName:
    """A speaker's name, drawn over the portrait's box."""

    key: str
    speaker: int
    source_address: int
    source_sha256: str
    text: str


RICHTER = 0
DRACULA = 1

# key: (message, start, end, speaker, SHA-256 of the original, its commands)
# fmt: off
_SOURCES: dict[str, tuple[int, int, int, int, str, str]] = {
    "die_monster": (
        0, 0x801829F3, 0x80182A29, RICHTER,
        "dbffb2f9846067eac5415df9e6ae11e18721d0bbabb3910e75b9f7bf9fb60214",
        "{speed 4}{wait 28}{speed 2}{wait 8}{wait 48}",
    ),
    "given_flesh": (
        1, 0x80182A38, 0x80182ABF, DRACULA,
        "f95072c938fab2a322018b5a38cc36918b3d25e06dbb865ef55f55948a9a3d2b",
        "{speed 3}{wait 4}{wait 4}{wait 48}{wait 4}{wait 16}{speed 5}{wait 16}{speed 3}{wait 4}"
        "{wait 24}{wait 48}",
    ),
    "tribute": (
        2, 0x80182AC8, 0x80182B1B, RICHTER,
        "c3ac3c2abfff82e9b2a8fbe91fee9c1b1cbb82ff3792f2cea5fc59c33bdd0d2f",
        "{flag 10}{speed 4}{wait 32}{flag 11}{speed 4}{wait 4}{wait 12}{flag 12}{speed 2}{wait 4}"
        "{flag 13}{wait 48}",
    ),
    "all_religions": (
        3, 0x80182B24, 0x80182B60, DRACULA,
        "2a620a5d47e9ee9e71083e0cbd5e3c8698567205a0d00ea4f688d6626c4152c7",
        "{speed 2}{wait 4}{wait 4}{speed 3}{wait 48}",
    ),
    "empty_words": (
        4, 0x80182B69, 0x80182BCE, RICHTER,
        "961fcd2374dcf809415289044a42e041ae3bf1e5bbe10c647a2e59874a05928c",
        "{speed 3}{flag 14}{wait 4}{flag 15}{wait 40}{flag 16}{wait 4}{flag 4}{flag 17}{speed 4}"
        "{wait 48}{flag 18}",
    ),
    "pile_of_secrets": (
        5, 0x80182BD7, 0x80182C41, DRACULA,
        "8e9bae586c31481388527c8d752d26d8ee310b213e2f487938dceea14c0359ae",
        "{speed 3}{wait 16}{flag 5}{wait 32}{speed 3}{wait 4}{wait 40}{speed 2}{wait-flag 8}"
        "{flag 6}{wait 24}{wait 48}",
    ),
}
# key: (speaker, original, SHA-256 of the original with its FF 00)
_NAMES: dict[str, tuple[int, int, str]] = {
    "name.richter": (
        RICHTER, 0x801A79F4, "400df8d006d38d8c4a8b5598046e4df15ece159e54034be8cc6e3a4d4a9bc1a4",
    ),
    "name.dracula": (
        DRACULA, 0x801A79E8, "ede44dcd50f0e13c50b0955cab79d892341a2ec6090b6833da47ad3f0cfa6a0a",
    ),
}
# fmt: on

TARGET = "sotn"


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts((*_SOURCES, *_NAMES))


def sotn_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[SotnArabicMessage, ...]:
    """Every translated message, in the order the game shows them."""
    texts = _texts(translations)
    return tuple(
        SotnArabicMessage(
            key=key,
            index=index,
            source_address=start,
            source_end=end,
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (index, start, end, speaker, digest, skeleton) in _SOURCES.items()
    )


def sotn_arabic_names(translations: TranslationSet | None = None) -> tuple[SotnArabicName, ...]:
    """The speakers' names."""
    texts = _texts(translations)
    return tuple(
        SotnArabicName(
            key=key, speaker=speaker, source_address=source, source_sha256=digest, text=texts[key]
        )
        for key, (speaker, source, digest) in _NAMES.items()
    )
