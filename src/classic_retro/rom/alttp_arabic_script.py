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
Its command skeleton (``engines.alttp.command_skeleton``: its commands with
their bytes, but the layout) may be pinned too, so the translation's commands
are checked without the ROM as the build checks them against the ROM's; the
build's report carries every original's, for pinning.

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
    """A translated message: its entry, its number, its original's SHA-256 and, when
    pinned, its original's command skeleton."""

    key: str
    index: int
    source_sha256: str
    notation: str
    source_skeleton: tuple[str, ...] | None = None


# key: (the message's number, SHA-256 of its bytes with the end, its commands; None
# until a maintainer pins them from the ROM, as the build's report gives them)
# fmt: off
_SOURCES: dict[str, tuple[int, str, tuple[str, ...] | None]] = {
    "house.uncle": (0x0D, "3d2993c3f16d97a6cabc192e23a49eaf99b7d1d85fb5e1e5852238a7b71cf828", None),
    "house.zelda_calls": (0x1F, "fb98a84f1bfa5c0dd71663221eb633905ba32c2a88af02b082d2fc11511df7df", None),
    "house.lamp": (0x51, "906ce06493459e0e9245d8f1cdca519bb12e63c27227c4336b497c84d8dfa2a5", None),
}
# fmt: on

TARGET = "link-to-the-past"


def alttp_arabic_messages(translations: TranslationSet | None = None) -> tuple[AlttpMessage, ...]:
    """Every translated message, in the order of their numbers."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        AlttpMessage(key, index, digest, texts[key], skeleton)
        for key, (index, digest, skeleton) in _SOURCES.items()
    )
