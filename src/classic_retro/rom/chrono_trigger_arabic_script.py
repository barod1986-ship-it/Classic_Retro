"""Arabic translation of three messages of *Chrono Trigger* (USA): the opening.

The game opens in Crono's room: his mother wakes him, and when he comes down
she reminds him of Lucca. The translation takes three of her messages, chosen
to be unlike: a short one of two lines under her name, a long one the encoder
wraps over two lines and a second box, and one that writes Lucca's name, which
the player may change. Every other message stays in English.

Each original is pinned by its string table (``STRING_TABLE``, $F7:0000: the
opening's), its number there and the SHA-256 of its bytes (its zero
included), so the translation can be checked without the ROM and the build
refuses another text.

The Arabic lives in ``classic_retro/translations/chrono-trigger.json``: logical
Unicode Arabic in the engine's notation (``engines.chrono_trigger_arabic``): a
line for each box, ``{line}`` where a line of the box must end, and a
``{name}`` token for a name the game writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.localization.translations import TranslationSet, builtin_translation_set

# $F7:0000: the string table of the opening's messages (as a file offset).
STRING_TABLE = 0x370000


@dataclass(frozen=True, slots=True)
class ChronoTriggerMessage:
    """A translated message: its entry, its table and number, and its original's
    SHA-256."""

    key: str
    table: int
    index: int
    source_sha256: str
    notation: str


# key: (the message's number in STRING_TABLE, SHA-256 of its bytes with the zero)
# fmt: off
_SOURCES: dict[str, tuple[int, str]] = {
    "opening.get_up": (6, "20455acd161dc69469d5fbd332d0f231a9355414c51f913b433257da9f6d5b09"),
    "opening.the_fair": (8, "ce65e4dd6b46292b2fd40f2a524a7dfc9690dcb387282fd1135da8f375128809"),
    "opening.lucca": (11, "3cfee175c793fe5da8e60959975fa5ceda92e15c668df2b545d27638a747bfba"),
}
# fmt: on

TARGET = "chrono-trigger"


def chrono_trigger_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[ChronoTriggerMessage, ...]:
    """Every translated message, in the order of the table."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        ChronoTriggerMessage(key, STRING_TABLE, index, digest, texts[key])
        for key, (index, digest) in _SOURCES.items()
    )
