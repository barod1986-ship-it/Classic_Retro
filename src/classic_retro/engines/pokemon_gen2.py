"""The Pokémon Generation II text engine, as the Game Boy Color games and their hacks have it.

Text is a byte a tile: codes ``$7f-$ff`` are 8x8 glyphs of a 1bpp font,
``$00-$09`` text commands, ``$52-$5c`` line and page codes and names the game
writes at run time. Polished Crystal compresses its speech-box text with a
Huffman code and its other strings with n-grams (``constants/charmap.asm``).
Its Arabic module is ``engines.pokemon_gen2_arabic``.
"""

from __future__ import annotations

from classic_retro.adapters.base import EngineAdapter


class PokemonGen2EngineAdapter(EngineAdapter):
    id = "gbc.pokemon-gen2"
    display_name = "Pokémon Generation II text engine"
    platform_ids = ("gbc",)
