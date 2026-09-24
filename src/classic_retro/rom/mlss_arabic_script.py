"""Arabic translation of the *Mario & Luigi: Superstar Saga* (USA) opening.

A new game starts with three scenes before the first battle:

- Princess Peach's castle: the Beanbean Kingdom's ambassador arrives with a
  gift, and her laugh gives her away; subtitles in the letterbox bar
  (4 messages, 6 pages);
- the Mario Bros.' house: a Toad runs past Luigi to the house and in, calls
  for Mario, looks for him (the player walks the Toad; trying to leave gives
  one more line), hears humming at the bathroom door, and finally stammers
  the news; speech bubbles (7 messages);
- the castle again: Bowser, jumped on from behind, calls the brothers to
  fight (1 message).

Each message is reached through its group of five language pointers in the
story text table (English first). For each one the original is pinned by its
group, its address, the SHA-256 of its bytes (header and text up to and
including ``FF 0A``) and its command skeleton (commands in order; line ends
after text excluded), so the translation can be checked without the ROM and
the ROM build can refuse a different script.

Translations are logical Unicode Arabic in the engine's notation
(``engines.mlss``): they keep every command of the original, in order;
``{FF 0B 01}`` opens a page, ``{FF 01 00}`` starts the next one, ``{FF 0C nn}``
waits, ``{FF 11 01}`` waits for a key, ``{FF 31}``/``{FF 33}`` double the
glyphs, ``{FF 35}`` centres the line and ``{FF 41}{FF 25}`` pick the subtitle
font list and colour. Line ends after text (``\\n``) may move; the empty first
line of every subtitle page stays.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.mlss import Piece, notation_skeleton, parse_notation

# The story text table's groups start at 0x084E8898 (2434 of them).
STORY_TABLE = 0x084E8898


@dataclass(frozen=True, slots=True)
class MlssArabicMessage:
    key: str
    group: int
    source_address: int
    speaker: str
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)

    @property
    def english_pointer(self) -> int:
        """Where the English pointer of the message's group is stored."""
        return self.group


_SUBTITLE_PAGE = "{FF 0B 01}\n{FF 03}{FF 35}"
_SUBTITLE_START = _SUBTITLE_PAGE + "{FF 41}{FF 25}"

# key: (group, English message, speaker, SHA-256 of the original, its commands)
# fmt: off
_SOURCES: dict[str, tuple[int, int, str, str, str]] = {
    "castle_ambassador": (
        0x084EA738, 0x083EE17C, "subtitle",
        "c65ee4207dbef1fe2ddb2f58c7fda9650eb38b081bf50fb63fcb35dd70164abd",
        _SUBTITLE_START + "{FF 0C 3C}{FF 01 00}" + _SUBTITLE_PAGE + "{FF 0C 5A}{FF 0A}",
    ),
    "castle_wish": (
        0x084EA74C, 0x083EE1E0, "subtitle",
        "41aa3f469517f4ba7eeb25d5d545fbb5d507b815c3cef82819b985e62c96dfe1",
        _SUBTITLE_START + "{FF 0C 41}{FF 01 00}" + _SUBTITLE_PAGE + "{FF 0C 50}{FF 0A}",
    ),
    "castle_gift": (
        0x084EA760, 0x083EE244, "subtitle",
        "bd4c53b9b5bf61ab9bb9b4f2fcffb7d96876e0464032d9985d0f2135141d1f8e",
        _SUBTITLE_START + "{FF 0C 46}{FF 0A}",
    ),
    "castle_laugh": (
        0x084EA774, 0x083EE27C, "subtitle",
        "04af3cbc58ed0d3bdc5e64527d4b5c460621af1fccc91478f27a32da3a62db3b",
        "{FF 0B 01}\n{FF 03}{FF 41}{FF 25}{FF 0C 3C}{FF 0A}",
    ),
    "house_emergency": (
        0x084E998C, 0x083EA0B4, "Toad",
        "720346f948971034c15e21220d265404620fd6447286abaca26033e35498cce2",
        "{FF 0B 01}{FF 03}{FF 31}{FF 35}{FF 11 01}{FF 0A}",
    ),
    "house_courier": (
        0x084E99A0, 0x083EA0E0, "Toad",
        "527e5b15e7ab1b137abe6e4c8ebb3f475ab26eceb50afb331acf6b0ab3326158",
        "{FF 0B 01}{FF 03}{FF 31}{FF 35}{FF 11 01}{FF 0A}",
    ),
    "house_mario": (
        0x084E99B4, 0x083EA114, "Toad",
        "6eec594ce6b89036654f8a4fdccadc0162e53c1069b30e089b6c1c978801c4ba",
        "{FF 0B 01}{FF 03}{FF 35}{FF 33}{FF 0C 1E}{FF 0A}",
    ),
    "house_find_mario": (
        0x084E99C8, 0x083EA134, "Toad",
        "62057cdc0ae5d4e3dfacb2a5f2b18f98aad6eabbdb1c923b8014625f5fe9aeca",
        "{FF 0B 01}{FF 11 01}{FF 0A}",
    ),
    "house_humming": (
        0x084E99DC, 0x083EA160, "Toad",
        "c63ad7b488e168811312c6d4da8ac0f7a5141c5fcf9bdb8b310e73d63704f574",
        "{FF 0B 01}{FF 11 01}{FF 0A}",
    ),
    "house_eek": (
        0x084E99F0, 0x083EA184, "Mario",
        "21336787260d57a8c61f48b355f1366578ff329a347281ea971ec5ca8f99249f",
        "{FF 0B 01}{FF 03}{FF 35}{FF 33}{FF 0C 1E}{FF 0A}",
    ),
    "house_peach": (
        0x084E9A04, 0x083EA1A0, "Toad",
        "0244769ff10b3291d02699b69709b9ebfe18a6058c2de3413458423c2a939163",
        "{FF 0B 01}{FF 11 01}{FF 0A}",
    ),
    "castle_bowser": (
        0x084E9A18, 0x083EA1E0, "Bowser",
        "b615a06586dcaa2d25ddbb7cdaa182c9c96510c9f1de46f84fdb337dffc675fa",
        "{FF 0B 01}{FF 11 01}{FF 0A}",
    ),
}
# fmt: on

_ARABIC: dict[str, str] = {
    "castle_ambassador": (
        _SUBTITLE_START
        + "لقد وصل سفير النوايا الحسنة{FF 0C 3C}{FF 01 00}"
        + _SUBTITLE_PAGE
        + "من مملكة الفاصولياء.{FF 0C 5A}{FF 0A}"
    ),
    "castle_wish": (
        _SUBTITLE_START
        + "«أود أن أوطد روابط مملكتي{FF 0C 41}{FF 01 00}"
        + _SUBTITLE_PAGE
        + "بمملكة الفطر.»{FF 0C 50}{FF 0A}"
    ),
    "castle_gift": _SUBTITLE_START + "«جئت بهدية من ملكة الفاصولياء.»{FF 0C 46}{FF 0A}",
    "castle_laugh": "{FF 0B 01}\n{FF 03}{FF 41}{FF 25}«هيييه ها ها ها ها!»{FF 0C 3C}{FF 0A}",
    "house_emergency": "{FF 0B 01}{FF 03}{FF 31}{FF 35}ح-ح-ح-حالة طوارئ!{FF 11 01}{FF 0A}",
    "house_courier": "{FF 0B 01}{FF 03}{FF 31}{FF 35}هل رأيت صحيفة المملكة؟{FF 11 01}{FF 0A}",
    "house_mario": "{FF 0B 01}{FF 03}{FF 35}{FF 33}ماريووووو!!!{FF 0C 1E}{FF 0A}",
    "house_find_mario": "{FF 0B 01}يجب أن أجد ماريو فورا!{FF 11 01}{FF 0A}",
    "house_humming": "{FF 0B 01}همم... أسمع دندنة...{FF 11 01}{FF 0A}",
    "house_eek": "{FF 0B 01}{FF 03}{FF 35}{FF 33}آآآآآه!!!{FF 0C 1E}{FF 0A}",
    "house_peach": (
        "{FF 0B 01}الـ-الـ-الأميرة بـ-بـ-بيتش...\nالـ-الـ-الأميرة بـ-بـ-بيتش...{FF 11 01}{FF 0A}"
    ),
    "castle_bowser": (
        "{FF 0B 01}تهاجمني وأنا أدير ظهري، ها؟\nهذا متوقع منكما!\n"
        "تعاليا أيها الجبانان الخارقان!!!{FF 11 01}{FF 0A}"
    ),
}


def mlss_arabic_messages() -> tuple[MlssArabicMessage, ...]:
    """Every translated message, in the order the opening shows them."""
    if set(_SOURCES) != set(_ARABIC):
        raise ValueError("every pinned MLSS message needs exactly one translation")
    return tuple(
        MlssArabicMessage(
            key=key,
            group=group,
            source_address=source,
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=_ARABIC[key],
        )
        for key, (group, source, speaker, digest, skeleton) in _SOURCES.items()
    )
