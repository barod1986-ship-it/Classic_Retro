from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
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


def test_graphics_overlay_uses_full_width_font_container():
    original = (
        "$(FONTGFXDIR)/latin_normal.fwlatfont: $(FONTGFXDIR)/latin_normal.png\n\t$(GFX) $< $@\n"
    )
    patched = overlay._patch_graphics_rules(original)

    assert "arabic_normal.fwlatfont" in patched
    assert "arabic_normal.hwlatfont" not in patched


def test_oak_intro_overlay_replaces_only_first_speech_with_arabic_bytes():
    original = """gOakSpeech_Text_WelcomeToTheWorld::
    .string "Hello, there!\\n"
    .string "Glad to meet you!\\p"
    .string "Welcome to the world of POKéMON!\\p"
    .string "My name is OAK.\\p"
    .string "People affectionately refer to me\\n"
    .string "as the POKéMON PROFESSOR.\\p$"

gOakSpeech_Text_ThisWorld::
    .string "This world…$"
"""
    patched = overlay._patch_oak_intro(original)

    assert "CLASSIC_RETRO_ARABIC_V1 — first OAK speech" in patched
    assert "Hello, there!" not in patched
    assert "gOakSpeech_Text_ThisWorld::" in patched
    assert ".byte 0xFC, 0x19, 0xD8" in patched


def test_oak_intro_bytes_preserve_newlines_pages_and_eos():
    data = overlay._oak_intro_bytes()

    assert data[:3] == bytes.fromhex("fc19d8")
    assert data.count(0xFE) == 2
    assert data.count(0xFB) == 4
    assert data[-3:] == bytes.fromhex("fc1aff")


def test_charmap_overlay_rejects_upstream_f9_collision():
    original = "RESUME_MUSIC = FC 18\nEXISTING = F9 40\n"

    with pytest.raises(ClassicRetroError) as caught:
        overlay._patch_charmap(original)

    assert caught.value.code is ErrorCode.SOURCE_PATCH_FAILED
