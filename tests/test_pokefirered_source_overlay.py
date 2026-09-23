from __future__ import annotations

from classic_retro.engines.pokemon_gen3_arabic import build_arabic_glyph_map
from classic_retro.source import pokefirered_arabic as overlay


def test_charmap_overlay_adds_rtl_controls_and_all_arabic_glyphs():
    original = "RESUME_MUSIC = FC 18\n"
    patched = overlay._patch_charmap(original)
    glyph_map = build_arabic_glyph_map()

    assert "RTL = FC 19" in patched
    assert "LTR = FC 1A" in patched
    assert len([line for line in patched.splitlines() if line.startswith("'")]) == len(
        glyph_map.characters
    )


def test_text_printer_overlay_adds_per_printer_rtl_state():
    original = "    sTempTextPrinter.japanese = 0;\n"
    patched = overlay._patch_text_printer(original)

    assert "sTempTextPrinter.rtl = FALSE" in patched
    assert "sTempTextPrinter.rtlX = textSubPrinter->x" in patched
