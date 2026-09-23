from __future__ import annotations

import hashlib
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen3_arabic import (
    PokemonGen3ArabicEncoder,
    build_arabic_font_atlas,
    build_arabic_glyph_map,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenMovement, TokenStream

PINNED_COMMIT = "c75f352304d529f6ba92d4f74b9cf8b5c3810788"
_PATCH_MARKER = "CLASSIC_RETRO_ARABIC_V1"

_PINNED_BLOBS = {
    "include/characters.h": "d00ecf0a3afcd9fc1fa9534c00f4b74793d5f06f",
    "include/text.h": "7090a029bfc454e19e6425df631fda9db866ae0a",
    "src/text_printer.c": "e425ccb181b52d1f0827785e76c1793c2b2d693d",
    "src/text.c": "f3eef07ce6dea8269980a5ecfdd6902c1c9c13d2",
    "charmap.txt": "b9d0ed9de00d05fc303bb987a5aa634b19009b47",
    "graphics_file_rules.mk": "39b952cd45b6a34eb98318a76aa531fcafff134d",
    "data/text/new_game_intro.inc": "e667b68d92f7b44f424d5d276093c434f1b7e2df",
}

_OAK_INTRO_RIGHT_X = 216


def check_pokefirered_arabic_source(source: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    texts = _read_pristine_source(source)
    patched = _patch_all(texts)
    if not all(_PATCH_MARKER in value for value in patched.values()):
        raise ClassicRetroError(
            ErrorCode.SOURCE_PATCH_FAILED,
            "Arabic source overlay marker missing after dry-run patch",
        )

    glyph_map = build_arabic_glyph_map()
    return {
        "upstream_commit": PINNED_COMMIT,
        "files_verified": len(texts),
        "overlay_dry_run": True,
        "arabic_glyphs": len(glyph_map.characters),
        "first_extra_symbol": f"0x{glyph_map.first_slot:02X}",
        "last_extra_symbol": f"0x{glyph_map.last_slot:02X}",
        "oak_intro_arabic": True,
        "oak_intro_bytes": len(_oak_intro_bytes()),
    }


def prepare_pokefirered_arabic_source(source: Path, font_path: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    text_c = source / "src/text.c"
    already_patched = text_c.is_file() and _PATCH_MARKER in text_c.read_text(encoding="utf-8")

    if already_patched:
        _validate_patched_tree(source)
    else:
        texts = _read_pristine_source(source)
        patched = _patch_all(texts)
        for relative, content in patched.items():
            path = source / relative
            path.write_text(content, encoding="utf-8", newline="\n")

    atlas = source / "graphics/fonts/arabic_normal.png"
    widths = source / "graphics/fonts/arabic_normal_widths.bin"
    font_result = build_arabic_font_atlas(font_path, atlas, widths)

    glyph_map = build_arabic_glyph_map()
    return {
        "upstream_commit": PINNED_COMMIT,
        "source": str(source),
        "already_patched": already_patched,
        "arabic_glyphs": len(glyph_map.characters),
        "font_size": font_result.font_size,
        "font_rows": font_result.rows,
        "max_advance": font_result.max_advance,
        "font_png": str(atlas),
        "widths": str(widths),
        "build_target": "firered_rev1",
        "oak_intro_arabic": True,
        "oak_intro_right_x": _OAK_INTRO_RIGHT_X,
    }


def _read_pristine_source(source: Path) -> dict[str, str]:
    if not source.is_dir():
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"pokefirered source directory not found: {source}",
        )

    texts: dict[str, str] = {}
    mismatches: list[str] = []

    for relative, expected_blob in _PINNED_BLOBS.items():
        path = source / relative
        if not path.is_file():
            mismatches.append(relative + ":missing")
            continue

        raw = path.read_bytes()
        actual_blob = _git_blob_sha(raw)
        if actual_blob != expected_blob:
            mismatches.append(relative + ":" + actual_blob)
            continue

        texts[relative] = raw.decode("utf-8")

    if mismatches:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            (
                "pokefirered source does not match pinned commit "
                + PINNED_COMMIT
                + ": "
                + ", ".join(mismatches)
            ),
        )

    return texts


def _validate_patched_tree(source: Path) -> None:
    required = (
        "include/characters.h",
        "include/text.h",
        "src/text_printer.c",
        "src/text.c",
        "charmap.txt",
        "graphics_file_rules.mk",
        "data/text/new_game_intro.inc",
    )
    missing = [
        relative
        for relative in required
        if not (source / relative).is_file()
        or _PATCH_MARKER not in (source / relative).read_text(encoding="utf-8")
    ]
    if missing:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "Partially patched pokefirered source: " + ", ".join(missing),
        )


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _patch_all(texts: dict[str, str]) -> dict[str, str]:
    glyph_map = build_arabic_glyph_map()
    count = len(glyph_map.characters)

    result = dict(texts)
    result["include/characters.h"] = _patch_characters(result["include/characters.h"])
    result["include/text.h"] = _patch_text_h(result["include/text.h"])
    result["src/text_printer.c"] = _patch_text_printer(result["src/text_printer.c"])
    result["charmap.txt"] = _patch_charmap(result["charmap.txt"])
    result["graphics_file_rules.mk"] = _patch_graphics_rules(result["graphics_file_rules.mk"])
    result["src/text.c"] = _patch_text_c(result["src/text.c"], count)
    result["data/text/new_game_intro.inc"] = _patch_oak_intro(
        result["data/text/new_game_intro.inc"]
    )
    return result


def _oak_intro_bytes() -> bytes:
    encoder = PokemonGen3ArabicEncoder()
    stream = TokenStream(
        (
            TextToken("مرحبا بك!"),
            InlineToken(
                id="oak_intro_line_1",
                kind=TokenKind.LINE_BREAK,
                movement=TokenMovement.ORDERED,
            ),
            TextToken("سعيد بلقائك!"),
            InlineToken(
                id="oak_intro_page_1",
                kind=TokenKind.CONTROL,
                movement=TokenMovement.ORDERED,
                name="PROMPT_CLEAR",
                args={"raw_hex": "fb"},
            ),
            TextToken("أهلا بك في عالم بوكيمون!"),
            InlineToken(
                id="oak_intro_page_2",
                kind=TokenKind.CONTROL,
                movement=TokenMovement.ORDERED,
                name="PROMPT_CLEAR",
                args={"raw_hex": "fb"},
            ),
            TextToken("اسمي أوك."),
            InlineToken(
                id="oak_intro_page_3",
                kind=TokenKind.CONTROL,
                movement=TokenMovement.ORDERED,
                name="PROMPT_CLEAR",
                args={"raw_hex": "fb"},
            ),
            TextToken("يناديني الناس بمحبة"),
            InlineToken(
                id="oak_intro_line_2",
                kind=TokenKind.LINE_BREAK,
                movement=TokenMovement.ORDERED,
            ),
            TextToken("بروفيسور بوكيمون."),
            InlineToken(
                id="oak_intro_page_4",
                kind=TokenKind.CONTROL,
                movement=TokenMovement.ORDERED,
                name="PROMPT_CLEAR",
                args={"raw_hex": "fb"},
            ),
        )
    )
    return encoder.encode_message(stream, right_x=_OAK_INTRO_RIGHT_X, terminator=True)


def _format_asm_bytes(data: bytes) -> str:
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        values = ", ".join(f"0x{value:02X}" for value in chunk)
        lines.append(f"    .byte {values}")
    return "\n".join(lines)


def _patch_oak_intro(text: str) -> str:
    original = """gOakSpeech_Text_WelcomeToTheWorld::
    .string "Hello, there!\\n"
    .string "Glad to meet you!\\p"
    .string "Welcome to the world of POKéMON!\\p"
    .string "My name is OAK.\\p"
    .string "People affectionately refer to me\\n"
    .string "as the POKéMON PROFESSOR.\\p$"
"""
    replacement = (
        "gOakSpeech_Text_WelcomeToTheWorld::\n"
        "    @ CLASSIC_RETRO_ARABIC_V1 — first OAK speech\n"
        + _format_asm_bytes(_oak_intro_bytes())
        + "\n"
    )
    return _replace_once(text, original, replacement, "OAK intro Arabic speech")


def _patch_characters(text: str) -> str:
    return _replace_once(
        text,
        "#define EXT_CTRL_CODE_RESUME_MUSIC           0x18\n",
        (
            "#define EXT_CTRL_CODE_RESUME_MUSIC           0x18\n"
            "#define EXT_CTRL_CODE_RTL                    0x19 // CLASSIC_RETRO_ARABIC_V1\n"
            "#define EXT_CTRL_CODE_LTR                    0x1A\n"
        ),
        "characters controls",
    )


def _patch_text_h(text: str) -> str:
    return _replace_once(
        text,
        "    u8 japanese;\n};\n",
        ("    u8 japanese;\n    bool8 rtl; // CLASSIC_RETRO_ARABIC_V1\n    u8 rtlX;\n};\n"),
        "TextPrinter RTL state",
    )


def _patch_text_printer(text: str) -> str:
    return _replace_once(
        text,
        "    sTempTextPrinter.japanese = 0;\n",
        (
            "    sTempTextPrinter.japanese = 0;\n"
            "    sTempTextPrinter.rtl = FALSE; // CLASSIC_RETRO_ARABIC_V1\n"
            "    sTempTextPrinter.rtlX = textSubPrinter->x;\n"
        ),
        "TextPrinter initialization",
    )


def _patch_charmap(text: str) -> str:
    glyph_map = build_arabic_glyph_map()
    text = _replace_once(
        text,
        "RESUME_MUSIC = FC 18\n",
        (
            "RESUME_MUSIC = FC 18\n"
            "RTL = FC 19 @ CLASSIC_RETRO_ARABIC_V1; followed by right-edge x offset\n"
            "LTR = FC 1A\n"
        ),
        "charmap RTL controls",
    )
    return (
        text
        + "\n@ CLASSIC_RETRO_ARABIC_V1 presentation-form glyphs\n"
        + "\n".join(glyph_map.charmap_lines())
        + "\n"
    )


def _patch_graphics_rules(text: str) -> str:
    anchor = (
        "$(FONTGFXDIR)/latin_normal.fwlatfont: $(FONTGFXDIR)/latin_normal.png\n\t$(GFX) $< $@\n"
    )
    replacement = (
        anchor
        + "\n# CLASSIC_RETRO_ARABIC_V1\n"
        + "$(FONTGFXDIR)/arabic_normal.fwlatfont: $(FONTGFXDIR)/arabic_normal.png\n"
        + "\t$(GFX) $< $@\n"
    )
    return _replace_once(text, anchor, replacement, "Arabic font graphics rule")


def _patch_text_c(text: str, glyph_count: int) -> str:
    prototype_anchor = "static s32 GetGlyphWidth_Female(u16 glyphId, bool32 isJapanese);\n"
    text = _replace_once(
        text,
        prototype_anchor,
        (
            prototype_anchor
            + "static bool32 IsArabicGlyph(u16 glyphId); // CLASSIC_RETRO_ARABIC_V1\n"
            + "static void DecompressGlyph_Arabic(u16 glyphId);\n"
            + "static s32 GetGlyphWidth_Arabic(u16 glyphId);\n"
        ),
        "Arabic font prototypes",
    )

    glyph_anchor = (
        "static const u16 sFontNormalLatinGlyphs[] = "
        'INCBIN_U16("graphics/fonts/latin_normal.fwlatfont");\n'
    )
    text = _replace_once(
        text,
        glyph_anchor,
        (
            glyph_anchor
            + "#define ARABIC_GLYPH_FIRST (0x100 | 0x40) // CLASSIC_RETRO_ARABIC_V1\n"
            + f"#define ARABIC_GLYPH_COUNT {glyph_count}\n"
            + "static const u16 sFontArabicGlyphs[] = "
            + 'INCBIN_U16("graphics/fonts/arabic_normal.fwlatfont");\n'
            + "static const u8 sFontArabicGlyphWidths[] = "
            + 'INCBIN_U8("graphics/fonts/arabic_normal_widths.bin");\n'
        ),
        "Arabic font data",
    )

    normal_anchor = "void DecompressGlyph_Normal(u16 glyphId, bool32 isJapanese)\n"
    arabic_functions = """static bool32 IsArabicGlyph(u16 glyphId)
{
    return glyphId >= ARABIC_GLYPH_FIRST
        && glyphId < ARABIC_GLYPH_FIRST + ARABIC_GLYPH_COUNT;
}

static void DecompressGlyph_Arabic(u16 glyphId)
{
    u16 index = glyphId - ARABIC_GLYPH_FIRST;
    const u16 *glyphs = sFontArabicGlyphs + (0x20 * index);

    DecompressGlyphTile(glyphs, (u16 *)gGlyphInfo.pixels);
    DecompressGlyphTile(glyphs + 0x8, (u16 *)(gGlyphInfo.pixels + 0x20));
    DecompressGlyphTile(glyphs + 0x10, (u16 *)(gGlyphInfo.pixels + 0x40));
    DecompressGlyphTile(glyphs + 0x18, (u16 *)(gGlyphInfo.pixels + 0x60));
    gGlyphInfo.width = sFontArabicGlyphWidths[index];
    gGlyphInfo.height = 14;
}

static s32 GetGlyphWidth_Arabic(u16 glyphId)
{
    return sFontArabicGlyphWidths[glyphId - ARABIC_GLYPH_FIRST];
}

// CLASSIC_RETRO_ARABIC_V1
"""
    text = _replace_once(
        text,
        normal_anchor,
        arabic_functions + normal_anchor,
        "Arabic glyph functions",
    )

    text = _replace_once(
        text,
        (
            "        case CHAR_NEWLINE:\n"
            "            textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.x;\n"
        ),
        (
            "        case CHAR_NEWLINE:\n"
            "            textPrinter->printerTemplate.currentX = textPrinter->rtl\n"
            "                ? textPrinter->rtlX\n"
            "                : textPrinter->printerTemplate.x;\n"
        ),
        "RTL newline origin",
    )

    text = _replace_once(
        text,
        (
            "            case EXT_CTRL_CODE_RESUME_MUSIC:\n"
            "                m4aMPlayContinue(&gMPlayInfo_BGM);\n"
            "                return RENDER_REPEAT;\n"
        ),
        (
            "            case EXT_CTRL_CODE_RESUME_MUSIC:\n"
            "                m4aMPlayContinue(&gMPlayInfo_BGM);\n"
            "                return RENDER_REPEAT;\n"
            "            case EXT_CTRL_CODE_RTL: // CLASSIC_RETRO_ARABIC_V1\n"
            "                textPrinter->rtl = TRUE;\n"
            "                textPrinter->rtlX = textPrinter->printerTemplate.x\n"
            "                    + *textPrinter->printerTemplate.currentChar++;\n"
            "                textPrinter->printerTemplate.currentX = textPrinter->rtlX;\n"
            "                return RENDER_REPEAT;\n"
            "            case EXT_CTRL_CODE_LTR:\n"
            "                textPrinter->rtl = FALSE;\n"
            "                textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.x;\n"
            "                return RENDER_REPEAT;\n"
        ),
        "RTL render controls",
    )

    text = _replace_once(
        text,
        (
            "        case CHAR_KEYPAD_ICON:\n"
            "            currChar = *textPrinter->printerTemplate.currentChar++;\n"
            "            gGlyphInfo.width = DrawKeypadIcon(textPrinter->printerTemplate.windowId, currChar, textPrinter->printerTemplate.currentX, textPrinter->printerTemplate.currentY);\n"
            "            textPrinter->printerTemplate.currentX += gGlyphInfo.width + textPrinter->printerTemplate.letterSpacing;\n"
            "            return RENDER_PRINT;\n"
        ),
        (
            "        case CHAR_KEYPAD_ICON:\n"
            "            currChar = *textPrinter->printerTemplate.currentChar++;\n"
            "            if (textPrinter->rtl)\n"
            "            {\n"
            "                width = GetKeypadIconWidth(currChar) + textPrinter->printerTemplate.letterSpacing;\n"
            "                textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.currentX >= width\n"
            "                    ? textPrinter->printerTemplate.currentX - width\n"
            "                    : 0;\n"
            "                DrawKeypadIcon(textPrinter->printerTemplate.windowId, currChar, textPrinter->printerTemplate.currentX, textPrinter->printerTemplate.currentY);\n"
            "            }\n"
            "            else\n"
            "            {\n"
            "                gGlyphInfo.width = DrawKeypadIcon(textPrinter->printerTemplate.windowId, currChar, textPrinter->printerTemplate.currentX, textPrinter->printerTemplate.currentY);\n"
            "                textPrinter->printerTemplate.currentX += gGlyphInfo.width + textPrinter->printerTemplate.letterSpacing;\n"
            "            }\n"
            "            return RENDER_PRINT;\n"
        ),
        "RTL keypad icon",
    )

    old_render = """        switch (subStruct->glyphId)
        {
        case FONT_SMALL:
            DecompressGlyph_Small(currChar, textPrinter->japanese);
            break;
        case FONT_NORMAL_COPY_1:
            DecompressGlyph_NormalCopy1(currChar, textPrinter->japanese);
            break;
        case FONT_NORMAL:
            DecompressGlyph_Normal(currChar, textPrinter->japanese);
            break;
        case FONT_NORMAL_COPY_2:
            DecompressGlyph_NormalCopy2(currChar, textPrinter->japanese);
            break;
        case FONT_MALE:
            DecompressGlyph_Male(currChar, textPrinter->japanese);
            break;
        case FONT_FEMALE:
            DecompressGlyph_Female(currChar, textPrinter->japanese);
            break;
        }

        CopyGlyphToWindow(textPrinter);

        if (textPrinter->minLetterSpacing)
        {
            textPrinter->printerTemplate.currentX += gGlyphInfo.width;
            width = textPrinter->minLetterSpacing - gGlyphInfo.width;
            if (width > 0)
            {
                ClearTextSpan(textPrinter, width);
                textPrinter->printerTemplate.currentX += width;
            }
        }
        else
        {
            if (textPrinter->japanese)
                textPrinter->printerTemplate.currentX += (gGlyphInfo.width + textPrinter->printerTemplate.letterSpacing);
            else
                textPrinter->printerTemplate.currentX += gGlyphInfo.width;
        }
"""
    new_render = """        if (IsArabicGlyph(currChar))
        {
            DecompressGlyph_Arabic(currChar);
        }
        else
        {
            switch (subStruct->glyphId)
            {
            case FONT_SMALL:
                DecompressGlyph_Small(currChar, textPrinter->japanese);
                break;
            case FONT_NORMAL_COPY_1:
                DecompressGlyph_NormalCopy1(currChar, textPrinter->japanese);
                break;
            case FONT_NORMAL:
                DecompressGlyph_Normal(currChar, textPrinter->japanese);
                break;
            case FONT_NORMAL_COPY_2:
                DecompressGlyph_NormalCopy2(currChar, textPrinter->japanese);
                break;
            case FONT_MALE:
                DecompressGlyph_Male(currChar, textPrinter->japanese);
                break;
            case FONT_FEMALE:
                DecompressGlyph_Female(currChar, textPrinter->japanese);
                break;
            }
        }

        if (textPrinter->rtl)
        {
            width = gGlyphInfo.width;
            if (textPrinter->minLetterSpacing > width)
                width = textPrinter->minLetterSpacing;
            else if (textPrinter->japanese)
                width += textPrinter->printerTemplate.letterSpacing;

            textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.currentX >= width
                ? textPrinter->printerTemplate.currentX - width
                : 0;
            CopyGlyphToWindow(textPrinter);
        }
        else
        {
            CopyGlyphToWindow(textPrinter);

            if (textPrinter->minLetterSpacing)
            {
                textPrinter->printerTemplate.currentX += gGlyphInfo.width;
                width = textPrinter->minLetterSpacing - gGlyphInfo.width;
                if (width > 0)
                {
                    ClearTextSpan(textPrinter, width);
                    textPrinter->printerTemplate.currentX += width;
                }
            }
            else
            {
                if (textPrinter->japanese)
                    textPrinter->printerTemplate.currentX += (gGlyphInfo.width + textPrinter->printerTemplate.letterSpacing);
                else
                    textPrinter->printerTemplate.currentX += gGlyphInfo.width;
            }
        }
"""
    text = _replace_once(text, old_render, new_render, "RTL glyph drawing")

    clear_scroll_anchor = (
        "            textPrinter->printerTemplate.currentX = textPrinter->printerTemplate.x;\n"
    )
    if text.count(clear_scroll_anchor) < 2:
        raise ClassicRetroError(
            ErrorCode.SOURCE_PATCH_FAILED,
            "Expected clear/scroll currentX anchors after newline patch",
        )
    text = text.replace(
        clear_scroll_anchor,
        (
            "            textPrinter->printerTemplate.currentX = textPrinter->rtl\n"
            "                ? textPrinter->rtlX\n"
            "                : textPrinter->printerTemplate.x;\n"
        ),
        2,
    )

    text = _replace_once(
        text,
        (
            "            case EXT_CTRL_CODE_SHIFT_RIGHT:\n"
            "            case EXT_CTRL_CODE_SHIFT_DOWN:\n"
            "                ++str;\n"
        ),
        (
            "            case EXT_CTRL_CODE_SHIFT_RIGHT:\n"
            "            case EXT_CTRL_CODE_SHIFT_DOWN:\n"
            "            case EXT_CTRL_CODE_RTL:\n"
            "                ++str;\n"
        ),
        "GetStringWidth RTL argument",
    )
    text = _replace_once(
        text,
        "            case EXT_CTRL_CODE_FILL_WINDOW:\n                break;\n",
        (
            "            case EXT_CTRL_CODE_FILL_WINDOW:\n"
            "            case EXT_CTRL_CODE_LTR:\n"
            "                break;\n"
        ),
        "GetStringWidth LTR control",
    )
    text = _replace_once(
        text,
        "                glyphWidth = func(*++str | 0x100, isJapanese);\n",
        (
            "            {\n"
            "                u16 glyphId = *++str | 0x100;\n"
            "                glyphWidth = IsArabicGlyph(glyphId)\n"
            "                    ? GetGlyphWidth_Arabic(glyphId)\n"
            "                    : func(glyphId, isJapanese);\n"
            "            }\n"
        ),
        "Arabic extra-symbol width",
    )

    return text


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_PATCH_FAILED,
            f"{label} anchor expected once, found {count}",
        )
    return text.replace(old, new, 1)
