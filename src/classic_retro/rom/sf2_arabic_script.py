"""Arabic translation of three strings of *Shining Force II* (USA): a new game.

A new game opens in a forest, where a witch greets the player, tells them she
has put a spell on them, and asks their name. The translation takes three of
her strings, chosen to be unlike: her first, which clears the window and keeps
it waiting; her second, whose three English lines the encoder lays out again;
and the one that says the name the player gives. Every other string stays in
English.

Each original is pinned by its number and the SHA-256 of its bytes as the game
stores them (the length byte and the Huffman code), so the translation can be
checked without the ROM and the build refuses another text. Its command
skeleton (``engines.sf2.command_skeleton``: its tags with their arguments,
but the new lines) may be pinned too, so the translation's tags are checked
without the ROM as the build checks them against the ROM's; the build's
report carries every original's, for pinning.

The Arabic lives in ``classic_retro/translations/shining-force-2.json``: logical
Unicode Arabic in the English's notation (``engines.sf2_arabic``): its tags
(``{N}``, ``{W2}``, ``{CLEAR}``, ``{NAME;0}``...) pass to the game as they are.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class Sf2String:
    """A translated string: its entry, its number, its original's SHA-256 and, when
    pinned, its original's command skeleton."""

    key: str
    index: int
    source_sha256: str
    notation: str
    source_skeleton: tuple[str, ...] | None = None


# key: (the string's number, SHA-256 of its bytes as stored, its commands; None until
# a maintainer pins them from the ROM, as the build's report gives them)
# fmt: off
_SOURCES: dict[str, tuple[int, str, tuple[str, ...] | None]] = {
    "witch.greeting": (0xD8, "e9954c46b74303979716d0e1ccf443eb02481bfaf8f4709408a8bf4c0742bfee", None),
    "witch.confused": (0xD9, "ecbdc3e88e8c083f092f18fae7015f878102424c49ca72f08d432af4dfadd76a", None),
    "witch.nice_name": (0xDF, "bf10873511e5247c15cb5d3b7007ac6ebb410d9ea6adbcf999c31c0ddc6352f6", None),
}
# fmt: on

TARGET = "shining-force-2"


def sf2_arabic_strings(translations: TranslationSet | None = None) -> tuple[Sf2String, ...]:
    """Every translated string, in the order of their numbers."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        Sf2String(key, index, digest, texts[key], skeleton)
        for key, (index, digest, skeleton) in _SOURCES.items()
    )
