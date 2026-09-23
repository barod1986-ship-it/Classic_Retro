from __future__ import annotations

import hashlib
import re
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen3_arabic import (
    PokemonGen3ArabicEncoder,
    build_arabic_font_atlas,
    build_arabic_glyph_map,
    make_ltr_placeholder_token,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenMovement, TokenStream

PINNED_COMMIT = "c75f352304d529f6ba92d4f74b9cf8b5c3810788"
_PATCH_MARKER = "CLASSIC_RETRO_ARABIC_V1"

_PINNED_BLOBS = {
    "include/characters.h": "d00ecf0a3afcd9fc1fa9534c00f4b74793d5f06f",
    "include/text.h": "7090a029bfc454e19e6425df631fda9db866ae0a",
    "src/text_printer.c": "e425ccb181b52d1f0827785e76c1793c2b2d693d",
    "src/text.c": "f3eef07ce6dea8269980a5ecfdd6902c1c9c13d2",
    "src/string_util.c": "5c26d151a61274caac3a16c3b9c4eb73bf9a9e26",
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
        "oak_intro_messages": len(_oak_speech_streams()),
        "oak_dynamic_ltr_placeholders": True,
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
        "oak_intro_messages": len(_oak_speech_streams()),
        "oak_dynamic_ltr_placeholders": True,
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
        "src/string_util.c",
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
    result["src/string_util.c"] = _patch_string_util(result["src/string_util.c"])
    result["data/text/new_game_intro.inc"] = _patch_oak_intro(
        result["data/text/new_game_intro.inc"]
    )
    return result


def _line(token_id: str) -> InlineToken:
    return InlineToken(
        id=token_id,
        kind=TokenKind.LINE_BREAK,
        movement=TokenMovement.ORDERED,
    )


def _page(token_id: str) -> InlineToken:
    return InlineToken(
        id=token_id,
        kind=TokenKind.CONTROL,
        movement=TokenMovement.ORDERED,
        name="PROMPT_CLEAR",
        args={"raw_hex": "fb"},
    )


def _player(token_id: str) -> InlineToken:
    return make_ltr_placeholder_token(token_id, "PLAYER", 0x01)


def _rival(token_id: str) -> InlineToken:
    return make_ltr_placeholder_token(token_id, "RIVAL", 0x06)


def _oak_speech_streams() -> dict[str, TokenStream]:
    return {
        "gOakSpeech_Text_AskPlayerGender": TokenStream(
            (
                TextToken("والآن أخبرني."),
                _line("gender_line"),
                TextToken("هل أنت ولد أم بنت؟"),
            )
        ),
        "gOakSpeech_Text_WelcomeToTheWorld": TokenStream(
            (
                TextToken("مرحبا بك!"),
                _line("welcome_line_1"),
                TextToken("سعيد بلقائك!"),
                _page("welcome_page_1"),
                TextToken("أهلا بك في عالم بوكيمون!"),
                _page("welcome_page_2"),
                TextToken("اسمي أوك."),
                _page("welcome_page_3"),
                TextToken("يناديني الناس بمحبة"),
                _line("welcome_line_2"),
                TextToken("بروفيسور بوكيمون."),
                _page("welcome_page_4"),
            )
        ),
        "gOakSpeech_Text_ThisWorld": TokenStream((TextToken("هذا العالم..."),)),
        "gOakSpeech_Text_IsInhabitedFarAndWide": TokenStream(
            (
                TextToken("تعيش فيه في كل مكان"),
                _line("world_line"),
                TextToken("مخلوقات تسمى بوكيمون."),
                _page("world_page"),
            )
        ),
        "gOakSpeech_Text_IStudyPokemon": TokenStream(
            (
                TextToken("لبعض الناس، بوكيمون أصدقاء."),
                _line("study_line_1"),
                TextToken("وآخرون يقاتلون بهم."),
                _page("study_page_1"),
                TextToken("أما أنا..."),
                _page("study_page_2"),
                TextToken("فأدرس بوكيمون كمهنة."),
                _page("study_page_3"),
            )
        ),
        "gOakSpeech_Text_TellMeALittleAboutYourself": TokenStream(
            (
                TextToken("لكن أولا، أخبرني قليلا"),
                _line("yourself_line"),
                TextToken("عن نفسك."),
                _page("yourself_page"),
            )
        ),
        "gOakSpeech_Text_YourNameWhatIsIt": TokenStream(
            (
                TextToken("لنبدأ باسمك."),
                _line("name_line"),
                TextToken("ما اسمك؟"),
                _page("name_page"),
            )
        ),
        "gOakSpeech_Text_SoYourNameIsPlayer": TokenStream(
            (
                TextToken("حسنا..."),
                _line("player_name_line"),
                TextToken("إذن اسمك "),
                _player("player_name"),
            )
        ),
        "gOakSpeech_Text_WhatWasHisName": TokenStream(
            (
                TextToken("هذا حفيدي."),
                _page("rival_intro_page_1"),
                TextToken("إنه منافسك منذ كنتما"),
                _line("rival_intro_line"),
                TextToken("صغيرين."),
                _page("rival_intro_page_2"),
                TextToken("همم... ما كان اسمه؟"),
            )
        ),
        "gOakSpeech_Text_YourRivalsNameWhatWasIt": TokenStream(
            (TextToken("ما اسم منافسك؟"),)
        ),
        "gOakSpeech_Text_ConfirmRivalName": TokenStream(
            (
                TextToken("هل كان اسمه"),
                _line("confirm_rival_line"),
                _rival("confirm_rival_name"),
            )
        ),
        "gOakSpeech_Text_RememberRivalsName": TokenStream(
            (
                TextToken("صحيح! تذكرت الآن!"),
                _line("remember_rival_line"),
                TextToken("اسمه "),
                _rival("remember_rival_name"),
                _page("remember_rival_page"),
            )
        ),
        "gOakSpeech_Text_LetsGo": TokenStream(
            (
                _player("lets_go_player"),
                _page("lets_go_page_1"),
                TextToken("حان وقت بدء أسطورتك"),
                _line("lets_go_line_1"),
                TextToken("الخاصة مع بوكيمون!"),
                _page("lets_go_page_2"),
                TextToken("عالم الأحلام والمغامرات"),
                _line("lets_go_line_2"),
                TextToken("ينتظرك. هيا بنا!"),
            )
        ),
    }


def _oak_message_bytes(label: str) -> bytes:
    streams = _oak_speech_streams()
    try:
        stream = streams[label]
    except KeyError as exc:
        raise ValueError(f"Unknown OAK speech label: {label}") from exc
    return PokemonGen3ArabicEncoder().encode_message(
        stream,
        right_x=_OAK_INTRO_RIGHT_X,
        terminator=True,
    )


def _oak_intro_bytes() -> bytes:
    return _oak_message_bytes("gOakSpeech_Text_WelcomeToTheWorld")


def _format_asm_bytes(data: bytes) -> str:
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        values = ", ".join(f"0x{value:02X}" for value in chunk)
        lines.append(f"    .byte {values}")
    return "\n".join(lines)


def _patch_oak_intro(text: str) -> str:
    for label in _oak_speech_streams():
        start = text.find(label + "::\n")
        if start < 0:
            raise ClassicRetroError(
                ErrorCode.SOURCE_PATCH_FAILED,
                f"OAK speech label not found: {label}",
            )
        end = text.find("\n\n", start)
        if end < 0:
            raise ClassicRetroError(
                ErrorCode.SOURCE_PATCH_FAILED,
                f"OAK speech block is not terminated: {label}",
            )

        replacement = (
            label
            + "::\n"
            + "    @ CLASSIC_RETRO_ARABIC_V1 — Arabic OAK speech\n"
            + _format_asm_bytes(_oak_message_bytes(label))
            + "\n"
        )
        text = text[:start] + replacement + text[end + 1 :]

    return text


def _patch_characters(text: str) -> str:
    return _replace_once(
        text,
        "#define EXT_CTRL_CODE_RESUME_MUSIC           0x18\n",
        (
            "#define EXT_CTRL_CODE_RESUME_MUSIC           0x18\n"
            "#define EXT_CTRL_CODE_RTL                    0x19 // CLASSIC_RETRO_ARABIC_V1\n"
            "#define EXT_CTRL_CODE_LTR                    0x1A\n"
            "#define EXT_CTRL_CODE_LTR_PLACEHOLDER        0x1B\n"
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


def _patch_string_util(text: str) -> str:
    helper_anchor = "u8 *StringExpandPlaceholders(u8 *dest, const u8 *src)\n"
    helper = """static u8 *StringCopyReversedMultibyteNoTerminator(u8 *dest, const u8 *src)
{
    const u8 *end = src;

    while (*end != EOS)
    {
        if (*end == CHAR_EXTRA_SYMBOL || *end == CHAR_KEYPAD_ICON)
            end += 2;
        else
            end++;
    }

    while (end > src)
    {
        if (end - src >= 2
         && (*(end - 2) == CHAR_EXTRA_SYMBOL || *(end - 2) == CHAR_KEYPAD_ICON))
        {
            *dest++ = *(end - 2);
            *dest++ = *(end - 1);
            end -= 2;
        }
        else
        {
            *dest++ = *--end;
        }
    }

    return dest;
}

// CLASSIC_RETRO_ARABIC_V1
"""
    text = _replace_once(
        text,
        helper_anchor,
        helper + helper_anchor,
        "LTR placeholder reverse-copy helper",
    )

    old = """        switch (c)
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
"""
    new = """        switch (c)
        {
            case PLACEHOLDER_BEGIN:
                placeholderId = *src++;
                expandedString = GetExpandedPlaceholder(placeholderId);
                dest = StringExpandPlaceholders(dest, expandedString);
                break;
            case EXT_CTRL_CODE_BEGIN:
                c = *src++;
                if (c == EXT_CTRL_CODE_LTR_PLACEHOLDER)
                {
                    placeholderId = *src++;
                    expandedString = GetExpandedPlaceholder(placeholderId);
                    dest = StringCopyReversedMultibyteNoTerminator(dest, expandedString);
                    break;
                }

                *dest++ = EXT_CTRL_CODE_BEGIN;
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
                    case EXT_CTRL_CODE_LTR:
                        break;
                    case EXT_CTRL_CODE_RTL:
                        *dest++ = *src++;
                        break;
                    case 0x04:
                        *dest++ = *src++;
                    case 0x0B:
                        *dest++ = *src++;
                    default:
                        *dest++ = *src++;
                }
                break;
"""
    return _replace_once(
        text,
        old,
        new,
        "StringExpandPlaceholders Arabic controls",
    )


def _patch_charmap(text: str) -> str:
    glyph_map = build_arabic_glyph_map()
    upstream_slots = {
        int(m.group(1), 16) for m in re.finditer(r"=\s*F9\s+([0-9A-Fa-f]{2})\b", text)
    }
    collisions = sorted(set(glyph_map.slots.values()) & upstream_slots)
    if collisions:
        values = ", ".join(f"F9 {value:02X}" for value in collisions)
        raise ClassicRetroError(
            ErrorCode.SOURCE_PATCH_FAILED,
            "Arabic glyph range collides with upstream extra symbols: " + values,
        )

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
            "            case EXT_CTRL_CODE_LTR_PLACEHOLDER:\n"
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
