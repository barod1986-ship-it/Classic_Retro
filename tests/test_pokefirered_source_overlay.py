from __future__ import annotations

import ctypes
import os
import shutil
import subprocess

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
    original = "\n\n".join(f'{label}::\n    .string "placeholder$"' for label in labels) + "\n\n"

    patched = overlay._patch_oak_intro(original)

    assert patched.count("CLASSIC_RETRO_ARABIC_V1 — Arabic OAK speech") == len(labels)
    # The standard dialogue window is 26 tiles (208 px), not 28 tiles.
    assert patched.count(".byte 0xFC, 0x19, 0xD0") == len(labels)
    assert '.string "placeholder$"' not in patched


def test_oak_intro_bytes_preserve_newlines_pages_and_eos():
    data = overlay._oak_intro_bytes()

    assert data[:3] == bytes.fromhex("fc19d0")
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


@pytest.fixture
def expander_source():
    return """u8 *StringExpandPlaceholders(u8 *dest, const u8 *src)
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


def test_string_expander_handles_arabic_controls_and_reverses_ltr_placeholder(expander_source):
    patched = overlay._patch_string_util(expander_source)

    assert "StringCopyReversedMultibyteNoTerminator" in patched
    assert "c == EXT_CTRL_CODE_LTR_PLACEHOLDER" in patched
    assert "case EXT_CTRL_CODE_LTR:" in patched
    assert "case EXT_CTRL_CODE_RTL:" in patched


def test_charmap_overlay_rejects_upstream_f9_collision():
    original = "RESUME_MUSIC = FC 18\nEXISTING = F9 40\n"

    with pytest.raises(ClassicRetroError) as caught:
        overlay._patch_charmap(original)

    assert caught.value.code is ErrorCode.SOURCE_PATCH_FAILED


@pytest.fixture
def arrow_source():
    return """void TextPrinterDrawDownArrow(struct TextPrinter *textPrinter)
{
    ClearArrow(textPrinter->printerTemplate.currentX);
    DrawArrow(textPrinter->printerTemplate.currentX);
}
void TextPrinterClearDownArrow(struct TextPrinter *textPrinter)
{
    ClearArrow(textPrinter->printerTemplate.currentX);
}
bool8 TextPrinterWaitAutoMode(struct TextPrinter *textPrinter)
{
    return 0;
}
"""


def test_arrow_draw_and_both_clear_paths_use_same_coordinate(arrow_source):
    patched = overlay._patch_down_arrows(arrow_source)
    assert patched.count("ClearArrow(GetTextPrinterArrowX(textPrinter))") == 2
    assert "DrawArrow(GetTextPrinterArrowX(textPrinter))" in patched


@pytest.fixture
def native_helpers(tmp_path, expander_source, arrow_source):
    compiler = shutil.which("cc")
    if os.name != "posix" or compiler is None:
        pytest.skip("Native renderer regression checks require a POSIX C compiler")
    helper = overlay._patch_string_util(expander_source).split("// CLASSIC_RETRO_ARABIC_V1")[0]
    origins = overlay._patch_line_origins("""
int reset_origin(int state, int rtl) {
    struct TextPrinter printer = {{8, 0}, rtl, 224};
    struct TextPrinter *textPrinter = &printer;
    switch (state) {
    case 0: /* newline */
        textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.x;
        break;
    case 1: /* clear */
        textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.x;
        break;
    case 2: /* scroll */
        textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.x;
        break;
    }
    return textPrinter->printerTemplate.currentX;
}
""")
    arrow_helper = overlay._patch_down_arrows(arrow_source).split("void TextPrinterDrawDownArrow")[
        0
    ]
    source = tmp_path / "regression.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "#define EOS 0xFF\n#define CHAR_EXTRA_SYMBOL 0xF9\n#define CHAR_KEYPAD_ICON 0xF8\n"
        "struct TextPrinter { struct { int x, currentX; } printerTemplate; int rtl, rtlX; };\n"
        + helper
        + origins
        + arrow_helper
        + "int arrow_x(int x, int rtl) {\n"
        "    struct TextPrinter printer = {{0, x}, rtl, 208};\n"
        "    return GetTextPrinterArrowX(&printer);\n}\n"
        + "int reverse(u8 *dest, const u8 *src) {\n"
        "    return StringCopyReversedMultibyteNoTerminator(dest, src) - dest;\n}\n",
        encoding="utf-8",
    )
    library = tmp_path / "regression.so"
    subprocess.run([compiler, "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
    return ctypes.CDLL(str(library))


@pytest.mark.parametrize("state", [0, 1, 2], ids=["newline", "clear", "scroll"])
@pytest.mark.parametrize("rtl,expected", [(0, 8), (1, 224)])
def test_runtime_line_origin(native_helpers, state, rtl, expected):
    assert native_helpers.reset_origin(state, rtl) == expected


@pytest.mark.parametrize(
    "x,rtl,expected", [(0, 0, 0), (200, 0, 200), (0, 1, 0), (5, 1, 0), (10, 1, 0), (200, 1, 190)]
)
def test_runtime_arrow_position_avoids_text_and_underflow(native_helpers, x, rtl, expected):
    assert native_helpers.arrow_x(x, rtl) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("ccbfbeff", "bebfcc"),  # RED -> DER in right-to-left paint order
        ("f9f9bbff", "bbf9f9"),  # A symbol argument is not another prefix
        ("f9f8f8f9bbff", "bbf8f9f9f8"),
        ("f9ffff", "f9ff"),  # FF inside an extra symbol is not EOS
        ("ff", ""),
    ],
)
def test_runtime_placeholder_reversal_preserves_glyph_units(native_helpers, source, expected):
    output = ctypes.create_string_buffer(32)
    size = native_helpers.reverse(output, bytes.fromhex(source))
    assert output.raw[:size] == bytes.fromhex(expected)


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    source = tmp_path / "upstream"
    (source / "src").mkdir(parents=True)
    (source / "src/text.c").write_bytes(b"pristine\n")
    monkeypatch.setattr(
        overlay, "_PINNED_BLOBS", {"src/text.c": overlay._git_blob_sha(b"pristine\n")}
    )
    monkeypatch.setattr(
        overlay, "_patch_all", lambda texts: {path: overlay._PATCH_MARKER for path in texts}
    )
    return source


def test_failed_font_build_does_not_modify_pristine_source(source_tree):
    before = (source_tree / "src/text.c").read_bytes()
    with pytest.raises(ClassicRetroError, match="font file not found"):
        overlay.prepare_pokefirered_arabic_source(source_tree, source_tree / "absent.ttf")
    assert (source_tree / "src/text.c").read_bytes() == before
    assert not (source_tree / overlay._STATE_FILE).exists()
    assert not (source_tree / "graphics").exists()


def test_prepared_source_must_match_recorded_overlay(source_tree, monkeypatch):
    from classic_retro.engines.pokemon_gen3_arabic import FontAtlasResult

    def build_font(font, atlas, widths):
        atlas.write_bytes(b"atlas")
        widths.write_bytes(b"widths")
        return FontAtlasResult(133, 13, 9, 9)

    monkeypatch.setattr(overlay, "build_arabic_font_atlas", build_font)
    (source_tree / "font.ttf").write_bytes(b"test font")
    first = overlay.prepare_pokefirered_arabic_source(source_tree, source_tree / "font.ttf")
    second = overlay.prepare_pokefirered_arabic_source(source_tree, source_tree / "font.ttf")
    assert not first["already_patched"]
    assert second["already_patched"]
    (source_tree / "src/text.c").write_text(overlay._PATCH_MARKER + " changed", encoding="utf-8")
    with pytest.raises(ClassicRetroError, match="Modified or partially patched"):
        overlay.prepare_pokefirered_arabic_source(source_tree, source_tree / "font.ttf")


def test_legacy_overlay_is_not_silently_reused(source_tree):
    (source_tree / "src/text.c").write_text(overlay._PATCH_MARKER, encoding="utf-8")
    with pytest.raises(ClassicRetroError, match="fresh checkout"):
        overlay.prepare_pokefirered_arabic_source(source_tree, source_tree / "font.ttf")
