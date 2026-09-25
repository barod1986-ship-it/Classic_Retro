"""Arabic translation of the Final Fantasy VI Advance (USA) new-game opening.

Messages are dialogue-bank indices. For each one the original is identified by
the SHA-256 of its bytes and by its command skeleton (commands with their
arguments, no text), so the translation can be checked without the ROM and
the ROM build can refuse a different script.

The Arabic lives in ``classic_retro/translations/ff6a.json``, in the
translators' notation (``engines.ff6a_arabic``): ``{PAGE}``, ``{PAUSE 14C}``,
``{+KEY_PAGE}`` and so on. Pages keep the original commands; only the layout
commands (newline, centre) may move. Arabic lines are 16 pixels high, so a
window holds two lines and the window-less narration band four. A page that
needs a third Arabic line in a window is split with an inserted page of the
kind the message already uses: a timed ``PAUSE, PAGE`` in the automatic
cutscene (``{+PAUSE nnn PAGE}``), a ``KEY_PAGE`` in button dialogue
(``{+KEY_PAGE}``). Message 9 is shown in the top band without a window frame,
which has the window's two-line height.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.ff6a import (
    CLOSE,
    END,
    KEY_PAGE,
    NARRATION,
    PAGE,
    PAUSE,
    TIMED_CLOSE,
)
from classic_retro.engines.ff6a_arabic import Ff6aLayout, parse_ff6a_notation
from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.text.tokens import TokenStream

TARGET = "ff6a"


@dataclass(frozen=True, slots=True)
class Ff6aArabicMessage:
    index: int
    layout: str
    source_sha256: str
    source_skeleton: tuple[int, ...]
    stream: TokenStream


# Waits are VALUE + n: n * 15 frames.
_2S, _4S, _6S = 0x14C, 0x154, 0x15C
_NARRATION_HOLD = 0x243
_NARRATION_SKELETON = (NARRATION, TIMED_CLOSE, _NARRATION_HOLD, CLOSE, END)

D = Ff6aLayout.DIALOGUE
N = Ff6aLayout.NARRATION

# index: (layout, SHA-256 of the original bytes, its commands with their arguments)
# fmt: off
_SOURCES: dict[int, tuple[str, str, tuple[int, ...]]] = {
    6: (N, "dccdea3d4fe048963130f0f1490f09f1e78c021802eca95ba5042b545001a270", _NARRATION_SKELETON),
    7: (N, "03f40d12ea79b3e8bc7e2fcf250d57acb0775dccb79f0f2671c965da7e4c9624", _NARRATION_SKELETON),
    8: (N, "cb883421c0199aeb976045b09844f94dad9d108c307eda3646de5002c85baeaf", _NARRATION_SKELETON),
    9: (D, "d52ebd77c4d6659c2883cfcc818e94eb4006e919ff26613a373a9902eb990e62", (TIMED_CLOSE, 0x16E, CLOSE, END)),
    1: (D, "722b527d4b2e091c0fe2204ab84de674fc195090f0c217a260c67867003b30bc", (PAUSE, _2S, PAGE, PAUSE, _6S, CLOSE, END)),
    2: (D, "bf748dba87a9cbf09fd145b295a22c113a521166f30ace03f3b74aea5dbc5078", (PAUSE, _4S, PAGE, PAUSE, _2S, PAGE, PAUSE, _6S, CLOSE, END)),
    3: (D, "bec16f289739fd338b54a4dd809c588f59c17c9bb8f659a26bb9515d969f354b", (PAUSE, _2S, PAGE, PAUSE, _6S, CLOSE, END)),
    4: (D, "42b28e1c492b875e92b432d03628da0978469fd98e5cd9704f7e2980d3d29534", (PAUSE, _4S, PAGE, PAUSE, _4S, CLOSE, END)),
    5: (D, "b9b16ff054c040024bf2069954736f5c64dd6bf347ee4594d8d0798cbb2e98d7", (PAUSE, _4S, CLOSE, END)),
    11: (D, "ae6c6750a5de320b230763cac24ebc8384ffa81348c2cb5a4655ee71597d5f29", (END,)),
    12: (D, "60b7c633a730889bb6100cf76beec7e5ccf3af7224718080e684e4ed48a32f80", (END,)),
    13: (D, "7fc97350d5dda51267f9011d5a38c6312c442b75670f99e9e56102d54288c832", (END,)),
    14: (D, "fa1f3ded32235330c5945fccb0964efcdab41a0a52779c331445bb21e580aeb7", (END,)),
    15: (D, "a03f1ba1f8efe7d5893e3a5cf2063277929f8bb58d536c9626c8891819793b50", (END,)),
    16: (D, "7e1a812ca1d6680ebf87327abc376556062f13a72e0a11b4fa0d0087f26a22e0", (KEY_PAGE, END)),
    17: (D, "721124866cea71b55b2fa044616469efb30da3ffa45cacf6011282fe56ae043f", (END,)),
    18: (D, "d9bf37251c8c49acbfaabfb60e404cf40932e0ef24f0d21f17e3d8444c596dee", (END,)),
    19: (D, "51f8daa817ff5d6867cfc81daafa564e8fa54ca79dc36820dc64f1642fcd6edb", (END,)),
    20: (D, "28d066cb6eb529615f7cf9d9b42f6702d42b0a185c94680b52afdbfc9e89e0ec", (END,)),
}
# fmt: on

# Every entry of translations/ff6a.json, in the order the opening plays them.
ENTRY_IDS: tuple[str, ...] = tuple(f"message.{index}" for index in _SOURCES)


def ff6a_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[Ff6aArabicMessage, ...]:
    """The new-game opening: the narration, the cliff above Narshe and the way to the mines."""
    texts = (translations or builtin_translation_set(TARGET)).texts(ENTRY_IDS)
    return tuple(
        Ff6aArabicMessage(
            index,
            layout,
            digest,
            skeleton,
            parse_ff6a_notation(texts[f"message.{index}"], f"m{index}_"),
        )
        for index, (layout, digest, skeleton) in _SOURCES.items()
    )
