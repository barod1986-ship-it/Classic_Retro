"""Arabic translation of six messages of *Final Fantasy II* (USA): the opening.

A new game opens on the deck of the Red Wings' airship, flying home to Baron
with the crystal of Mysidia: the crew tells the captain they are about to
arrive, then argues over the robbery, and Cecil answers them; monsters attack;
the airship reaches Baron. The translation takes the six messages of that
scene, chosen to be unlike: short exchanges with the captain's name written by
the game (``{Name 00}``), and Cecil's long answer of four pages. Every other
message stays in English.

Each original is pinned by its bank and its offset in that bank's text (what
the engine holds while it reads the message, and what the hooks match) and the
SHA-256 of its bytes (its end included), so the translation can be checked
without the ROM and the build refuses another text. Its command skeleton
(``engines.ff4.command_skeleton``: its commands with their bytes, but the
layout) may be pinned too, so the translation's commands are checked without
the ROM as the build checks them against the ROM's; the build's report carries
every original's, for pinning.

The Arabic lives in ``classic_retro/translations/final-fantasy-ii.json``:
logical Unicode Arabic in the engine's notation (``engines.ff4_arabic``): a line
for each page, ``{line}`` where a row must end, ``{Name 00}`` for the captain's
name and the English's commands as tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class Ff4Message:
    """A translated message: its entry, its bank and offset, its original's SHA-256
    and, when pinned, its original's command skeleton."""

    key: str
    bank: int
    offset: int
    source_sha256: str
    notation: str
    source_skeleton: tuple[str, ...] | None = None


# key: (the bank, the offset of the message in the bank's text, SHA-256 of its bytes
# with the end, its commands; None until a maintainer pins them from the ROM, as the
# build's report gives them)
# fmt: off
_SOURCES: dict[str, tuple[int, int, str, tuple[str, ...] | None]] = {
    "deck.arrive": (1, 0x0290, "bf7ef4d59476b6a0ff8b36c6d40b77619bb751a5a60cf2d6c205872f0bd5b0e4", None),
    "deck.robbing": (1, 0x02B7, "2f2cc6ecef5ce893e2e66be121f350fe96e03c16824d60c96eee8e4c0f040d4d", None),
    "deck.captain": (1, 0x030C, "f2a0d7d4cea2d88a72cdc70885c0023110ab1ab6579c754cc0e604c874e3c707", None),
    "deck.monsters": (1, 0x03F9, "833e546546b6206a02145c93ce41a8af4a5d987260a9e80463d4198eb5817d07", None),
    "deck.ouch": (1, 0x0405, "5a23aae2919fcd5b11e333f740766b8edccae62608171501beb899194a12ae65", None),
    "deck.baron": (1, 0x0490, "5254fe7983efa912e6cd3dfc491ca5e48a86498fa38a1bbbd6bfe35743b63864", None),
}
# fmt: on

TARGET = "final-fantasy-ii"
# The fourteen characters' names, by the number the name command writes: Cecil,
# Kain, Rydia, Tellah, Edward, Rosa, Yang, Palom, Porom, Cid, Edge, FuSoYa,
# Golbez, Anna. The hook writes these in an Arabic message.
NAME_KEYS = tuple(f"name.{number:02X}" for number in range(14))


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts((*_SOURCES, *NAME_KEYS))


def ff4_arabic_messages(translations: TranslationSet | None = None) -> tuple[Ff4Message, ...]:
    """Every translated message, in the order of their places in the text."""
    texts = _texts(translations)
    return tuple(
        Ff4Message(key, bank, offset, digest, texts[key], skeleton)
        for key, (bank, offset, digest, skeleton) in _SOURCES.items()
    )


def ff4_arabic_names(translations: TranslationSet | None = None) -> dict[str, str]:
    """The characters' names in Arabic, by entry (``NAME_KEYS``), in the game's order."""
    texts = _texts(translations)
    return {key: texts[key] for key in NAME_KEYS}
