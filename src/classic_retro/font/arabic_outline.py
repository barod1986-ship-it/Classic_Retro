"""Select contextual Arabic outlines from a user-supplied TTF/OTF font.

Game fonts store one bitmap per Arabic presentation form. Many modern fonts do
not map the Unicode Presentation Forms blocks and instead reach contextual
outlines through OpenType substitutions. These helpers ask HarfBuzz for the
outline of each form and expose it through an in-memory cmap so that Pillow can
rasterize it without a second shaping pass. The user's font file is never
modified or redistributed.
"""

from __future__ import annotations

import unicodedata
from io import BytesIO
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTFont, TTLibError

from classic_retro.core.errors import ClassicRetroError, ErrorCode

_JOINING_FORMS = {"<isolated>", "<initial>", "<medial>", "<final>"}


def presentation_form(character: str) -> str | None:
    """Return '<initial>', '<medial>', '<final>' or '<isolated>' for a presentation form."""
    decomposition = unicodedata.decomposition(character).split()
    if decomposition and decomposition[0] in _JOINING_FORMS:
        return decomposition[0]
    return None


def joins_right_neighbour(character: str) -> bool:
    """True when the glyph connects to the glyph painted on its right (medial/final)."""
    return presentation_form(character) in {"<medial>", "<final>"}


def joins_left_neighbour(character: str) -> bool:
    """True when the glyph connects to the glyph painted on its left (initial/medial)."""
    return presentation_form(character) in {"<initial>", "<medial>"}


def font_glyph_text(character: str) -> str:
    """Ask OpenType for a contextual form without requiring presentation-form cmap entries."""
    decomposition = unicodedata.decomposition(character).split()
    if len(decomposition) == 2 and decomposition[0] in _JOINING_FORMS:
        form, codepoint = decomposition
        before = "‍" if form in {"<medial>", "<final>"} else ""
        after = "‍" if form in {"<medial>", "<initial>"} else ""
        return before + chr(int(codepoint, 16)) + after
    return character


def contextual_font_data(font_path: Path, characters: tuple[str, ...]) -> bytes:
    """Map game slot identifiers to HarfBuzz-selected outlines in an in-memory font.

    Glyph zero is .notdef, even when it has visible rectangle pixels, so a font
    without a real outline for one of the requested forms is rejected.
    """
    raw = font_path.read_bytes()
    try:
        parsed = TTFont(BytesIO(raw), recalcTimestamp=False)
    except TTLibError as exc:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Invalid TTF/OTF font file") from exc
    with parsed as font:
        if "cmap" not in font:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED, "Font has no Unicode character map"
            )
        shaper = hb.Font(hb.Face(raw))
        glyph_order = font.getGlyphOrder()
        mappings = {}
        for character in characters:
            buffer = hb.Buffer()
            buffer.add_str(font_glyph_text(character))
            buffer.guess_segment_properties()
            buffer.flags = hb.BufferFlags.REMOVE_DEFAULT_IGNORABLES
            hb.shape(shaper, buffer, {"liga": False, "rlig": False})
            glyphs = buffer.glyph_infos
            if not glyphs or any(glyph.codepoint == 0 for glyph in glyphs):
                raise ClassicRetroError(
                    ErrorCode.FONT_BUILD_FAILED,
                    f"Selected font has no Arabic glyph for U+{ord(character):04X}",
                )
            if len(glyphs) != 1 or any(
                position.x_offset or position.y_offset for position in buffer.glyph_positions
            ):
                raise ClassicRetroError(
                    ErrorCode.FONT_BUILD_FAILED,
                    f"U+{ord(character):04X} requires composite placement; select another font",
                )
            mappings[ord(character)] = glyph_order[glyphs[0].codepoint]
        for table in font["cmap"].tables:
            if table.isUnicode() and table.format != 14:
                table.cmap.update(mappings)
        output = BytesIO()
        font.save(output)
        return output.getvalue()
