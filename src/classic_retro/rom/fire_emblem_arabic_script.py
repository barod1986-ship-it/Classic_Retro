"""Arabic translation of the *Fire Emblem: The Sacred Stones* (USA) new-game opening.

Messages are indices of the game's message table: the world map's narration
of Magvel (0x8DB) and the throne room of Castle Renais, from the soldier's
report to King Fado's last words (0x903..0x906). For each one the original is
identified by the SHA-256 of its decoded bytes and by its command skeleton
(commands with their arguments, no text), so the translation can be checked
without the ROM and the ROM build can refuse a different script.

The Arabic lives in ``classic_retro/translations/fire-emblem.json``: logical
Unicode Arabic in the engine's bracket notation. Commands keep their original
order; only ``[LF]`` and ``[.]`` may move, and ``[CR][LF]`` stays one unit (the
narration box skips the byte after ``[CR]``).

The legend shown before a new game is seven images, not messages; the Arabic
lines of image ``n`` (entry ``legend.n``, one line per line) are drawn into new
images (``engines.fire_emblem_legend``).
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.fire_emblem import split_notation
from classic_retro.engines.fire_emblem_arabic import TalkBox, fire_emblem_stream
from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.text.tokens import TokenStream

TARGET = "fire-emblem"
# The legend shown before a new game: one subtitle image per gOpSubtitleGfxLut entry.
LEGEND_IMAGES = 7


@dataclass(frozen=True, slots=True)
class FireEmblemArabicMessage:
    index: int
    speakers: str
    box: TalkBox
    source_sha256: str
    source_skeleton: tuple[bytes, ...]
    stream: TokenStream


@dataclass(frozen=True, slots=True)
class FireEmblemArabicSubtitle:
    """One legend image (``gOpSubtitleGfxLut`` entry) and its Arabic lines."""

    index: int
    lines: tuple[str, ...]


def _skeleton(notation: str) -> tuple[bytes, ...]:
    pieces = split_notation(notation)
    if any(isinstance(piece, str) for piece in pieces):
        raise ValueError(f"a skeleton holds commands only: {notation!r}")
    return tuple(piece for piece in pieces if isinstance(piece, bytes))


# fmt: off
# index: (speakers, box, SHA-256 of the decoded original, its commands)
_SOURCES: dict[int, tuple[str, TalkBox, str, str]] = {
    0x8DB: (
        "Narrator",
        TalkBox.WORLD_MAP,
        "b6b83ffa3f5e924a678bed03c49d16d25330f1c531972a5978571aa54465a168",
        "[A][A][A][A][CR][LF][BreakTalk][A][CR][LF][BreakTalk][A][CR][LF][BreakTalk][A][CR]"
        "[LF][BreakTalk][A][CR][LF][BreakTalk][A][CR][LF][BreakTalk][A][BreakTalk][A][CR][LF]"
        "[BreakTalk][A][A][CR][LF][BreakTalk][A][BreakTalk][A][BreakTalk][A][BreakTalk][A]"
        "[BreakTalk][A][BreakTalk][A][BreakTalk][A][CR][LF][BreakTalk][A][BreakTalk][A]"
        "[BreakTalk][X]",
    ),
    0x903: (
        "Soldier, Fado",
        TalkBox.BUBBLE,
        "0b2aa719098dab4e73e5c4c334c791bbf40f05c2f32c56c7611c434001ac811d",
        "[OpenMidLeft][LoadFace 51 01][OpenFarFarRight][LoadFace 6A 01][OpenFarFarRight]"
        "[MoveMidRight][OpenMidRight][A][CloseSpeechSlow][OpenMidRight][A][A][OpenMidLeft][A]"
        "[OpenMidRight][A][A][A][OpenMidLeft][ToggleMouthMove][ToggleMouthMove][A][A][X]",
    ),
    0x904: (
        "Eirika, Fado, Seth",
        TalkBox.BUBBLE,
        "a0602e19bbd6e7d17fa4424f6ce2e38c8087c7ee041f76299d8bee0fd0ea5fa7",
        "[OpenMidLeft][LoadFace 51 01][OpenMidRight][LoadFace 02 01][OpenMidRight][MoveRight]"
        "[OpenRight][ToggleMouthMove][ToggleMouthMove][A][OpenMidLeft][A][A][OpenRight][A]"
        "[OpenMidLeft][A][CloseSpeechSlow][OpenMidLeft][A][OpenFarRight][LoadFace 04 01]"
        "[OpenFarRight][A][OpenMidLeft][A][A][OpenFarRight][A][A][OpenMidLeft][A][A][A]"
        "[CloseSpeechSlow][OpenMidLeft][A][ToggleMouthMove][ToggleMouthMove][A][SendToBack]"
        "[OpenRight][MoveRight][OpenRight][A][A][OpenMidLeft][A][X]",
    ),
    0x905: (
        "Eirika, Seth",
        TalkBox.BUBBLE,
        "5ab13694d94b39b927cf71b7d8b2e67dd3518f20cc5ea3a1eddb30cb7f55afe8",
        "[OpenRight][LoadFace 02 01][OpenFarRight][LoadFace 04 01][OpenRight][A][SendToBack]"
        "[OpenFarRight][A][X]",
    ),
    0x906: (
        "Fado",
        TalkBox.BUBBLE,
        "a73122ba03a03b93af51c2809002388bf0edd942dddeb941dfb8dbfa3523d9ed",
        "[OpenMidLeft][LoadFace 51 01][OpenMidLeft][ToggleMouthMove][ToggleMouthMove][A][X]",
    ),
}
# fmt: on

# Every entry of translations/fire-emblem.json: the messages, then the legend images.
ENTRY_IDS: tuple[str, ...] = (
    *(f"message.{index:#x}" for index in _SOURCES),
    *(f"legend.{index}" for index in range(LEGEND_IMAGES)),
)


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts(ENTRY_IDS)


def fire_emblem_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[FireEmblemArabicMessage, ...]:
    """Magvel's narration, then the fall of Castle Renais' throne room."""
    texts = _texts(translations)
    return tuple(
        FireEmblemArabicMessage(
            index=index,
            speakers=speakers,
            box=box,
            source_sha256=digest,
            source_skeleton=_skeleton(skeleton),
            stream=fire_emblem_stream(texts[f"message.{index:#x}"], prefix=f"m{index:x}_"),
        )
        for index, (speakers, box, digest, skeleton) in _SOURCES.items()
    )


def fire_emblem_arabic_legend(
    translations: TranslationSet | None = None,
) -> tuple[FireEmblemArabicSubtitle, ...]:
    """The legend of the Sacred Stones, one entry per subtitle image."""
    texts = _texts(translations)
    return tuple(
        FireEmblemArabicSubtitle(index, tuple(texts[f"legend.{index}"].split("\n")))
        for index in range(LEGEND_IMAGES)
    )
