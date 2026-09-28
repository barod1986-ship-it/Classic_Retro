"""Arabic translation of three messages of *A Link to the Past* (USA): the opening.

A new game opens in Link's house at night: Zelda calls to him in his sleep, his
uncle leaves him, and the chest in the house holds a lamp. The translation takes
three of those messages, chosen to be unlike: Zelda's call, a long one of six
pages with waits and scrolling, in the window without a frame; the uncle's
words, which start with the name the player gave; and the lamp's, an item's.
Every other message stays in English.

Each original is pinned by its number (its place among the messages, as the
game counts them) and the SHA-256 of its bytes (its end included), so the
translation can be checked without the ROM and the build refuses another text.

The Arabic lives in ``classic_retro/translations/link-to-the-past.json``: logical
Unicode Arabic in the engine's notation (``engines.alttp_arabic``): a line for
each page, ``{line}`` where a line must end, ``{Name}`` for the player's name and
the English's commands as tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class AlttpMessage:
    """A translated message: its entry, its number and its original's SHA-256."""

    key: str
    index: int
    source_sha256: str
    notation: str


# key: (the message's number, SHA-256 of its bytes with the end)
# fmt: off
_SOURCES: dict[str, tuple[int, str]] = {
    "house.uncle": (0x0D, "3d2993c3f16d97a6cabc192e23a49eaf99b7d1d85fb5e1e5852238a7b71cf828"),
    "house.zelda_calls": (0x1F, "fb98a84f1bfa5c0dd71663221eb633905ba32c2a88af02b082d2fc11511df7df"),
    "house.lamp": (0x51, "906ce06493459e0e9245d8f1cdca519bb12e63c27227c4336b497c84d8dfa2a5"),
}
# fmt: on

TARGET = "link-to-the-past"


def alttp_arabic_messages(translations: TranslationSet | None = None) -> tuple[AlttpMessage, ...]:
    """Every translated message, in the order of their numbers."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        AlttpMessage(key, index, digest, texts[key]) for key, (index, digest) in _SOURCES.items()
    )
