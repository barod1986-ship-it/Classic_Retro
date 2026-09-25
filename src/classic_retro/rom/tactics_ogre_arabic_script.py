"""Arabic translation of the *Tactics Ogre: The Knight of Lodis* (USA) opening.

A new game opens in a harbour town on the eve of a voyage: a dark-haired young
knight, the hero, whom the player names at the end of the scene, talks with
his friend Rictor, reports to their commander and meets a fortune teller, who
asks for his name and date of birth. That is the first scene's dialogue, the
15 messages the game shows before its name screen, in the order it shows them:
messages 0 to 4, 13 to 15, 5 to 8 and 10 to 12 of the block that the new
game's scene entry (``SCENE``) reads. The block also holds a narration that
comes later and eight unused messages; those stay in English.

Each message starts with its speaker's name, shown at once (``{8B}`` up to
``{8C}``, then the typewriter), on the first line of its window. Rictor's name
is an ``{8705}`` in the original, name 5 of the game's list of characters: the
translation keeps the command, and the build writes the Arabic name out in its
place (``NAMES``).

For each message the original is pinned by its index in the block, its address
and header, the SHA-256 of its bytes (up to its final ``FF``) and its commands,
so the translation can be checked without the ROM and the ROM build can refuse
a different script. A name is pinned by its index and the SHA-256 of its bytes.

The Arabic lives in ``classic_retro/translations/tactics-ogre.json``: logical
Unicode Arabic in the engine's notation (``engines.tactics_ogre``). It keeps
every command of the original, in order: ``{8B}`` and ``{8C}`` around the
speaker's name, ``{8E}{8A}`` wait for A and start the next page and
``{8D}{8A}`` end the message. Line ends after text (``\\n``) may move. A page
holds the lines the message's header gives (the name's line counts), of at
most 176 pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.tactics_ogre import (
    Piece,
    lines_per_page,
    notation_skeleton,
    parse_notation,
)
from classic_retro.localization.translations import TranslationSet, builtin_translation_set

# The scene entry a new game reads (entry 0 shares its block), the block and
# how many messages it holds.
SCENE = 1
BLOCK_ADDRESS = 0x087843B0
BLOCK_MESSAGES = 35


@dataclass(frozen=True, slots=True)
class ToArabicMessage:
    key: str
    index: int
    source_address: int
    header: int
    speaker: str
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)

    @property
    def lines_per_page(self) -> int:
        return lines_per_page(self.header)


@dataclass(frozen=True, slots=True)
class ToArabicName:
    """A name of the game's list (``87xx``), written out in Arabic where a message uses it."""

    key: str
    index: int
    source_address: int
    source_sha256: str
    text: str


_HERO = "the dark-haired knight"
_RICTOR = "Rictor"

# key: (index, original, header, speaker, SHA-256 of the original, its commands)
# fmt: off
_SOURCES: dict[str, tuple[int, int, int, str, str, str]] = {
    "farewell": (
        0, 0x087843F8, 0x0031, _RICTOR,
        "4083a199f0abddb6427651a598277b7fd39fd8e7e1ccc6a48f5d93f98aa6b433",
        "{8B}{8C}{8D}{8A}",
    ),
    "family_name": (
        1, 0x0878444A, 0x0031, _HERO,
        "476c84be1452c9bd5a7d8b87ee8e4230067188fadc9a6d331e8185ba1e821a8a",
        "{8B}{8C}{8705}{8E}{8A}{8E}{8A}{8D}{8A}",
    ),
    "ship_departs": (
        2, 0x0878451C, 0x0031, _RICTOR,
        "9be41b9868256bc38d99b1d7c5ae832fa91582d22af498044ea48302bed26a36",
        "{8B}{8705}{8C}{8E}{8A}{8D}{8A}",
    ),
    "first_voyage": (
        3, 0x08784598, 0x0031, _HERO,
        "2e6f96ebdbb1685b87199bc875d26fcf22a3cf53e2c1c9c0880b760630300414",
        "{8B}{8C}{8D}{8A}",
    ),
    "no_holiday": (
        4, 0x087845EC, 0x0031, _RICTOR,
        "0006ac7dc6bd2a75a999ed91f672b50f58872fd57c1c3f30f2854ac347aae7b7",
        "{8B}{8705}{8C}\n{8E}{8A}{8D}{8A}",
    ),
    "commander": (
        13, 0x0878489C, 0x0031, _HERO,
        "380064f54112823b4be68d7d0256b85fe5dbc70f14599828daa85f271e43cc52",
        "{8B}{8C}{8D}{8A}",
    ),
    "first_command": (
        14, 0x087848D6, 0x0031, _RICTOR,
        "4eeffef8f6bd54b02cb6d34149da0ba85660dd65c11312179f7962be75420a8b",
        "{8B}{8705}{8C}\n{8E}{8A}{8D}{8A}",
    ),
    "count_on_me": (
        15, 0x08784954, 0x0021, _HERO,
        "e502fb81ac5636f48030380a35fceb098b60dd8f958fead123056b16812a1b6d",
        "{8B}{8C}{8D}{8A}",
    ),
    "fortune_offer": (
        5, 0x08784668, 0x0031, "a mysterious woman",
        "2355b17176429bc069e53633b657e49d20bea0af3c6ba885fcfe2f8d8aa61b3a",
        "{8B}{8C}{8D}{8A}",
    ),
    "no_time": (
        6, 0x087846B4, 0x0031, _RICTOR,
        "673783ec94958538d9071f946716199e2e00ad73be89fdf94899dfac556ddacd",
        "{8B}{8705}{8C}\n{8D}{8A}",
    ),
    "silence": (
        7, 0x087846FA, 0x0021, _HERO,
        "a48e48dbe10502745d9cb544fbb73a0ff87b66ec7cfa3987d6fea52b6d9913d9",
        "{8B}{8C}{8D}{8A}",
    ),
    "sudden_interest": (
        8, 0x0878471C, 0x0031, _RICTOR,
        "0b79659ceb2072fcd97ef65e6be10130fa2613290273e593290c7026cf4d5abb",
        "{8B}{8705}{8C}\n{8E}{8A}{8D}{8A}",
    ),
    "heading_back": (
        10, 0x0878477E, 0x0021, _RICTOR,
        "34ae082a9f32456f99f592603d5de15724fe1c40a19f8668e90ee5f397748d7c",
        "{8B}{8705}{8C}\n{8E}{8A}{8D}{8A}",
    ),
    "i_know": (
        11, 0x087847D2, 0x0021, _HERO,
        "9d0c545527c617a6e7cd86d9916ce0071997b1be04718f3997feddd115880607",
        "{8B}{8C}{8D}{8A}",
    ),
    "fortune_teller": (
        12, 0x087847FA, 0x0031, "the fortune teller",
        "b941f3d7ee59c4d11c620cb6acfe33f1d7dd02ceb90f031b5f4ba63abb735b3e",
        "{8B}{8C}{8E}{8A}{8D}{8A}",
    ),
}
# key: (index in the list, original, SHA-256 of the original)
_NAMES: dict[str, tuple[int, int, str]] = {
    "rictor": (
        5, 0x08623E41, "2f2878f715fe47a18fd115eadcdf79756938e728fb0b81c87af15d0a77fdb9c1",
    ),
}
# fmt: on

TARGET = "tactics-ogre"


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts((*_SOURCES, *_NAMES))


def tactics_ogre_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[ToArabicMessage, ...]:
    """Every translated message, in the order the game shows them."""
    texts = _texts(translations)
    return tuple(
        ToArabicMessage(
            key=key,
            index=index,
            source_address=source,
            header=header,
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (index, source, header, speaker, digest, skeleton) in _SOURCES.items()
    )


def tactics_ogre_arabic_names(
    translations: TranslationSet | None = None,
) -> tuple[ToArabicName, ...]:
    """The names the translated messages write out."""
    texts = _texts(translations)
    return tuple(
        ToArabicName(
            key=key, index=index, source_address=source, source_sha256=digest, text=texts[key]
        )
        for key, (index, source, digest) in _NAMES.items()
    )
