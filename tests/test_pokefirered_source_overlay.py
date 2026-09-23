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


def test_oak_intro_overlay_replaces_all_oak_speech_blocks():
    labels = tuple(overlay._oak_speech_streams())
    original = "\n\n".join(
        f'{label}::\n    .string "placeholder$"' for label in labels
    ) + "\n\n"

    patched = overlay._patch_oak_intro(original)

    assert patched.count("CLASSIC_RETRO_ARABIC_V1 — Arabic OAK speech") == len(labels)
    assert patched.count(".byte 0xFC, 0x19, 0xD8") == len(labels)
    assert '.string "placeholder$"' not in patched


def test_oak_intro_bytes_preserve_newlines_pages_and_eos():
    data = overlay._oak_intro_bytes()

    assert data[:3] == bytes.fromhex("fc19d8")
    assert data.count(0xFE) == 2
    assert data.count(0xFB) == 4
    assert data[-3:] == bytes.fromhex("fc1aff")


def test_oak_dynamic_names_use_ltr_placeholder_control():
    messages = {
        label: overlay._oak_message_bytes(label)
        for label in (
            "gOakSpeech_Text_SoYourNameIsPlayer",
            "gOakSpeech_Text_ConfirmRivalName",
            "gOakSpeech_Text_RememberRivalsName",
            "gOakSpeech_Text_LetsGo",
        )
    }

    assert bytes.fromhex("fc1b01") in messages["gOakSpeech_Text_SoYourNameIsPlayer"]
    assert bytes.fromhex("fc1b01") in messages["gOakSpeech_Text_LetsGo"]
    assert bytes.fromhex("fc1b06") in messages["gOakSpeech_Text_ConfirmRivalName"]
    assert bytes.fromhex("fc1b06") in messages["gOakSpeech_Text_RememberRivalsName"]
    assert all(b"\xfd\x01" not in data and b"\xfd\x06" not in data for data in messages.values())


def test_string_expander_handles_arabic_controls_and_reverses_ltr_placeholder():
    original = """u8 *StringExpandPlaceholders(u8 *dest, const u8 *src)
{
    for (;;)
    {
        u8 c = *src++;
        u8 placeholderId;
        u8 *expandedString;

        switch (c)
        {
            case PLACEHOLDER_BEGIN:
                placeholderId = *src++;
                expandedString = GetExpandedPlaceholder(placeholderId);
                dest = StringExpandPlaceholders(dest, expandedString);
                break;
            case EXT_CTRL_CODE_BEGIN:
                *dest++ = c;
                c = *src++;
                *dest++ = c;

                switch (c)
                {
                    case 0x07:
                    case 0x09:
                    case 0x0F:
                    case 0x15:
                    case 0x16:
                    case 0x17:
                    case 0x18:
                        break;
                    case 0x04:
                        *dest++ = *src++;
                    case 0x0B:
                        *dest++ = *src++;
                    default:
                        *dest++ = *src++;
                }
                break;
            case EOS:
                *dest = EOS;
                return dest;
            case 0xFA:
            case 0xFB:
            case 0xFE:
            default:
                *dest++ = c;
        }
    }
}
"""
    patched = overlay._patch_string_util(original)

    assert "StringCopyReversedMultibyteNoTerminator" in patched
    assert "c == EXT_CTRL_CODE_LTR_PLACEHOLDER" in patched
    assert "case EXT_CTRL_CODE_LTR:" in patched
    assert "case EXT_CTRL_CODE_RTL:" in patched


def test_charmap_overlay_rejects_upstream_f9_collision():
    original = "RESUME_MUSIC = FC 18\nEXISTING = F9 40\n"

    with pytest.raises(ClassicRetroError) as caught:
        overlay._patch_charmap(original)

    assert caught.value.code is ErrorCode.SOURCE_PATCH_FAILED
