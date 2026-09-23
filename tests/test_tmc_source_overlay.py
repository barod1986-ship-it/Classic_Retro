from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tmc import control_signature, parse_tmc_string
from classic_retro.engines.tmc_arabic import TmcArabicFontResult, build_tmc_arabic_glyph_map
from classic_retro.source import tmc_arabic as overlay


def _english_tables() -> list[list[str]]:
    """Stand-in USA.json whose strings carry the same engine commands as the originals."""
    english = [[""] * 0x40 for _ in range(0x26)]
    for message in overlay.tmc_arabic_messages():
        english[message.table][message.index] = "".join(control_signature(message.stream))
    return english


def test_messages_are_unique_and_sized_for_their_boxes():
    messages = overlay.tmc_arabic_messages()
    labels = [message.label for message in messages]

    assert len(labels) == len(set(labels))
    assert {message.line_width for message in messages} == {0xD0, 0xF0, 0x78}


def test_translate_rejects_a_dropped_engine_command():
    english = _english_tables()
    english[0x10][0x04] = "Well, {Player} was up late.\n{07:10:05}{Sound:00:01}"

    with pytest.raises(ClassicRetroError) as caught:
        overlay._translate(json.dumps(english), overlay._encoder(Path("."), None), False)
    assert caught.value.code is ErrorCode.TOKEN_SET_MISMATCH
    assert "1004" in str(caught.value)


def test_translation_is_written_in_tmc_strings_notation():
    translated = json.loads(
        overlay._translate(json.dumps(_english_tables()), overlay._encoder(Path("."), None), False)
    )
    first = translated[0x10][0x01]
    assert first.startswith("{04:16}{Sound:00:95}")
    assert first.endswith("{04:17}")
    assert "{04:18:" in first
    # Every translated string still parses as game text.
    for message in overlay.tmc_arabic_messages():
        parse_tmc_string(translated[message.table][message.index])


def test_header_overlay_keeps_window_struct_size():
    original = (
        "typedef struct {\n    u8 unk00 : 1;\n    u8 unk01 : 3;\n    u8 unk04 : 4;\n    u8 unk1;\n"
        "} WStruct;\n\nstatic_assert(sizeof(WStruct) == 12);\n"
    )
    patched = overlay._patch_message_h(original)

    assert "u8 rtl : 1;" in patched
    assert "u8 rtlVariables : 1;" in patched
    assert "u8 unk03 : 1;" in patched
    assert "static_assert(sizeof(WStruct) == 12);" in patched
    assert "#define ARABIC_FONT_PAGE 9" in patched


def test_font_page_and_linker_overlays_append_without_moving_existing_data():
    table = "\t.4byte gUnk_086A2A60\n\t.4byte gUnk_086A2EE0\n\ngUnk_0810926C:: @ 0810926C\n"
    patched_table = overlay._patch_text_s(table)
    assert patched_table.index("gClassicRetroArabicFont") < patched_table.index("gUnk_0810926C")

    linker = (
        "#endif\n        . = 0x00040000;\n    } >ewram\n"
        "        src/eeprom.o(.rodata);\n    } >rom\n"
    )
    patched_linker = overlay._patch_linker(linker)
    assert "gClassicRetroArabicRtl = .;" in patched_linker
    assert patched_linker.index("src/eeprom.o") < patched_linker.index("classic_retro_arabic.o")


def test_patch_anchor_must_appear_exactly_once():
    with pytest.raises(ClassicRetroError) as caught:
        overlay._patch_text_s("no anchors here\n")
    assert caught.value.code is ErrorCode.SOURCE_PATCH_FAILED


# --------------------------------------------------------------------------- native checks

_HARNESS_PRELUDE = """
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef u32 bool32;
#define TRUE 1
#define FALSE 0
#define ARABIC_DIALOG_LINE_WIDTH 0xd0
typedef struct {
    u8 unk00 : 1;
    u8 rtl : 1;
    u8 rtlVariables : 1;
    u8 unk03 : 1;
    u8 unk04 : 4;
    u8 unk1;
    u8 charColor;
    u8 bgColor;
    u16 unk4;
    u16 unk6;
    void* unk8;
} WStruct;
typedef union { char s[8]; u32 w[2]; } String8;
typedef struct {
    WStruct _50;
    char player_name[10];
    u8 _66[2];
    String8 _68;
    String8 _70;
    String8 _78;
    String8 _80;
} TextRender;
typedef struct { u16 left; u16 right; } ArabicRtlExtent;
TextRender gTextRender;
ArabicRtlExtent gClassicRetroArabicRtl;
int gDrawnX[4];
int gDrawnWidth[4];
int gDrawn;

/* Width marker: leading 0xF nibbles skip, following non-0xF nibbles count. */
static u32 sub_0805F7A0(u32 value) {
    u32 mask = 0xf;
    u32 i;
    u32 j;
    for (i = 0; i < 8; i++) {
        if (mask != (value & mask))
            break;
        mask <<= 4;
    }
    for (j = i; i < 8 && mask != (value & mask); mask <<= 4, i++) {
    }
    return ((i - j) << 8) | j;
}

/* Draw one 8x16 half at unk6, clamped to the room left before unk4. */
static void sub_0805F820(WStruct* w, u32* glyph) {
    int room = (int)w->unk4 - (int)w->unk6;
    u32 width;
    if (room <= 0)
        return;
    width = w->unk1 ? 8 : sub_0805F7A0(glyph[0]) >> 8;
    if (room > 8)
        room = 8;
    if ((int)width > room)
        width = room;
    gDrawnX[gDrawn] = w->unk6;
    gDrawnWidth[gDrawn] = width;
    gDrawn++;
    w->unk6 += width;
}
"""

_HARNESS_EXPORTS = """
static u32 marker(u32 width) {
    u32 value = 0;
    u32 i;
    for (i = width; i < 8; i++)
        value |= 0xfu << (4 * i);
    return value;
}

int draw(int dialog, int bound, int cursor, int left, int right, int page, int first, int second,
         int* result) {
    static WStruct other;
    WStruct* w = dialog ? &gTextRender._50 : &other;
    u32 glyph[0x20] = {0};
    u32 drawn = 0;
    int ok;
    glyph[0] = marker(first);
    glyph[0x10] = marker(second);
    w->unk4 = bound;
    w->unk6 = cursor;
    w->unk1 = 0;
    gClassicRetroArabicRtl.left = left;
    gClassicRetroArabicRtl.right = right;
    gDrawn = 0;
    ok = ClassicRetroArabicDrawGlyphRtl((page << 8) | 1, w, glyph, &drawn);
    result[0] = ok;
    result[1] = drawn;
    result[2] = w->unk6;
    result[3] = w->unk4;
    result[4] = gDrawn;
    result[5] = gDrawn > 0 ? gDrawnX[0] : -1;
    result[6] = gDrawn > 1 ? gDrawnX[1] : -1;
    result[7] = gDrawn > 1 ? gDrawnWidth[1] : -1;
    return ok;
}

void set_variables(const char* name, const char* number) {
    int i = 0;
    int n = 0;
    gTextRender.player_name[i++] = 2;
    gTextRender.player_name[i++] = 0xe;
    while (name[n])
        gTextRender.player_name[i++] = name[n++];
    gTextRender.player_name[i++] = 2;
    gTextRender.player_name[i++] = 0xf;
    gTextRender.player_name[i] = 0;
    for (i = 0; i < 8; i++)
        gTextRender._68.s[i] = 0;
    for (i = 0; number[i]; i++)
        gTextRender._68.s[i] = number[i];
    gTextRender._50.rtlVariables = 0;
}

void set_order(int rtl) {
    ClassicRetroArabicSetVariableOrder(rtl);
}

const char* player_name(void) {
    return gTextRender.player_name;
}

const char* number(void) {
    return gTextRender._68.s;
}
"""


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    compiler = shutil.which("cc")
    if os.name != "posix" or compiler is None:
        pytest.skip("Native renderer regression checks require a POSIX C compiler")
    directory = tmp_path_factory.mktemp("tmc_native")
    variable_functions = overlay._VARIABLE_ORDER_FUNCTIONS.replace(
        "static void ClassicRetroArabicSetVariableOrder",
        "void ClassicRetroArabicSetVariableOrder",
    )
    source = directory / "regression.c"
    source.write_text(
        _HARNESS_PRELUDE
        + "static bool32 ClassicRetroArabicDrawGlyphRtl(u32, WStruct*, u32*, u32*);\n"
        + overlay._RTL_DRAW_FUNCTION
        + variable_functions
        + _HARNESS_EXPORTS,
        encoding="utf-8",
    )
    library = directory / "regression.so"
    subprocess.run(
        [compiler, "-shared", "-fPIC", "-Wall", "-Werror", str(source), "-o", str(library)],
        check=True,
    )
    lib = ctypes.CDLL(str(library))
    lib.player_name.restype = ctypes.c_char_p
    lib.number.restype = ctypes.c_char_p
    return lib


def _draw(native, **kwargs):
    result = (ctypes.c_int * 8)()
    arguments = (
        kwargs.get("dialog", 1),
        kwargs["bound"],
        kwargs["cursor"],
        kwargs.get("left", 0),
        kwargs.get("right", 0),
        kwargs.get("page", 9),
        kwargs["first"],
        kwargs.get("second", 0),
    )
    native.draw(*arguments, result)
    return list(result)


def test_first_dialogue_glyph_is_painted_at_the_right_edge(native):
    ok, drawn, cursor, bound, halves, x0, x1, width1 = _draw(
        native, bound=0xD0, cursor=0, first=8, second=3
    )
    assert (ok, drawn, cursor, bound, halves) == (1, 11, 11, 0xD0, 2)
    # Both halves in reading position: 197..204 then 205..207.
    assert (x0, x1, width1) == (0xD0 - 11, 0xD0 - 3, 3)


def test_second_dialogue_line_mirrors_inside_its_own_extent(native):
    result = _draw(native, bound=0x1A0, cursor=0xD0 + 20, page=1, first=6)
    assert result[:3] == [1, 6, 0xD0 + 26]
    assert result[5] == 0x1A0 - 26


def test_text_box_line_uses_the_recorded_extent(native):
    result = _draw(native, dialog=0, bound=240, cursor=6, left=6, right=105, first=8)
    assert result[:3] == [1, 8, 14]
    assert result[5] == 6 + 105 - 6 - 8


def test_cursor_outside_extent_falls_back_to_left_to_right(native):
    result = _draw(native, dialog=0, bound=240, cursor=2, left=6, right=105, first=8)
    assert result[0] == 0
    assert result[4] == 0


def test_glyph_cut_by_the_line_end_never_underflows(native):
    result = _draw(native, bound=0xD0, cursor=0xD0 - 4, first=8, second=3)
    assert result[:3] == [1, 4, 0xD0]
    assert result[5] == 0


def test_runtime_variables_are_reversed_once_and_restored(native):
    native.set_variables(b"Link", b"300")

    native.set_order(1)
    assert native.player_name() == b"\x02\x0ekniL\x02\x0f"
    assert native.number() == b"003"

    native.set_order(1)  # already right-to-left: no double reversal
    assert native.player_name() == b"\x02\x0ekniL\x02\x0f"

    native.set_order(0)
    assert native.player_name() == b"\x02\x0eLink\x02\x0f"
    assert native.number() == b"300"


def test_six_letter_name_keeps_its_terminator_in_the_padding(native):
    # MsgInit writes the EOS of a six-letter name into TextRender._66[0].
    native.set_variables(b"ABCDEF", b"1234567")
    native.set_order(1)
    assert native.player_name() == b"\x02\x0eFEDCBA\x02\x0f"
    assert native.number() == b"7654321"
    native.set_order(0)
    assert native.player_name() == b"\x02\x0eABCDEF\x02\x0f"


# --------------------------------------------------------------------------- tree state


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
        lambda texts, encoder, measure: {path: overlay._PATCH_MARKER for path in texts},
    )
    return source


def test_failed_font_build_does_not_modify_pristine_source(source_tree):
    before = (source_tree / "src/text.c").read_bytes()
    with pytest.raises(ClassicRetroError, match="font file not found"):
        overlay.prepare_tmc_arabic_source(source_tree, source_tree / "absent.ttf")
    assert (source_tree / "src/text.c").read_bytes() == before
    assert not (source_tree / overlay._STATE_FILE).exists()
    assert not (source_tree / "data").exists()


def test_prepared_source_must_match_recorded_overlay(source_tree, monkeypatch):
    characters = build_tmc_arabic_glyph_map().characters

    def build_font(font_path):
        return TmcArabicFontResult(
            glyphs=len(characters),
            font_size=10,
            baseline=11,
            widths=dict.fromkeys(characters, 6),
            max_advance=6,
            data=b"\xff" * 128 * len(characters),
        )

    monkeypatch.setattr(overlay, "build_tmc_arabic_font", build_font)
    (source_tree / "font.ttf").write_bytes(b"test font")
    first = overlay.prepare_tmc_arabic_source(source_tree, source_tree / "font.ttf")
    second = overlay.prepare_tmc_arabic_source(source_tree, source_tree / "font.ttf")
    assert not first["already_patched"]
    assert second["already_patched"]
    assert (source_tree / overlay.FONT_BINARY).stat().st_size == 128 * len(characters)
    assert (source_tree / "data/classic_retro_arabic.s").read_text().count(".incbin") == 1

    (source_tree / "src/text.c").write_text(overlay._PATCH_MARKER + " changed", encoding="utf-8")
    with pytest.raises(ClassicRetroError, match="Modified or partially patched"):
        overlay.prepare_tmc_arabic_source(source_tree, source_tree / "font.ttf")


def test_untracked_overlay_is_not_silently_reused(source_tree):
    (source_tree / "src/text.c").write_text(overlay._PATCH_MARKER, encoding="utf-8")
    with pytest.raises(ClassicRetroError, match="fresh checkout"):
        overlay.prepare_tmc_arabic_source(source_tree, source_tree / "font.ttf")


def test_pristine_check_reports_mismatched_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/text.c").write_text("different", encoding="utf-8")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.check_tmc_arabic_source(tmp_path)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert "src/text.c:" in str(caught.value)
    assert "include/message.h:missing" in str(caught.value)
