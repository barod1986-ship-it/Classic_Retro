"""Arabic for the Pokémon Generation II text engine, as Polished Crystal 3.2.3 has it.

The game draws text a tile at a time: one byte is one 8x8 glyph of a 1bpp font,
and a speech-box line holds 18 of them. Arabic letters do not fit an 8x8 cell
when drawn from an outline font (the reference font is illegible at 8 pixels), so
the 70 glyphs are pixel art drawn by hand (``glyphs``). Contextual forms that an
8x8 cell cannot tell apart share a glyph (``forms``), and the glyphs take the 70
codes of the English font's Latin letters, contractions and accents.

What the overlay builds from this module:

- ``forms``: the letters' joining types, each form's glyph, the glyph codes, the
  build-time shaper (``shape``, lam-alef ligatures on or off) and the charmap
  lines of the presentation forms;
- ``fonts``: the glyphs drawn into the game's 8x8 typefaces (regular and bold)
  and into its variable-width font, with the VWF widths;
- ``huffman``: the codes of the game's compressed text, from symbol counts;
- ``naming``: the runtime shaper's tables, the keyboards of the naming screen
  and mail composer, and the key phrase, with the model that proves the runtime
  shaper writes what the build writes.

The text itself, its notation and where it goes in the source are the source
overlay's (``classic_retro.source.polished_crystal``).
"""

from __future__ import annotations

from classic_retro.engines.pokemon_gen2_arabic.forms import (
    ARABIC_GLYPHS,
    CODES,
    DIGITS,
    FREE_CODES,
    GLYPH_OF_FORM,
    JOINING,
    LAMALEF,
    PRESENTATION_GLYPH,
    PUNCTUATION,
    charmap_lines,
    glyph_code,
    presentation,
    shape,
    visual_codes,
)
from classic_retro.engines.pokemon_gen2_arabic.glyphs import GLYPHS, PUNCTUATION_GLYPHS

__all__ = [
    "ARABIC_GLYPHS",
    "CODES",
    "DIGITS",
    "FREE_CODES",
    "GLYPHS",
    "GLYPH_OF_FORM",
    "JOINING",
    "LAMALEF",
    "PRESENTATION_GLYPH",
    "PUNCTUATION",
    "PUNCTUATION_GLYPHS",
    "charmap_lines",
    "glyph_code",
    "presentation",
    "shape",
    "visual_codes",
]
