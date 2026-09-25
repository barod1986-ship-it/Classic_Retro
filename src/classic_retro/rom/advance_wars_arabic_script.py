"""Arabic translation of the *Advance Wars* (USA, Rev 1) opening.

A new game opens on Nell, an Orange Star CO, in the dialogue box. She
welcomes the player, asks for a name (the name entry screen), confirms it,
introduces herself and asks whether this is the first time playing:

- yes: her overview of the game modes, then the first lesson of Field
  Training;
- no: she offers a quicker way and asks whether to go through Field Training
  all the same. Yes gives her advice on the Mode Select menu and the first
  lesson; no gives the modes and the quick way (the last Field Training
  mission).

Those are 14 messages, all shown by the event scripts' message command
``0x19``.

For each one the original is pinned by the address of the script's pointer
to it, its address, the SHA-256 of its bytes (up to its final 0x00) and its
control codes, so the translation can be checked without the ROM and the ROM
build can refuse a different script.

The Arabic lives in ``classic_retro/translations/advance-wars.json``: logical
Unicode Arabic in the engine's notation (``engines.advance_wars``). It keeps
every control code of the original, in order: ``{0F}`` ends a page (the key
arrow), ``{15}`` is the player's name and ``{16}`` asks Yes/No on a line of
its own, where the answers are drawn. Line ends after text (``\\n``) may move;
a page holds two lines.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.advance_wars import Piece, notation_skeleton, parse_notation
from classic_retro.localization.translations import TranslationSet, builtin_translation_set

# The script command that shows a message: its opcode word, then the message.
MESSAGE_COMMAND = 0x19


@dataclass(frozen=True, slots=True)
class AwArabicMessage:
    key: str
    pointer: int
    source_address: int
    speaker: str
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


_PAGES = {n: "{0F}" * n for n in range(1, 13)}

# key: (script pointer, original message, SHA-256 of the original, its codes)
# fmt: off
_SOURCES: dict[str, tuple[int, int, str, str]] = {
    "welcome": (
        0x082F0B7C, 0x082EFE84,
        "cc312f40238ba1e51977b6bc63b7110ad211b37df344a26ca9025c55f98b800a", _PAGES[1],
    ),
    "name_prompt": (
        0x082F06BC, 0x082EFE3C,
        "40d2810bb9ab9b42df95e00e49f1425f6cbdedabc6059e9d9ee45e46e739eee2", _PAGES[1],
    ),
    "name_confirm": (
        0x082F087C, 0x082EFE70,
        "fac74bceebc547a4d3d0cbf185908102702fbac1b6b526b76b023a20dad8b1cd", "{16}",
    ),
    "nice_to_meet": (
        0x082F0C0C, 0x082EFEA0,
        "8665e69e65d75ad6243b66c6aa41a3d6f49554ef02512a73f6528915197edb5d", "{15}{0F}{0F}",
    ),
    "orange_star_co": (
        0x082F0C2C, 0x082EFEC8,
        "4463eb3b8fa85b35365dd4cff9d5271809bdfdc9b4126732e8ec69cd900c6c16", _PAGES[1],
    ),
    "first_time": (
        0x082F0C4C, 0x082EFEEC,
        "21d6740f61def6a62f548494a4a9a583e66892df3e300a7825c6de482cee6157", "{16}",
    ),
    "modes_first_time": (
        0x082F0D3C, 0x082EFF10,
        "7373f54537973049f051012454e2e8bd0439dfaace2dc42201fb8ba1c8f07c5d", _PAGES[12],
    ),
    "first_lesson": (
        0x082F0D5C, 0x082F015C,
        "3c32acc7e8de2a735998cc08272037177ea66a6173f9e36f2516a1bd263aeca1", _PAGES[1],
    ),
    "quick_way": (
        0x082F0C6C, 0x082F0194,
        "43486e2854cd9f8203a9f4bc8c182211902481f924bfa2b463269b685c9f8ed3",
        _PAGES[7] + "{16}",
    ),
    "for_the_best": (
        0x082F0DFC, 0x082F02B8,
        "5ad5b97ea43eda6786657741291cdca0e4f5b0490ee50208abb4cc52478b4e97", _PAGES[1],
    ),
    "mode_select": (
        0x082F0E1C, 0x082F02D8,
        "35b2558205c529337197a79a34760b17b1f7575ad18f8182422a64746fdb35c3", _PAGES[6],
    ),
    "first_lesson_luck": (
        0x082F0E3C, 0x082F0414,
        "131a206eaacd985970e6af39c303356ede53f45916b00cbdd722432a89233a4a", _PAGES[1],
    ),
    "modes_fog_of_war": (
        0x082F0C8C, 0x082F0448,
        "50916f6facae741d0ed858dc1506d66b0e3a473c3eaf5b9402af444aad0c413b", _PAGES[9],
    ),
    "move_out": (
        0x082F0CAC, 0x082F0608,
        "8d79850230a97b61ceb9ec7ad2070b7e1cc545b2e24302be0a5fbfdc425ffacc", _PAGES[1],
    ),
}
# fmt: on

TARGET = "advance-wars"


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))


def advance_wars_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[AwArabicMessage, ...]:
    """Every translated message, in the order the opening can show them."""
    texts = _texts(translations)
    return tuple(
        AwArabicMessage(
            key=key,
            pointer=pointer,
            source_address=source,
            speaker="Nell",
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (pointer, source, digest, skeleton) in _SOURCES.items()
    )
