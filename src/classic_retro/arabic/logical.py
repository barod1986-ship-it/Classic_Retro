"""What logical Arabic text may hold, and the errors for what a game cannot draw.

Translations are written in logical order with ordinary Arabic letters. The
toolkit shapes them and decides their direction, so the text itself holds no
presentation forms and no direction controls.
"""

from __future__ import annotations

import unicodedata

from classic_retro.core.errors import ClassicRetroError, ErrorCode

# Embeddings, overrides and isolates: never in logical text.
EXPLICIT_DIRECTION_CONTROLS = frozenset(
    chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))
)
# With the direction marks (LRM, RLM, ALM): all a translation file refuses.
DIRECTION_CONTROLS = EXPLICIT_DIRECTION_CONTROLS | {"\u200e", "\u200f", "\u061c"}
# Arabic Presentation Forms-A and -B: shaped glyphs, not letters.
PRESENTATION_FORM_RANGES = ((0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


def is_presentation_form(character: str) -> bool:
    return any(start <= ord(character) <= end for start, end in PRESENTATION_FORM_RANGES)


def is_arabic_letter(character: str) -> bool:
    return unicodedata.category(character).startswith("L") and "ARABIC" in unicodedata.name(
        character, ""
    )


def check_logical_arabic(text: str, profile: str) -> None:
    """Refuse direction controls, presentation forms and vowel marks.

    For renderers that draw whole lines from logical text and have no place for
    harakat. ``profile`` names the renderer in the errors ("MMBN Arabic").
    """
    for character in text:
        if character in DIRECTION_CONTROLS:
            raise ClassicRetroError(
                ErrorCode.EXPLICIT_BIDI_CONTROL, f"{profile} text takes no bidi controls"
            )
        if is_presentation_form(character):
            raise ClassicRetroError(
                ErrorCode.PRE_SHAPED_ARABIC_INPUT,
                f"Write logical Arabic, not presentation form U+{ord(character):04X}",
            )
        if unicodedata.category(character) == "Mn":
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_ARABIC_MARK,
                f"{profile} v1 has no vowel marks (U+{ord(character):04X})",
            )


def no_glyph(character: str, profile: str) -> ClassicRetroError:
    """The error for a character the game's fonts cannot draw.

    ``profile`` names the font ("Golden Sun Arabic"). An Arabic letter means a
    form the glyph set lacks; anything else is text the game cannot show.
    """
    if is_arabic_letter(character):
        return ClassicRetroError(
            ErrorCode.MISSING_GLYPH, f"No {profile} glyph for U+{ord(character):04X}"
        )
    return ClassicRetroError(
        ErrorCode.UNENCODABLE_TEXT, f"{profile} text has no glyph for {character!r}"
    )
