"""Arabic translation of the prologue of *The Legend of Zelda: Phantom Hourglass* (USA).

The prologue is the story told with paper cutouts before the game starts: its
seven messages (``English/Message/demo.bmg``, 0 to 6) type out, three lines a
page, above the pictures, from the sea to the pirates setting sail. The game
goes on in English with Niko's question about the cutouts.

For each message the original is pinned by its index, the SHA-256 of its
UTF-16 text and its escapes and line ends, so the translation can be checked
without the ROM and the ROM build can refuse a different script. Every line
is measured against the box (``LINE_WIDTH``).

The Arabic lives in ``classic_retro/translations/phantom-hourglass.json``:
logical Unicode Arabic in the BMG notation (``text.bmg``). It keeps the
original's escapes and line ends, in order: the typewriter's waits
(``{01:0A00nnnn}``, ``{01:0E00nnnn}``) and pace (``{01:1400nnnn}``), and the
blue of a name (``{FF:00000300}`` to ``{FF:00000000}``).
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.text.bmg import Piece, notation_skeleton, parse_notation

TARGET = "phantom-hourglass"


@dataclass(frozen=True, slots=True)
class PhArabicMessage:
    key: str
    index: int
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


# key: (index in demo.bmg, SHA-256 of the original, its escapes and line ends)
# fmt: off
_SOURCES: dict[str, tuple[int, str, str]] = {
    "story_begins": (
        0, "2b1bced0a796536979614a055b2b3852ea86202a39ffa0f51c18c63c6e493ea7",
        "{01:14000600}{01:0A001400}\n{01:0A000800}{01:0A000800}\n{01:0E00BE00}",
    ),
    "tetra": (
        1, "be706fe71df5bf24b78a410f6df19bb52e282a34402afabf953c28cb8a5b0d86",
        "{01:14000200}{01:0A001900}{01:14000400}\n\n{01:0E00DC00}\n"
        "{01:0A000500}{01:14000400}{01:0A000F00}{FF:00000300}{FF:00000000}{01:0A000F00}\n\n"
        "{01:0E00E600}\n{01:14000400}{01:0A000A00}{01:0A000600}\n{01:0A000A00}\n{01:0E00E100}",
    ),
    "boy_in_green": (
        2, "8a93c1512d744879202ccf5f9d78aad8c0bdf24c63be15eeb84052331325b136",
        "{01:0A001900}{01:14000300}\n{01:0A001900}\n{01:0E000E01}\n{01:14000400}{01:0A000A00}\n"
        "\n{01:0A000500}{01:0A000A00}{01:0A000F00}{01:0E000B01}",
    ),
    "princess_zelda": (
        3, "dd4aacd1b3c08f6b3944b689f29aa1de802bef5df12ded6962a2c92257286465",
        "{01:14000300}\n\n{01:0E007D00}\n{01:14000300}\n\n{01:0E007D00}\n{01:14000200}\n\n"
        "{01:0E006E00}\n{01:14000300}{FF:00000300}{FF:00000000}\n\n{01:0E008C00}",
    ),
    "evil_king": (
        4, "c44c34849b9457f3b56c1b4111daa22fa5b4e5c71c7ce4522b141db94ab8db34",
        "{01:14000300}{01:0A002400}\n\n{01:0E001801}\n{01:14000300}\n"
        "{01:0A000800}{01:0A000C00}{01:0A001000}\n{01:0E00B900}\n{01:14000300}\n\n{01:0E00B400}\n"
        "{01:14000300}\n\n{01:0E00C300}\n{01:14000400}\n\n"
        "{01:0A000800}{01:0A000C00}{01:0A001000}{01:0E00C800}",
    ),
    "hero": (
        5, "a873382ff10c064fcaec36b4a33075ea82cf3ec878b476eff67e7a466543675a",
        "{01:14000400}\n{01:0E00B400}\n\n{01:14000400}\n\n{01:0E000401}\n{01:14000400}\n\n"
        "{01:0E000401}\n{01:14000400}\n\n{01:0E000401}",
    ),
    "set_sail": (
        6, "6c880853785c05c38115c359abdcb7082770a228f7d8b9d26ca35c77bb737b1b",
        "{01:0A000500}{01:14000100}{01:0A001400}{01:14000400}\n\n{01:0E00C800}{FF:00000300}\n"
        "{FF:00000000}{01:14000400}{01:0A006400}\n{01:14000100}\n"
        "{01:0A001400}{01:14000100}{01:0E00E600}",
    ),
}
# fmt: on


def ph_arabic_messages(translations: TranslationSet | None = None) -> tuple[PhArabicMessage, ...]:
    """The prologue's messages, in order."""
    texts = (translations or builtin_translation_set(TARGET)).texts(_SOURCES)
    return tuple(
        PhArabicMessage(
            key=key,
            index=index,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (index, digest, skeleton) in _SOURCES.items()
    )
