"""Arabic translation of three strings of *Shining Force II* (USA): a new game.

A new game opens in a forest, where a witch greets the player, tells them she
has put a spell on them, and asks their name. The translation takes three of
her strings, chosen to be unlike: her first, which clears the window and keeps
it waiting; her second, whose three English lines the encoder lays out again;
and the one that says the name the player gives. Every other string stays in
English.

Each original is pinned by its number and the SHA-256 of its bytes as the game
stores them (the length byte and the Huffman code), so the translation can be
checked without the ROM and the build refuses another text.

The Arabic lives in ``classic_retro/translations/shining-force-2.json``: logical
Unicode Arabic in the English's notation (``engines.sf2_arabic``): its tags
(``{N}``, ``{W2}``, ``{CLEAR}``, ``{NAME;0}``...) pass to the game as they are.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class Sf2String:
    """A translated string: its entry, its number and its original's SHA-256."""

    key: str
    index: int
    source_sha256: str
    notation: str


# key: (the string's number, SHA-256 of its bytes as stored)
# fmt: off
_SOURCES: dict[str, tuple[int, str]] = {
    "witch.greeting": (0xD8, "e9954c46b74303979716d0e1ccf443eb02481bfaf8f4709408a8bf4c0742bfee"),
    "witch.confused": (0xD9, "ecbdc3e88e8c083f092f18fae7015f878102424c49ca72f08d432af4dfadd76a"),
    "witch.nice_name": (0xDF, "bf10873511e5247c15cb5d3b7007ac6ebb410d9ea6adbcf999c31c0ddc6352f6"),
}
# fmt: on

TARGET = "shining-force-2"


def sf2_arabic_strings(translations: TranslationSet | None = None) -> tuple[Sf2String, ...]:
    """Every translated string, in the order of their numbers."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        Sf2String(key, index, digest, texts[key]) for key, (index, digest) in _SOURCES.items()
    )
