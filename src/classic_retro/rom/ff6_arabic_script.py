"""Arabic translation of *Final Fantasy III* (USA): the opening, to the end of Narshe.

A new game opens on the cliffs above Narshe: two Imperial soldiers and the
girl they lead in Magitek armour walk into the town, fight their way to the
frozen Esper, and the girl wakes in Arvis's house without her memory; the
guards come, she flees through the mines, and Locke and the Moogles get her
out. The translation takes the messages of those scenes, and the fourteen
characters' names the game writes in them. Every other message stays in
English.

Each original is pinned by its number (what the event script gives the
engine, and what the hooks match) and the SHA-256 of its bytes (its end
included), so the translation can be checked without the ROM and the build
refuses another text. Its command skeleton (``engines.ff6.command_skeleton``:
its commands with their bytes, but the layout) may be pinned too, so the
translation's commands are checked without the ROM as the build checks them
against the ROM's; the build's report carries every original's, for pinning.

The Arabic lives in ``classic_retro/translations/final-fantasy-iii.json``:
logical Unicode Arabic in the engine's notation (``engines.ff6_arabic``): a
line for each page, ``{line}`` where a line must end, ``{Terra}`` and the
other names for the characters' names, and the English's pauses and button
waits as tokens.

The messages are pinned from the user's own ROM (``extract_originals``): the
list is empty until then.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.ff6 import NAMES
from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class Ff6Message:
    """A translated message: its entry, its number, its original's SHA-256 and, when
    pinned, its original's command skeleton."""

    key: str
    number: int
    source_sha256: str
    notation: str
    source_skeleton: tuple[str, ...] | None = None


# key: (the message's number, SHA-256 of its bytes with the end, its commands; None
# until a maintainer pins them from the ROM, as the build's report gives them)
# fmt: off
_SOURCES: dict[str, tuple[int, str, tuple[str, ...] | None]] = {
}
# fmt: on

TARGET = "final-fantasy-iii"
# The fourteen characters' names, by the name the game's command writes: Terra,
# Locke, Cyan, Shadow, Edgar, Sabin, Celes, Strago, Relm, Setzer, Mog, Gau, Gogo,
# Umaro. The hook draws these in an Arabic message.
NAME_KEYS = tuple(f"name.{name.lower()}" for name in NAMES)


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts((*_SOURCES, *NAME_KEYS))


def ff6_arabic_messages(translations: TranslationSet | None = None) -> tuple[Ff6Message, ...]:
    """Every translated message, in the order of their numbers."""
    texts = _texts(translations)
    return tuple(
        Ff6Message(key, number, digest, texts[key], skeleton)
        for key, (number, digest, skeleton) in _SOURCES.items()
    )


def ff6_arabic_names(translations: TranslationSet | None = None) -> dict[str, str]:
    """The characters' names in Arabic, by entry (``NAME_KEYS``), in the game's order."""
    texts = _texts(translations)
    return {key: texts[key] for key in NAME_KEYS}
