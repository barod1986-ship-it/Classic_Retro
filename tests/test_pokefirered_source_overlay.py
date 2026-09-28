from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen3_arabic import (
    FontAtlasResult,
    build_arabic_glyph_map,
    command_skeleton,
)
from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.source import pokefirered_arabic as overlay
from classic_retro.text.tokens import TokenStream


@pytest.fixture
def reference_font() -> Path:
    """The pinned reference font, from the environment; never bundled with the tests."""
    path = os.environ.get("CLASSIC_RETRO_REFERENCE_FONT")
    if not path:
        pytest.skip("CLASSIC_RETRO_REFERENCE_FONT is unset")
    return Path(path)


def _oak_blocks(streams: dict[str, TokenStream]) -> str:
    """A stand-in new_game_intro.inc whose Oak speech carries the translations' commands."""
    blocks = [
        f"{label}::\n"
        f'    .string "Invented speech {number}\\n"\n'
        f'    .string "{"".join(command_skeleton(stream))}$"'
        for number, (label, stream) in enumerate(streams.items())
    ]
    return "\n\n".join(blocks) + "\n\n"


def _asm_bytes(asm: str) -> bytes:
    """Every byte of the ``.byte`` lines, in order; a sequence may straddle two lines."""
    return bytes(int(value, 16) for value in re.findall(r"0x([0-9A-F]{2})", asm))


def _retranslated(label: str, text: str) -> TranslationSet:
    """The shipped translations, with ``label``'s Arabic replaced by ``text``."""
    shipped = builtin_translation_set(overlay.TARGET)
    entries = tuple(
        replace(entry, text=text) if entry.id == label else entry for entry in shipped.entries
    )
    return replace(shipped, entries=entries)


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
    streams = overlay._oak_speech_streams()
    original = _oak_blocks(streams)

    patched = overlay._patch_oak_intro(original)

    assert patched.count("CLASSIC_RETRO_ARABIC_V1 — Arabic OAK speech") == len(streams)
    # The standard dialogue window is 26 tiles (208 px), not 28 tiles.
    assert patched.count(".byte 0xFC, 0x19, 0xD0") == len(streams)
    assert ".string" not in patched and patched.endswith("\n\n")
    # The last block may end the file without a blank line after it.
    assert overlay._patch_oak_intro(original.rstrip("\n")).rstrip("\n") == patched.rstrip("\n")


def test_oak_intro_overlay_keeps_the_originals_names_and_page_breaks():
    """A translation may move a line end, never a name or a page break."""
    original = _oak_blocks(overlay._oak_speech_streams())
    label = "gOakSpeech_Text_LetsGo"
    moved_line_end = _retranslated(label, "{PLAYER}\\pحان وقت بدء\nأسطورتك!\\pهيا\nبنا!")
    patched = _asm_bytes(overlay._patch_oak_intro(original, moved_line_end))
    assert patched.count(b"\xfc\x1b\x01") == 2 and patched.count(b"\xfc\x1b\x06") == 2

    refused = {
        "حان وقت بدء أسطورتك!\\pهيا بنا!\\p": "{PLAYER}\\p\\p != \\p\\p",
        "\\p{PLAYER}\\pهيا بنا!": "{PLAYER}\\p\\p != \\p{PLAYER}\\p",
        "{RIVAL}\\pحان وقت بدء أسطورتك!\\pهيا بنا!": "{PLAYER}\\p\\p != {RIVAL}\\p\\p",
        "{PLAYER}\\pحان وقت بدء أسطورتك!\\pهيا بنا!\\p": "{PLAYER}\\p\\p != {PLAYER}\\p\\p\\p",
    }
    for text, notations in refused.items():
        with pytest.raises(ClassicRetroError) as error:
            overlay._patch_oak_intro(original, _retranslated(label, text))
        assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
        assert str(error.value) == f"FireRed {label} commands differ from the original: {notations}"


def test_check_translations_validates_the_notation_without_a_checkout(tmp_path):
    report = overlay.check_pokefirered_translations()
    assert report["messages"] == list(overlay.OAK_SPEECH_LABELS)
    assert report["encoded_bytes"] == sum(
        len(overlay._oak_message_bytes(label)) for label in overlay.OAK_SPEECH_LABELS
    )
    assert report["arabic_glyphs"] == len(build_arabic_glyph_map().characters)
    assert report["oak_intro_right_x"] == 26 * 8
    assert report["lines_measured"] is False and "font_size" not in report

    with pytest.raises(ClassicRetroError) as error:
        overlay.check_pokefirered_translations(
            translations=_retranslated("gOakSpeech_Text_ThisWorld", "هذا {WORLD}...")
        )
    assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    with pytest.raises(ClassicRetroError) as error:
        overlay.check_pokefirered_translations(None, tmp_path / "arabic_normal.png")
    assert str(error.value) == "A preview needs --font"
    with pytest.raises(ClassicRetroError, match="font file not found"):
        overlay.check_pokefirered_translations(tmp_path / "absent.ttf")


def test_check_translations_writes_the_atlas_prepare_would(tmp_path, monkeypatch):
    built = []

    def build_font(font, atlas, widths):
        built.append((atlas, widths))
        atlas.write_bytes(b"atlas")
        widths.write_bytes(b"widths")
        return FontAtlasResult(133, 13, 9, 9)

    monkeypatch.setattr(overlay, "build_arabic_font_atlas", build_font)
    font = tmp_path / "font.ttf"
    font.write_bytes(b"test font")
    preview = tmp_path / "previews" / "arabic_normal.png"
    preview.parent.mkdir()

    report = overlay.check_pokefirered_translations(font, preview)
    assert (report["font_size"], report["font_rows"], report["max_advance"]) == (13, 9, 9)
    assert preview.read_bytes() == b"atlas"
    # The widths file is prepare's, not a preview: it went to a temporary folder.
    assert built[-1] == (preview, built[-1][1]) and not built[-1][1].exists()
    # Without a preview folder the atlas is still built, and left nowhere.
    report = overlay.check_pokefirered_translations(font)
    assert report["font_size"] == 13 and not built[-1][0].exists()


def test_check_translations_builds_the_atlas_with_the_reference_font(tmp_path, reference_font):
    preview = tmp_path / "arabic_normal.png"
    report = overlay.check_pokefirered_translations(reference_font, preview)
    with Image.open(preview) as atlas:
        assert atlas.size == (256, report["font_rows"] * 16)
    assert 1 <= report["max_advance"] <= 16
    assert report["encoded_bytes"] == overlay.check_pokefirered_translations()["encoded_bytes"]


def test_cli_checks_the_script_without_a_checkout(capsys):
    assert main(["targets", "check-translations", "firered"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == list(overlay.OAK_SPEECH_LABELS)
    assert report["lines_measured"] is False


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
        overlay,
        "_patch_all",
        lambda texts, translations=None: {path: overlay._PATCH_MARKER for path in texts},
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


@pytest.fixture
def oak_source_tree(tmp_path, monkeypatch):
    """A checkout of two pinned files: Oak's speech, patched for real, and one merely marked."""
    source = tmp_path / "upstream"
    (source / "src").mkdir(parents=True)
    (source / "data/text").mkdir(parents=True)
    intro = _oak_blocks(overlay._oak_speech_streams()).encode("utf-8")
    (source / "src/text.c").write_bytes(b"pristine\n")
    (source / "data/text/new_game_intro.inc").write_bytes(intro)
    monkeypatch.setattr(
        overlay,
        "_PINNED_BLOBS",
        {
            "src/text.c": overlay._git_blob_sha(b"pristine\n"),
            "data/text/new_game_intro.inc": overlay._git_blob_sha(intro),
        },
    )
    monkeypatch.setattr(
        overlay,
        "_patch_all",
        lambda texts, translations=None: {
            "src/text.c": overlay._PATCH_MARKER + "\n",
            "data/text/new_game_intro.inc": overlay._patch_oak_intro(
                texts["data/text/new_game_intro.inc"], translations
            ),
        },
    )
    return source


def _tree_files(source: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in sorted(source.rglob("*")) if path.is_file()}


def test_prepare_and_source_check_refuse_a_translation_that_drops_a_name(oak_source_tree):
    dropped = _retranslated("gOakSpeech_Text_LetsGo", "حان وقت بدء أسطورتك!\\pهيا بنا!\\p")
    before = _tree_files(oak_source_tree)
    for check in (
        lambda: overlay.prepare_pokefirered_arabic_source(
            oak_source_tree, oak_source_tree / "absent.ttf", dropped
        ),
        lambda: overlay.check_pokefirered_arabic_source(oak_source_tree, dropped),
    ):
        with pytest.raises(ClassicRetroError) as error:
            check()
        assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
        assert "gOakSpeech_Text_LetsGo commands differ from the original: {PLAYER}\\p\\p" in str(
            error.value
        )
    # Refused before the font was even looked for: nothing in the tree changed.
    assert _tree_files(oak_source_tree) == before
    assert not (oak_source_tree / overlay._STATE_FILE).exists()

    # The shipped translations keep every command: the dry run and prepare both pass.
    report = overlay.check_pokefirered_arabic_source(oak_source_tree)
    assert (report["files_verified"], report["oak_intro_messages"]) == (2, 13)


def test_prepare_writes_the_arabic_oak_speech_it_checked(oak_source_tree, monkeypatch):
    def build_font(font, atlas, widths):
        atlas.write_bytes(b"atlas")
        widths.write_bytes(b"widths")
        return FontAtlasResult(133, 13, 9, 9)

    monkeypatch.setattr(overlay, "build_arabic_font_atlas", build_font)
    (oak_source_tree / "font.ttf").write_bytes(b"test font")
    report = overlay.prepare_pokefirered_arabic_source(
        oak_source_tree, oak_source_tree / "font.ttf"
    )
    assert not report["already_patched"] and report["oak_intro_messages"] == 13
    intro = (oak_source_tree / "data/text/new_game_intro.inc").read_text(encoding="utf-8")
    assert intro.count("Arabic OAK speech") == 13 and ".string" not in intro
    # The names' left-to-right placeholders, twice each, and every message's terminator.
    data = _asm_bytes(intro)
    assert data.count(b"\xfc\x1b\x01") == 2 and data.count(b"\xfc\x1b\x06") == 2
    assert data.count(b"\xfc\x1a\xff") == 13


def test_extract_reads_the_oak_speech_of_a_checkout(tmp_path, monkeypatch):
    blocks = [
        f'{label}::\n\t.string "Line {number} of an\\n"\n\t.string "invented speech, {{PLAYER}}!\\p$"\n'
        for number, label in enumerate(overlay.OAK_SPEECH_LABELS)
    ]
    intro = "\n".join(blocks)
    monkeypatch.setattr(
        overlay, "_read_pristine_source", lambda source: {"data/text/new_game_intro.inc": intro}
    )
    originals = overlay.extract_pokefirered_originals(tmp_path)
    assert list(originals) == list(overlay.OAK_SPEECH_LABELS)
    assert originals[overlay.OAK_SPEECH_LABELS[2]] == "Line 2 of an\ninvented speech, {PLAYER}!\\p"
    broken = {"data/text/new_game_intro.inc": intro.replace(".string", ".byte", 1)}
    monkeypatch.setattr(overlay, "_read_pristine_source", lambda source: broken)
    with pytest.raises(ClassicRetroError) as error:
        overlay.extract_pokefirered_originals(tmp_path)
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
