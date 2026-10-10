from __future__ import annotations

from classic_retro.adapters.base import EngineAdapter


class PolishedCrystalEngineAdapter(EngineAdapter):
    """Polished Crystal v3.2.3 is not the unmodified Pokémon Crystal text engine."""

    id = "gbc.polished-crystal"
    display_name = "Polished Crystal (RGBDS source, Huffman text, multiple fonts)"
    platform_ids = ("gbc",)
