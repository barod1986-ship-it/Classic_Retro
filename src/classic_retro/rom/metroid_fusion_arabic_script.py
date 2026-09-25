"""Arabic translation of the *Metroid Fusion* (USA) opening.

A new game opens on the intro: Samus tells how she was infected by the X on
SR388, how her ship drifted into an asteroid belt, how her suit was removed
and how a vaccine made from Metroid cells saved her. Then the ship's computer
announces the arrival at the B.S.L station, and Samus reflects on her mission
and her new commanding officer. Those are 12 of the game's 19 monologues, in
the English list ``MONOLOGUE_LIST``, which the intro's scenes read by index:
eleven go through its two-line strip (``STRIP``; the ship computer's line is
typed with a sound in its own box), and the last one fills a page of nine
lines (``PAGE``).

On the station, the ship's computer gives Samus her first briefing on the map
(``BRIEFING``): the first text of the briefings' list ``NAVIGATION_LIST``,
and the second, what it says when she comes back. The briefing asks whether
her objective is clear, and the game asks again, later, whether she confirms
it: the two questions (``QUESTION_BOX``) are messages 43 and 44 of
``MESSAGE_LIST``, the same in every briefing.

For each text the original is pinned by its list, its index there, its
address, the SHA-256 of its units (up to its final ``FF00``) and its commands,
so the translation can be checked without the ROM and the ROM build can
refuse a different script.

The Arabic lives in ``classic_retro/translations/metroid-fusion.json``: logical
Unicode Arabic in the engine's notation (``engines.metroid_fusion``). It keeps
every command of the original, in order: in the intro, ``{FC00}`` waits for A
with the arrow, ``{FD00}`` starts a new page and ``{E1xx}`` waits ``xx``
frames; a briefing also sets colours (``{81xx}``), starts its music
(``{B003}``), shows the target on the map (``{E000}``) and asks its question
(``{FB00}``); a question places its options (``{83xx}``). Line ends after text
(``\\n``) may move, and so may a pen advance's amount (``{80xx}``). A strip page
holds two lines, a monologue page nine, a briefing's box two and a question a
line and its options, of at most 224 pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.metroid_fusion import (
    MESSAGES,
    MONOLOGUES,
    NAVIGATION_TEXTS,
    Piece,
    notation_skeleton,
    parse_notation,
)
from classic_retro.engines.metroid_fusion_arabic import (
    BRIEFING,
    PAGE,
    QUESTION_BOX,
    RENDERER_DIALECTS,
    STRIP,
)
from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class MfTextList:
    """An English list of texts: where it is and how many it holds."""

    name: str
    address: int
    length: int


MONOLOGUE_LIST = MfTextList("monologue", 0x0879E6EC, MONOLOGUES)
NAVIGATION_LIST = MfTextList("briefing", 0x0879D50C, NAVIGATION_TEXTS)
MESSAGE_LIST = MfTextList("message", 0x0879C810, MESSAGES)
TEXT_LISTS = (MONOLOGUE_LIST, NAVIGATION_LIST, MESSAGE_LIST)


@dataclass(frozen=True, slots=True)
class MfArabicMessage:
    key: str
    text_list: MfTextList
    index: int
    source_address: int
    renderer: str
    speaker: str
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pointer(self) -> int:
        """Where the list holds this text's address."""
        return self.text_list.address + 4 * self.index

    @property
    def dialect(self) -> str:
        return RENDERER_DIALECTS[self.renderer]

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation, self.dialect)


def _pages(count: int) -> str:
    return "{FD00}".join(["{FC00}"] * count)


# The first briefing's commands: its music, the colour of every name, the
# boxes it clears, the target on the map and the question.
_PLACE = "{8102}{8100}"
_FIRST_BRIEFING = (
    "{B003}" + _PLACE + "{FD00}{FD00}" + _PLACE + "{FD00}{8103}{8100}{FD00}{E000}{FD00}"
    + _PLACE + "{FD00}{FD00}{8103}{8100}{FD00}{FD00}" + _PLACE + "{FB00}" + _PLACE
)  # fmt: skip
# A question: its line, pushed to the middle, then its options.
_QUESTION = "{8000}{8000}{8340}{83A0}"

# key: (list, index, original, renderer, speaker, SHA-256 of the original, its commands)
# fmt: off
_SOURCES: dict[str, tuple[MfTextList, int, int, str, str, str, str]] = {
    "watching_biologic": (
        MONOLOGUE_LIST, 8, 0x0872192E, STRIP, "Samus",
        "bb963a288cfe0ef79f66fdd8ecb62fdb4d2d83b504db646ab1ee262197f4042e", _pages(2),
    ),
    "attacked": (
        MONOLOGUE_LIST, 9, 0x08721A12, STRIP, "Samus",
        "f8779de118512aeb8d5cb0b113aa419f1436e8bbf539ce3f0feee98f4f9807c5", _pages(2),
    ),
    "the_x": (
        MONOLOGUE_LIST, 10, 0x08721AB6, STRIP, "Samus",
        "77061390ff73cf1e6611271f69952f71fc0150ff3c168abd28761a4d6c3b6a59", _pages(4),
    ),
    "asteroid_belt": (
        MONOLOGUE_LIST, 11, 0x08721C28, STRIP, "Samus",
        "af9332c3051a7b4cd6e35e5c44027a1ad26b1e49f010ac9bde2947fc80aca00d", _pages(2),
    ),
    "escape_pod": (
        MONOLOGUE_LIST, 12, 0x08721D12, STRIP, "Samus",
        "6580422689b42c8a67b9ddcc359a12685837236ff7cdd98b24f04e4184e02f84",
        _pages(3) + "{FC00}{FD00}{E132}" + _pages(2),
    ),
    "suit_integrated": (
        MONOLOGUE_LIST, 13, 0x08721F20, STRIP, "Samus",
        "5da5ad2d9c4ccb393883d278ca23383a905217ea03eee8e73b62582b76d99f98", _pages(3),
    ),
    "surgery": (
        MONOLOGUE_LIST, 14, 0x08722068, STRIP, "Samus",
        "b7c33ee1ad99e27a489d5df9d564759f395fbb63f453e5b5965cc60fb0000628", _pages(4),
    ),
    "vaccine": (
        MONOLOGUE_LIST, 15, 0x08722238, STRIP, "Samus",
        "825b7794dba89c01f236cb6b1a2cb2cdb8c8f48579fc5773d34691aa6b525f6a",
        "{FC00}" + _pages(5),
    ),
    "reborn": (
        MONOLOGUE_LIST, 16, 0x08722438, STRIP, "Samus",
        "0a5dc6025a3e1a4c13ec6744786b6a5c9b4d1674e860613f3c7ab598372ed054",
        _pages(2) + "{FC00}{FD00}" + _pages(2),
    ),
    "metroid_hatchling": (
        MONOLOGUE_LIST, 17, 0x08722550, STRIP, "Samus",
        "ed121a58d2fbbdd53a0ad705a6620639a3850a10ee0b578b7bd328d828b0b8de", _pages(2),
    ),
    "arriving": (
        MONOLOGUE_LIST, 18, 0x087225F8, STRIP, "the ship's computer",
        "c6637bb4269202d3184a2d5f4176b28c7a492f3b08a5960a9ce34a1d423e47cd", _pages(2),
    ),
    "new_mission": (
        MONOLOGUE_LIST, 0, 0x0871FAD4, PAGE, "Samus",
        "8d2e13f97ca44fdacad9fda8440d0d46c91ca167b1675b49c274ef2b95d7e343", _pages(4),
    ),
    "first_briefing": (
        NAVIGATION_LIST, 0, 0x086CE8B0, BRIEFING, "the ship's computer",
        "827ac721efb9299db4db540614bacd6f2c454335b83cc2798a9b14799cca6d78", _FIRST_BRIEFING,
    ),
    "first_briefing_again": (
        NAVIGATION_LIST, 1, 0x086CEC7A, BRIEFING, "the ship's computer",
        "4f36144d6147efd4a4b1547e75b1f98e9fdab4abcc6f43454a20b9a14e9076de", _PLACE,
    ),
    "objective_clear": (
        MESSAGE_LIST, 43, 0x086B5984, QUESTION_BOX, "the ship's computer",
        "b555fd134167792e4e6def55f4826199c7b21d4cf6c1009e60c329ec7a101aa3", _QUESTION,
    ),
    "confirm_objective": (
        MESSAGE_LIST, 44, 0x086B59CC, QUESTION_BOX, "the ship's computer",
        "d08828f1a736b41e956385e341a9fc2d8d3998e1226949b358df58c9602204d5", _QUESTION,
    ),
}
# fmt: on

TARGET = "metroid-fusion"


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))


def metroid_fusion_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[MfArabicMessage, ...]:
    """Every translated text, in the order the game shows them."""
    texts = _texts(translations)
    return tuple(
        MfArabicMessage(
            key=key,
            text_list=text_list,
            index=index,
            source_address=source,
            renderer=renderer,
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=notation_skeleton(
                parse_notation(skeleton, RENDERER_DIALECTS[renderer])
            ),
            notation=texts[key],
        )
        for key, (
            text_list,
            index,
            source,
            renderer,
            speaker,
            digest,
            skeleton,
        ) in _SOURCES.items()
    )
