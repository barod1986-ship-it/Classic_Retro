"""Arabic source overlay for the zeldaret/tmc decompilation (The Minish Cap, USA).

The overlay only targets the pinned upstream commit. Every touched file is
checked by Git blob hash before modification, the font is generated before any
source edit, and the result is recorded so that a partially or differently
patched tree is refused.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tmc import (
    TMC_DIALOGUE_LINE_WIDTH,
    TMC_PLAYER_NAME_LENGTH,
    control_signature,
    glyph_advance,
    latin_glyph_widths,
    parse_tmc_string,
    tmc_color,
    tmc_jump,
    tmc_line,
    tmc_player,
    tmc_raw,
    tmc_sound,
)
from classic_retro.engines.tmc_arabic import (
    TmcArabicEncoder,
    TmcArabicFontResult,
    build_tmc_arabic_font,
    build_tmc_arabic_glyph_map,
    font_preview,
)
from classic_retro.text.tokens import InlineToken, TextToken, Token, TokenStream

PINNED_COMMIT = "d92d4581e202ae531bdcc206a7d6a90ddb8fd907"
USA_ROM_SHA1 = "b4bd50e4131b027c334547b4524e2dbbd4227130"
_PATCH_MARKER = "CLASSIC_RETRO_ARABIC_V1"
_OVERLAY_VERSION = 1
_STATE_FILE = ".classic-retro-arabic.json"
FONT_BINARY = "data/classic_retro/arabic_font.4bpp"
FONT_PREVIEW = "data/classic_retro/arabic_font_preview.png"

_PINNED_BLOBS = {
    "include/message.h": "dbb5ac5547449c740312a046fd4c87f01aabdbc5",
    "src/text.c": "90f043865d40217cb0e58cf9351a6858b98c7e00",
    "src/message.c": "54ab722f15f601e514360488de8bf11102c8b344",
    "data/const/text.s": "26884566e64b63e6128dbd07a227dfe9a9f2aa41",
    "linker.ld": "c4e151282516e8a1461ae0acc96b3280812b92cc",
    "translations/USA.json": "80eb8846c2866e89a2e5bbbf9fb82290fc304690",
}

# USA Latin font advances (glyph row-0 width markers of the pinned ROM).
# Used for line measurement when the extracted font is not available.
_USA_LATIN_WIDTHS = {
    " ": 4, "!": 3, '"': 7, "#": 8, "$": 8, "%": 8, "&": 8, "'": 3, "(": 5, ")": 5, "*": 6,
    "+": 7, ",": 5, "-": 8, ".": 5, "/": 8, "0": 6, "1": 6, "2": 6, "3": 6, "4": 7, "5": 6,
    "6": 6, "7": 6, "8": 7, "9": 6, ":": 5, ";": 8, "<": 8, "=": 8, ">": 8, "?": 7, "@": 8,
    "A": 6, "B": 6, "C": 7, "D": 6, "E": 6, "F": 6, "G": 7, "H": 6, "I": 5, "J": 7, "K": 7,
    "L": 7, "M": 6, "N": 6, "O": 7, "P": 6, "Q": 7, "R": 6, "S": 6, "T": 6, "U": 6, "V": 6,
    "W": 6, "X": 6, "Y": 6, "Z": 6, "[": 8, "]": 8, "^": 8, "_": 8, "`": 3, "a": 7, "b": 6,
    "c": 6, "d": 6, "e": 6, "f": 5, "g": 7, "h": 6, "i": 3, "j": 5, "k": 6, "l": 3, "m": 6,
    "n": 6, "o": 6, "p": 6, "q": 6, "r": 5, "s": 6, "t": 5, "u": 6, "v": 6, "w": 6, "x": 6,
    "y": 6, "z": 6,
}  # fmt: skip
# Widest glyph a player may type in the name-entry grid (extension page included).
_USA_NAME_GLYPH_MAX = 8

_PROLOGUE_WIDE = 0xF0
_PROLOGUE_NARROW = 0x78


@dataclass(frozen=True, slots=True)
class TmcArabicMessage:
    table: int
    index: int
    line_width: int
    stream: TokenStream

    @property
    def label(self) -> str:
        return f"{self.table:02X}{self.index:02X}"


def _text(value: str) -> TextToken:
    return TextToken(value)


def _lines(label: str, *parts: str | Token) -> TokenStream:
    """Build a stream where '\\n' inside strings becomes an ordered line break."""
    tokens: list[Token] = []
    counter = 0
    for part in parts:
        if isinstance(part, str):
            chunks = part.split("\n")
            for number, chunk in enumerate(chunks):
                if number:
                    tokens.append(tmc_line(f"{label}_line{counter}"))
                    counter += 1
                if chunk:
                    tokens.append(_text(chunk))
        else:
            tokens.append(part)
    return TokenStream(tuple(tokens))


def _green(label: str) -> InlineToken:
    return tmc_color(f"{label}_green", "Green")


def _white(label: str) -> InlineToken:
    return tmc_color(f"{label}_white", "White")


def _player(label: str) -> InlineToken:
    return tmc_player(f"{label}_player")


def _window_y(label: str) -> InlineToken:
    return tmc_raw(f"{label}_window", "{04:10:00}", "RENDER_CONTROL")


def tmc_arabic_messages() -> tuple[TmcArabicMessage, ...]:
    """The new-game opening: storybook prologue, the Smith house scene and the walk to town."""
    d = TMC_DIALOGUE_LINE_WIDTH
    return (
        TmcArabicMessage(0x0F, 0x01, _PROLOGUE_WIDE, _lines("0f01", "منذ زمن بعيد جدا...")),
        TmcArabicMessage(
            0x0F,
            0x02,
            _PROLOGUE_WIDE,
            _lines("0f02", "حين كان العالم على وشك\nأن يبتلعه الظلام..."),
        ),
        TmcArabicMessage(
            0x0F,
            0x03,
            _PROLOGUE_NARROW,
            _lines(
                "0f03", "ظهر البيكوري\nالصغار من السماء،\nحاملين لبطل\nالبشر سيفا\nونورا ذهبيا."
            ),
        ),
        TmcArabicMessage(
            0x0F,
            0x04,
            _PROLOGUE_NARROW,
            _lines("0f04", "بالحكمة والشجاعة،\nطرد البطل\nالظلام."),
        ),
        TmcArabicMessage(
            0x0F,
            0x05,
            _PROLOGUE_WIDE,
            _lines("0f05", "وحين عاد السلام، حفظ الناس\nذلك السيف في مزار بكل عناية."),
        ),
        TmcArabicMessage(
            0x0F,
            0x06,
            _PROLOGUE_WIDE,
            _lines(
                "0f06",
                "أما قوة النور الذهبي، فقد تجسدت\nفي أميرة هايرول،\nوأشرقت على كل الأرجاء.",
            ),
        ),
        TmcArabicMessage(
            0x0F,
            0x07,
            d,
            _lines(
                "0f07", tmc_sound("0f07_sound", 0x01, 0xE8), "هه هه هه...\nإذن هذا هو معناها..."
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x01,
            d,
            _lines(
                "1001",
                tmc_sound("1001_sound", 0x00, 0x95),
                "صباح الخير يا ",
                _green("1001"),
                "معلم سميث",
                _white("1001"),
                ".",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x02,
            d,
            _lines(
                "1002",
                tmc_sound("1002_sound", 0x00, 0xC2),
                "يا للعجب! ",
                _green("1002"),
                "الأميرة زيلدا",
                _white("1002"),
                "!\n\nهل تسللت من القلعة\nوجئت كل هذه المسافة وحدك؟\n"
                "لا بد أن الوزير قلق عليك!\nتعرفين كيف يكون حاله!",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x03,
            d,
            _lines(
                "1003",
                "لا تقلق بشأنه! سيكون بخير.\nأين ",
                _player("1003"),
                "؟\nالبلدة كلها تحتفل بقدوم\n",
                tmc_color("1003_blue", "Blue"),
                "مهرجان بيكوري",
                _white("1003"),
                " السنوي!\nفكرت أن نذهب إليه معا.\nهل تمانع؟",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x04,
            d,
            _lines(
                "1004",
                "آه، أهذا ما جئت من أجله؟\n\nحسنا، سهر ",
                _player("1004"),
                " يساعدني\nليلة أمس، وما زال نائما...\nلكن لدي مهمة في\n"
                "القلعة... نعم، لا بأس بذلك.\n",
                tmc_jump("1004_next", 0x10, 0x05),
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x05,
            d,
            _lines("1005", _player("1005"), "، حان وقت الاستيقاظ!"),
        ),
        TmcArabicMessage(
            0x10,
            0x09,
            d,
            _lines(
                "1009",
                _window_y("1009"),
                "هيه يا ",
                _player("1009"),
                "!\n\n",
                _green("1009"),
                "الأميرة زيلدا",
                _white("1009"),
                " هنا. تريد أن تعرف\nإن كنت ستذهب معها إلى المهرجان.",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x0A,
            d,
            _lines(
                "100a",
                "نعم يا ",
                _player("100a"),
                ". هيا بنا!\nلنذهب إلى المهرجان معا!\n",
                _green("100a"),
                "المعلم سميث",
                _white("100a"),
                " سمح لي\nبأن آخذك معي!",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x0B,
            d,
            _lines(
                "100b",
                _window_y("100b"),
                "نعم. فالمهرجان لا يأتي إلا\nمرة في السنة. اذهب واستمتع!\n"
                "وبينما أنت هناك، أريد منك\nخدمة صغيرة.\nلقد أنهيت صنع هذا ",
                tmc_color("100b_red", "Red"),
                "السيف",
                _white("100b_sword"),
                " لوزير\n",
                _green("100b"),
                "قلعة هايرول",
                _white("100b"),
                ".\nأريدك أن توصله إليه.",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x0C,
            d,
            _lines(
                "100c",
                _window_y("100c"),
                "هذا هو السيف الذي سيقدم\nللفائز في المسابقة.\n"
                "لا تضيعه. ومع أنكما\nصديقا طفولة، تذكر...\n",
                tmc_jump("100c_next", 0x10, 0x0E),
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x0D,
            d,
            _lines(
                "100d",
                "كف عن القلق يا معلم سميث!\nسنكون بأمان تام.\nهيا يا ",
                _player("100d"),
                "! لنذهب\nإلى المهرجان!",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x0E,
            d,
            _lines(
                "100e",
                _window_y("100e"),
                "زيلدا هي أميرة هايرول.\n\nاعتن بها جيدا، ولا تدع\nأي مكروه يصيبها.",
            ),
        ),
        TmcArabicMessage(
            0x10,
            0x10,
            d,
            _lines("1010", tmc_sound("1010_sound", 0x00, 0x94), _player("1010"), "! من هنا!\n"),
        ),
        TmcArabicMessage(
            0x10,
            0x11,
            d,
            _lines("1011", "هيا يا ", _player("1011"), ". لنسرع\nإلى القلعة."),
        ),
        TmcArabicMessage(
            0x10,
            0x12,
            d,
            _lines(
                "1012", tmc_sound("1012_sound", 0x00, 0x95), _player("1012"), "!\nأسرع! هيا بنا!"
            ),
        ),
        TmcArabicMessage(0x10, 0x13, d, _lines("1013", "من هنا! هيا!\nأسرع!")),
        TmcArabicMessage(
            0x10,
            0x14,
            d,
            _lines(
                "1014",
                "ها قد وصلنا إلى ",
                _green("1014"),
                "بلدة هايرول",
                _white("1014"),
                "!",
            ),
        ),
        # Received inside the Smith's house scene.
        TmcArabicMessage(
            0x05,
            0x34,
            d,
            _lines(
                "0534",
                tmc_raw("0534_window", "{04:10:0E}", "RENDER_CONTROL"),
                "لقد استلمت ",
                tmc_color("0534_red", "Red"),
                "سيف سميث",
                _white("0534"),
                "!\n\nاحرص على ألا تفقد هذه\nالأمانة البالغة الأهمية!",
            ),
        ),
        # Arrival at the festival in Hyrule Town.
        TmcArabicMessage(
            0x25,
            0x01,
            d,
            _lines(
                "2501",
                "ها نحن هنا يا ",
                _player("2501"),
                "!\nأليس المكان ممتعا؟\n",
                tmc_jump("2501_next", 0x25, 0x02),
            ),
        ),
        TmcArabicMessage(0x25, 0x02, d, _lines("2502", "هيا! لنتجول في المكان!")),
    )


def check_tmc_arabic_source(source: Path, font_path: Path | None = None) -> dict[str, object]:
    """Dry run against a pristine checkout; with a font, also measure every line."""
    source = source.expanduser().resolve()
    texts = _read_pristine_source(source)
    font = build_tmc_arabic_font(font_path) if font_path is not None else None
    patched = _patch_all(texts, _encoder(source, font), measure=font is not None)
    translated = patched.pop("translations/USA.json")
    if not all(_PATCH_MARKER in value for value in patched.values()):
        raise ClassicRetroError(
            ErrorCode.SOURCE_PATCH_FAILED,
            "Arabic source overlay marker missing after dry-run patch",
        )
    return {
        "upstream_commit": PINNED_COMMIT,
        "files_verified": len(texts),
        "overlay_dry_run": True,
        "arabic_glyphs": len(build_tmc_arabic_glyph_map().characters),
        "arabic_font_page": 9,
        "messages": len(tmc_arabic_messages()),
        "lines_measured": font is not None,
        "translated_json_bytes": len(translated.encode("utf-8")),
    }


def encode_tmc_arabic_line(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one logical line; with a font, also report its rendered pixel width."""
    font = build_tmc_arabic_font(font_path) if font_path is not None else None
    encoder = TmcArabicEncoder(
        arabic_widths=font.widths
        if font is not None
        else dict.fromkeys(build_tmc_arabic_glyph_map().characters, 0),
        latin_widths=dict(_USA_LATIN_WIDTHS),
        player_width=TMC_PLAYER_NAME_LENGTH * _USA_NAME_GLYPH_MAX,
    )
    stream = TokenStream((TextToken(text),))
    result: dict[str, object] = {
        "tmc_strings": encoder.encode_message(stream),
        "glyphs": len(build_tmc_arabic_glyph_map().characters),
    }
    if font is not None:
        result["width_px"] = encoder.line_widths(stream)[0].width
        result["dialogue_width_px"] = TMC_DIALOGUE_LINE_WIDTH
    return result


def prepare_tmc_arabic_source(
    source: Path, font_path: Path, *, preview: bool = True
) -> dict[str, object]:
    source = source.expanduser().resolve()
    text_c = source / "src/text.c"
    already_patched = text_c.is_file() and _PATCH_MARKER in text_c.read_text(encoding="utf-8")

    if already_patched:
        _validate_patched_tree(source)
        texts = None
    else:
        texts = _read_pristine_source(source)

    # Build the font and every translated string before touching upstream files.
    font = build_tmc_arabic_font(font_path)
    encoder = _encoder(source, font)
    if texts is not None:
        patched = _patch_all(texts, encoder, measure=True)
        for relative, content in patched.items():
            (source / relative).write_text(content, encoding="utf-8", newline="\n")
        asm = source / "data/classic_retro_arabic.s"
        asm.parent.mkdir(parents=True, exist_ok=True)
        asm.write_text(_FONT_ASM, encoding="utf-8", newline="\n")

    binary = source / FONT_BINARY
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(font.data)
    if preview:
        font_preview(font, build_tmc_arabic_glyph_map()).save(source / FONT_PREVIEW)

    state = {
        "overlay_version": _OVERLAY_VERSION,
        "upstream_commit": PINNED_COMMIT,
        "source_blobs": {
            relative: _git_blob_sha((source / relative).read_bytes()) for relative in _PINNED_BLOBS
        },
    }
    (source / _STATE_FILE).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    return {
        "upstream_commit": PINNED_COMMIT,
        "source": str(source),
        "already_patched": already_patched,
        "arabic_glyphs": font.glyphs,
        "font_size": font.font_size,
        "font_baseline": font.baseline,
        "max_advance": font.max_advance,
        "font_sha256": hashlib.sha256(font_path.expanduser().read_bytes()).hexdigest(),
        "font_binary": str(binary),
        "font_binary_sha256": hashlib.sha256(font.data).hexdigest(),
        "messages": [message.label for message in tmc_arabic_messages()],
        "build_command": "make CUSTOM=1",
        "base_rom_sha1": USA_ROM_SHA1,
    }


def _encoder(source: Path, font: TmcArabicFontResult | None) -> TmcArabicEncoder:
    # Without a font the glyph notation is still exact; widths are placeholders
    # and callers must not ask for line measurement.
    if font is not None:
        arabic = font.widths
    else:
        arabic = dict.fromkeys(build_tmc_arabic_glyph_map().characters, 0)
    return TmcArabicEncoder(
        arabic_widths=arabic,
        latin_widths=_latin_widths(source),
        player_width=TMC_PLAYER_NAME_LENGTH * _USA_NAME_GLYPH_MAX,
    )


def _latin_widths(source: Path) -> dict[str, int]:
    widths = dict(_USA_LATIN_WIDTHS)
    gfx = source / "build/USA/assets/gfx"
    page = gfx / "gUnk_08692F60.bin"
    page_tail = gfx / "gUnk_08692F60_1.bin"
    if page.is_file() and page_tail.is_file():
        measured = latin_glyph_widths(page.read_bytes() + page_tail.read_bytes())
        mismatched = sorted(
            character
            for character, width in _USA_LATIN_WIDTHS.items()
            if measured.get(character) != width
        )
        if mismatched:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                "Extracted Latin font widths differ from the pinned USA font: "
                + "".join(mismatched),
            )
    return widths


def _translate(json_text: str, encoder: TmcArabicEncoder, measure: bool) -> str:
    tables = json.loads(json_text)
    for message in tmc_arabic_messages():
        try:
            original = tables[message.table][message.index]
        except IndexError as exc:
            raise ClassicRetroError(
                ErrorCode.SOURCE_PATCH_FAILED, f"Text {message.label} not found"
            ) from exc
        expected = control_signature(parse_tmc_string(original))
        actual = control_signature(message.stream)
        if expected != actual:
            raise ClassicRetroError(
                ErrorCode.TOKEN_SET_MISMATCH,
                f"Text {message.label} must keep engine commands {expected}, got {actual}",
            )
        tables[message.table][message.index] = encoder.encode_message(
            message.stream, line_width=message.line_width if measure else None
        )
    return json.dumps(tables, indent=4, ensure_ascii=False) + "\n"


def _read_pristine_source(source: Path) -> dict[str, str]:
    if not source.is_dir():
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"tmc source directory not found: {source}",
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
            "tmc source does not match pinned commit "
            + PINNED_COMMIT
            + ": "
            + ", ".join(mismatches),
        )
    return texts


def _validate_patched_tree(source: Path) -> None:
    try:
        state = json.loads((source / _STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "Untracked Arabic overlay; prepare a fresh checkout of " + PINNED_COMMIT,
        ) from exc
    if (
        not isinstance(state, dict)
        or state.get("overlay_version") != _OVERLAY_VERSION
        or state.get("upstream_commit") != PINNED_COMMIT
        or not isinstance(state.get("source_blobs"), dict)
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "Outdated Arabic overlay; prepare a fresh checkout of " + PINNED_COMMIT,
        )
    changed = [
        relative
        for relative in _PINNED_BLOBS
        if not (source / relative).is_file()
        or _git_blob_sha((source / relative).read_bytes()) != state["source_blobs"].get(relative)
    ]
    if changed:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "Modified or partially patched tmc source: " + ", ".join(changed),
        )


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_PATCH_FAILED,
            f"{label} anchor expected once, found {count}",
        )
    return text.replace(old, new, 1)


def _patch_all(
    texts: dict[str, str], encoder: TmcArabicEncoder, *, measure: bool
) -> dict[str, str]:
    patched = _patch_sources(texts)
    patched["translations/USA.json"] = _translate(texts["translations/USA.json"], encoder, measure)
    return patched


def _patch_sources(texts: dict[str, str]) -> dict[str, str]:
    return {
        "include/message.h": _patch_message_h(texts["include/message.h"]),
        "src/text.c": _patch_text_c(texts["src/text.c"]),
        "src/message.c": _patch_message_c(texts["src/message.c"]),
        "data/const/text.s": _patch_text_s(texts["data/const/text.s"]),
        "linker.ld": _patch_linker(texts["linker.ld"]),
    }


_MARK = _PATCH_MARKER

_FONT_ASM = f"""\t.include "asm/macros.inc"

\t.section .rodata
\t.align 2

@ {_MARK}: Arabic presentation-form glyphs, two 8x16 4bpp halves per glyph.
@ Row 0 of each half is the engine's width marker (0xF = unused column).
gClassicRetroArabicFont::
\t.incbin "{FONT_BINARY}"
"""


def _patch_message_h(text: str) -> str:
    text = _replace_once(
        text,
        "typedef struct {\n    u8 unk00 : 1;\n    u8 unk01 : 3;\n    u8 unk04 : 4;\n    u8 unk1;\n",
        "typedef struct {\n    u8 unk00 : 1;\n"
        f"    u8 rtl : 1; // {_MARK}: mirror glyphs inside the line extent\n"
        "    u8 rtlVariables : 1; // runtime variables are stored reversed\n"
        "    u8 unk03 : 1;\n    u8 unk04 : 4;\n    u8 unk1;\n",
        "WStruct RTL flag",
    )
    return _replace_once(
        text,
        "static_assert(sizeof(WStruct) == 12);\n",
        "static_assert(sizeof(WStruct) == 12);\n\n"
        f"// {_MARK}\n"
        "#define ARABIC_FONT_PAGE 9\n"
        "#define TEXT_CODE_ARABIC_RTL 0xf\n"
        "#define TEXT_CODE_ARABIC_LTR 0x10\n"
        "#define ARABIC_DIALOG_LINE_WIDTH 0xd0\n\n"
        "typedef struct {\n    u16 left;\n    u16 right;\n} ArabicRtlExtent;\n\n"
        "extern ArabicRtlExtent gClassicRetroArabicRtl;\n",
        "Arabic declarations",
    )


def _patch_text_c(text: str) -> str:
    text = _replace_once(
        text,
        "static u32 sub_0805F8F8(u32 idx);\nstatic u32 sub_0805F7A0(u32 param_1);\n",
        "static u32 sub_0805F8F8(u32 idx);\nstatic u32 sub_0805F7A0(u32 param_1);\n"
        "static bool32 ClassicRetroArabicDrawGlyphRtl(u32 chr, WStruct* w, u32* glyph, u32* drawn);"
        f" // {_MARK}\n",
        "text.c prototypes",
    )
    text = _replace_once(
        text,
        """                    case 0x14:
                    case 0x15:
                        code = 0xb;
                        if ((uVar6 ^ 0x14) != 0) {
                            uVar6 = 1;
                        } else {
                            uVar6 = 0;
                        }
                }
""",
        f"""                    case 0x14:
                    case 0x15:
                        code = 0xb;
                        if ((uVar6 ^ 0x14) != 0) {{
                            uVar6 = 1;
                        }} else {{
                            uVar6 = 0;
                        }}
                        break;
                    case 0x16: // {_MARK}
                        code = TEXT_CODE_ARABIC_RTL;
                        break;
                    case 0x17:
                        code = TEXT_CODE_ARABIC_LTR;
                        break;
                    case 0x18:
                        code = (ARABIC_FONT_PAGE << 8) | sub_0805EF8C(token);
                        break;
                }}
""",
        "GetCharacter Arabic sub-codes",
    )
    text = _replace_once(
        text,
        """            case 1:
                code = sub_0805F9A0(code);
                break;
        }
        token->extended = (u16)code;
""",
        f"""            case 1:
                // {_MARK}: the stylized font has no Arabic page.
                if ((code >> 8) != ARABIC_FONT_PAGE) {{
                    code = sub_0805F9A0(code);
                }}
                break;
        }}
        token->extended = (u16)code;
""",
        "stylized font exemption",
    )
    text = _replace_once(
        text,
        """        case 8:
            param_1 = param_1 << 1;
            break;
    }
    return gUnk_08109248[uVar1] + param_1 * 0x10;
""",
        f"""        case 8:
        case ARABIC_FONT_PAGE: // {_MARK}: 16px-wide glyphs
            param_1 = param_1 << 1;
            break;
    }}
    return gUnk_08109248[uVar1] + param_1 * 0x10;
""",
        "Arabic font page lookup",
    )
    text = _replace_once(
        text,
        """                case 2 ... 10:
                case 0xd:
                case 0xe:
                    break;
                default:
                    if (uVar5 == 0) {
""",
        f"""                case 2 ... 10:
                case 0xd:
                case 0xe:
                case TEXT_CODE_ARABIC_RTL: // {_MARK}
                case TEXT_CODE_ARABIC_LTR:
                    break;
                default:
                    if (uVar5 == 0) {{
""",
        "line width Arabic controls",
    )
    text = _replace_once(
        text,
        """    param_3->unk6 = param_1->right_align ? ((8 - ((fontStr + 1) >> 1)) & 7) : 0;

    puVar5 = (u16*)sub_0805F6A4(param_2, param_3);
""",
        f"""    param_3->unk6 = param_1->right_align ? ((8 - ((fontStr + 1) >> 1)) & 7) : 0;
    gClassicRetroArabicRtl.left = param_3->unk6; // {_MARK}
    gClassicRetroArabicRtl.right = param_3->unk6 + (u16)fontStr;

    puVar5 = (u16*)sub_0805F6A4(param_2, param_3);
""",
        "text box RTL extent",
    )
    text = _replace_once(
        text,
        """            case 0xb:
                param_2->unk1 = param_1->param;
                break;
            default:
                iVar4 += sub_0805F7DC(uVar1, param_2);
""",
        f"""            case 0xb:
                param_2->unk1 = param_1->param;
                break;
            case TEXT_CODE_ARABIC_RTL: // {_MARK}
                param_2->rtl = 1;
                break;
            case TEXT_CODE_ARABIC_LTR:
                param_2->rtl = 0;
                break;
            default:
                iVar4 += sub_0805F7DC(uVar1, param_2);
""",
        "line renderer RTL controls",
    )
    text = _replace_once(
        text,
        """    InitToken(&stackToken, textIdOrPtr);
    stackToken.unk05 = param_2->unk04 & 3;
    return sub_0805F6A4(&stackToken, param_2);
""",
        f"""    InitToken(&stackToken, textIdOrPtr);
    stackToken.unk05 = param_2->unk04 & 3;
    gClassicRetroArabicRtl.left = param_2->unk6; // {_MARK}
    gClassicRetroArabicRtl.right = param_2->unk6 + (u16)GetFontStrWith(&stackToken, 0);
    return sub_0805F6A4(&stackToken, param_2);
""",
        "string renderer RTL extent",
    )
    text = _replace_once(
        text,
        """    if (r1->unk4 <= r1->unk6)
        return 0;

    offset = sub_0805F25C(r0);
    temp = r1->unk6;
""",
        f"""    if (r1->unk4 <= r1->unk6)
        return 0;

    offset = sub_0805F25C(r0);
    if (r1->rtl && ClassicRetroArabicDrawGlyphRtl(r0, r1, offset, &temp)) // {_MARK}
        return temp;
    temp = r1->unk6;
""",
        "glyph draw RTL dispatch",
    )
    return _replace_once(
        text,
        "\nvoid sub_0805F820(WStruct* r0, u32* r1) {\n",
        _RTL_DRAW_FUNCTION + "\nvoid sub_0805F820(WStruct* r0, u32* r1) {\n",
        "RTL glyph painter",
    )


_RTL_DRAW_FUNCTION = f"""
// {_MARK}
// Right-to-left painting. Text is stored in paint order (the rightmost glyph
// first). The engine keeps advancing its left-to-right cursor, so bounds,
// centring and choice positions keep their meaning; only the pixels are placed
// at the mirrored position inside the current line extent.
static bool32 ClassicRetroArabicDrawGlyphRtl(u32 chr, WStruct* w, u32* glyph, u32* drawn) {{
    u32 x;
    u32 width;
    u32 left;
    u32 right;
    u32 bound;
    u32 drawX;

    if (w == &gTextRender._50) {{
        // Dialogue canvas: line 1 is x 0..0xd0, line 2 is x 0xd0..0x1a0.
        right = w->unk4;
        left = right - ARABIC_DIALOG_LINE_WIDTH;
    }} else {{
        left = gClassicRetroArabicRtl.left;
        right = gClassicRetroArabicRtl.right;
    }}

    x = w->unk6;
    if (w->unk1 != 0) {{
        width = (chr >> 8) > 4 ? 16 : 8;
    }} else {{
        width = sub_0805F7A0(glyph[0]) >> 8;
        if ((chr >> 8) > 4) {{
            width += sub_0805F7A0(glyph[0x10]) >> 8;
        }}
    }}
    if (x + width > w->unk4) {{
        width = w->unk4 - x;
    }}
    if (x < left || x + width > right) {{
        return FALSE;
    }}

    drawX = left + right - x - width;
    bound = w->unk4;
    w->unk4 = drawX + width;
    w->unk6 = drawX;
    if ((chr >> 8) > 4) {{
        sub_0805F820(w, glyph);
        glyph += 0x10;
    }}
    sub_0805F820(w, glyph);
    w->unk4 = bound;
    w->unk6 = x + width;
    *drawn = width;
    return TRUE;
}}
"""


def _patch_message_c(text: str) -> str:
    text = _replace_once(
        text,
        "static void StatusUpdate(u32 status);\n",
        "static void StatusUpdate(u32 status);\n"
        f"static void ClassicRetroArabicSetVariableOrder(u32 rtl); // {_MARK}\n",
        "message.c prototypes",
    )
    text = _replace_once(
        text,
        """            case 14:
                this->_94 = this->curToken.param;
                break;
            default:
                break;
        }
        if (chr >> 8 == 0)
            return 0;
""",
        f"""            case 14:
                this->_94 = this->curToken.param;
                break;
            case TEXT_CODE_ARABIC_RTL: // {_MARK}
                this->_50.rtl = 1;
                ClassicRetroArabicSetVariableOrder(TRUE);
                break;
            case TEXT_CODE_ARABIC_LTR:
                this->_50.rtl = 0;
                ClassicRetroArabicSetVariableOrder(FALSE);
                break;
            default:
                break;
        }}
        if (chr >> 8 == 0)
            return 0;
""",
        "dialogue RTL controls",
    )
    return _replace_once(
        text,
        "/*static*/ void PaletteChange(TextRender* this, u32 id) {\n",
        _VARIABLE_ORDER_FUNCTIONS + "/*static*/ void PaletteChange(TextRender* this, u32 id) {\n",
        "runtime variable order",
    )


_VARIABLE_ORDER_FUNCTIONS = f"""// {_MARK}
// Runtime variables (player name, numbers) are Latin runs inside Arabic text.
// The dialogue paints right-to-left, so their bytes are reversed while RTL is
// active. The state is a spare WStruct bit: TextRender padding is not free,
// because a six-letter name writes its terminator into _66[0].
static void ClassicRetroArabicReverse(u8* start, u8* end) {{
    u8 tmp;

    while (start < end) {{
        end--;
        tmp = *start;
        *start = *end;
        *end = tmp;
        start++;
    }}
}}

static void ClassicRetroArabicSetVariableOrder(u32 rtl) {{
    u8* start;
    u8* end;
    u32 i;

    if (gTextRender._50.rtlVariables == rtl)
        return;
    gTextRender._50.rtlVariables = rtl;

    // player_name is {{Color:Green}} name {{Color:White}} EOS
    start = (u8*)&gTextRender.player_name[2];
    end = start;
    while (*end != '\\0' && *end != 2) {{
        end++;
    }}
    ClassicRetroArabicReverse(start, end);

    for (i = 0; i < 4; i++) {{
        start = (u8*)(&gTextRender._68 + i)->s;
        end = start;
        while (end < start + sizeof(String8) && *end != '\\0') {{
            end++;
        }}
        ClassicRetroArabicReverse(start, end);
    }}
}}

"""


def _patch_text_s(text: str) -> str:
    return _replace_once(
        text,
        "\t.4byte gUnk_086A2A60\n\t.4byte gUnk_086A2EE0\n",
        "\t.4byte gUnk_086A2A60\n\t.4byte gUnk_086A2EE0\n"
        f"\t.4byte gClassicRetroArabicFont @ {_MARK}: page 9, 16px Arabic glyphs\n",
        "font page table",
    )


def _patch_linker(text: str) -> str:
    text = _replace_once(
        text,
        "#endif\n        . = 0x00040000;\n    } >ewram\n",
        "#endif\n"
        f"        . = 0x0003FFF0; gClassicRetroArabicRtl = .; /* {_MARK} */\n"
        "        . = 0x00040000;\n    } >ewram\n",
        "EWRAM Arabic RTL extent",
    )
    return _replace_once(
        text,
        "        src/eeprom.o(.rodata);\n    } >rom\n",
        "        src/eeprom.o(.rodata);\n"
        f"        data/classic_retro_arabic.o(.rodata); /* {_MARK} */\n"
        "    } >rom\n",
        "ROM Arabic font placement",
    )


def font_glyph_row_markers(data: bytes) -> list[tuple[int, int]]:
    """(first-half width, second-half width) of each glyph, as the engine reads them."""
    return [
        (
            glyph_advance(data[offset : offset + 64]),
            glyph_advance(data[offset + 64 : offset + 128]),
        )
        for offset in range(0, len(data), 128)
    ]
