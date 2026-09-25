"""Arabic ROM overlay for *Pokémon Mystery Dungeon: Red Rescue Team* (USA).

The pret/pmd-red decompilation (https://github.com/pret/pmd-red) builds this
exact image and gave every address below; its data is still extracted from
the original, so the overlay patches the user's image (``B24E``, SHA-256
below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified, and
   every translated string's original is checked against its pinned hash;
2. the Thumb hooks (``pmd_arabic_hooks.s``), a new charmap and the
   translated strings go into the padding (``0xFF``) between the end of the
   code and the data at ``0x08300000``; the image stays 32 MiB;
3. the new charmap holds the game's 473 entries, unchanged, and the
   right-to-left glyphs (``engines.pmd_arabic``) under codes ``0x84XX``,
   sorted as the game's binary search needs; the ``kanji_a`` file's ``SIRO``
   header is repointed to it;
4. the three calls of ``DrawCharOnWindowInternal`` go to ``hook_draw``; the
   key arrow of ``{WAIT_PRESS}`` and the menu cursor get their own hooks;
5. the pointers to the personality test's strings (script commands, question
   and answer tables, the gender question) are repointed to the Arabic.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import bl_instruction, bl_target, branch_instruction
from classic_retro.engines.pmd import (
    ENTRY_BYTES,
    GLYPH_BYTES,
    ROM_BASE,
    PmdCharmap,
    PmdGlyphEntry,
    command_skeleton,
    parse_notation,
    pmd_notation,
    read_string,
)
from classic_retro.engines.pmd_arabic import (
    ARABIC_LEAD,
    BASELINE,
    LATIN_COPIES,
    LINE_WIDTH,
    RTL_FLAG,
    RTL_STYLE,
    USA_LATIN_WIDTHS,
    PmdArabicEncoder,
    PmdRtlFont,
    PmdRtlGlyph,
    PmdTextBox,
    build_pmd_arabic_glyph_map,
    build_pmd_rtl_font,
    font_preview,
    latin_rtl_glyphs,
    string_preview,
    strings_sheet,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.pmd_arabic_script import PmdArabicString, pmd_arabic_strings

USA_SHA256 = "ad316814c77ed083734d816ebcde2ece390efae8d15bcb6c66d7c2862d82eb68"
USA_SIZE = 0x2000000

# kanji_a: "SIRO", then the pointer to {count, entries}.
CHARMAP_FILE_ADDRESS = 0x0830F66C
CHARMAP_TABLE_ADDRESS = 0x083191B0
CHARMAP_ENTRIES_ADDRESS = 0x08317B84
CHARMAP_COUNT = 473
SIRO_POINTER_ADDRESS = CHARMAP_FILE_ADDRESS + 4

# The code and its IWRAM copy end at 0x08272B3C; 0xFF padding follows up to
# the data at 0x08300000.
PADDING_START = 0x08272B3C
PADDING_END = 0x08300000
HOOK_CODE_ADDRESS = 0x08272C00
CHARMAP_ADDRESS = 0x08273000
ARABIC_TEXT_ADDRESS = 0x08280000
REGION_END = 0x08290000
FREE_FILL = 0xFF
HOOK_SOURCE = Path(__file__).with_name("pmd_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi pmd_arabic_hooks.s; ld -Ttext 0x08272C00; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "f0b584b004000d0016001f00099800900a980190380095f5b5fc027a01231a40"
    "01994823594309194723ca54002a2dd00423cb5edb005b1b0622825e9d1a0098"
    "0f2108408000344908583449401834490a680292104008603249096889003248"
    "09180a6803920c220a602000290032003b0094f5f9fb2a49029a0a6029490968"
    "8900294a8918039a0a6005e02000290032003b0094f5e8fb04b0f0bc02bc0847"
    "42460023d05ec00029884723d35c002b03d140180238288170470423d35edb00"
    "c018401a0e38288170470021605ec000aa884721615c002902d1801828817047"
    "0421615ec90040180838801a288170470fb53168482251430c4a89184722895c"
    "002903d041880a4a114341800fbc92f5cff908bc184700003c850b0811111111"
    "30b00202ac74020228b002027073020200100000"
)
HOOK_SYMBOLS = {
    "hook_draw": 0x000,
    "hook_wait_arrow": 0x0A0,
    "hook_cursor_x": 0x0CA,
    "hook_cursor_sprite": 0x0F0,
}
IMAGE = ImageSpec("Pokémon Mystery Dungeon: Red Rescue Team (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("PMD hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "pokemon-mystery-dungeon-red-usa-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class HookSite:
    """Code replaced by a ``BL`` to a hook, then (``resume``) a branch over the rest."""

    address: int
    original: bytes
    symbol: str
    purpose: str
    resume: int | None = None


HOOK_SITES = (
    HookSite(0x08007454, bytes.fromhex("00f008f8"), "hook_draw", "DrawCharOnWindow"),
    HookSite(0x080090D0, bytes.fromhex("fef7caf9"), "hook_draw", "DrawStringInternal"),
    HookSite(0x0800911A, bytes.fromhex("fef7a5f9"), "hook_draw", "DrawStringInternal (spaced)"),
    HookSite(
        0x0800931A,
        bytes.fromhex("42460023d05ec0002988401802382881"),
        "hook_wait_arrow",
        "HandleCharFormatInternal: {WAIT_PRESS} arrow",
        resume=0x0800932A,
    ),
    HookSite(
        0x08013690,
        bytes.fromhex("0021605ec000aa8880182881"),
        "hook_cursor_x",
        "UpdateMenuCursorSpriteCoords",
        resume=0x0801369C,
    ),
    HookSite(0x080132D2, bytes.fromhex("f1f7edfe"), "hook_cursor_sprite", "AddMenuCursorSprite_"),
)


@dataclass(frozen=True, slots=True)
class PmdArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: PmdRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset


def site_patch(site: HookSite) -> bytes:
    code = bl_instruction(site.address, HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol])
    if site.resume is not None:
        code += branch_instruction(site.address + 4, site.resume)
    return code


def source_digest(data: bytes) -> str:
    """SHA-256 of an original string's bytes, terminator excluded."""
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> PmdCharmap:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 32 MiB")
    for site in HOOK_SITES:
        start = _offset(site.address)
        if rom[start : start + len(site.original)] != site.original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected code at {site.address:#x} ({site.purpose})",
            )
    if not IMAGE.filled(rom, PADDING_START, PADDING_END, FREE_FILL):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{PADDING_START:#x}..{PADDING_END:#x} is not empty padding",
        )
    charmap = PmdCharmap.parse(rom, CHARMAP_FILE_ADDRESS)
    if (
        charmap.table_address != CHARMAP_TABLE_ADDRESS
        or charmap.entries_address != CHARMAP_ENTRIES_ADDRESS
        or len(charmap.entries) != CHARMAP_COUNT
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "kanji_a differs from the USA charmap"
        )
    if any(entry.flags for entry in charmap.entries):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "A kanji_a glyph already uses byte 8"
        )
    widths = charmap.widths()
    if {character: widths.get(ord(character)) for character in LATIN_COPIES} != USA_LATIN_WIDTHS:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "kanji_a punctuation differs from the USA font"
        )
    taken = set(widths) & set(build_pmd_arabic_glyph_map().all_codes())
    if taken:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "Right-to-left codes are already used: " + ", ".join(f"{code:#x}" for code in taken),
        )
    return charmap


def _verify_source(rom: bytes, string: PmdArabicString) -> bytes:
    for reference in string.references:
        (pointer,) = struct.unpack_from("<I", rom, _offset(reference))
        if pointer != string.source_address:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"{string.key}: pointer at {reference:#x} does not lead to "
                f"{string.source_address:#x}",
            )
    original = read_string(rom, string.source_address)
    if source_digest(original) != string.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: the original at {string.source_address:#x} differs from the pinned "
            "USA script",
        )
    if command_skeleton(original) != string.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: the original has different commands than pinned",
        )
    return original


def game_latin_glyphs(rom: bytes, charmap: PmdCharmap) -> dict[str, PmdRtlGlyph]:
    pixels = {character: charmap.pixels(rom, ord(character)) for character in LATIN_COPIES}
    return latin_rtl_glyphs(pixels, USA_LATIN_WIDTHS)


def encode_strings(
    encoder: PmdArabicEncoder, strings: tuple[PmdArabicString, ...] | None = None
) -> dict[str, tuple[bytes, tuple[int, ...]]]:
    """Validate every translation against its original commands and encode it."""
    encoded: dict[str, tuple[bytes, tuple[int, ...]]] = {}
    references: set[int] = set()
    for string in strings or pmd_arabic_strings():
        if string.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"String {string.key} twice")
        if references & set(string.references):
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{string.key} shares a pointer with another string"
            )
        references |= set(string.references)
        pieces = string.pieces
        validate_command_skeleton(string.source_skeleton, pieces)
        result = encoder.encode(pieces, string.box)
        encoded[string.key] = (result.data, result.widths)
    return encoded


def charmap_data(
    charmap: PmdCharmap, font: PmdRtlFont, address: int
) -> tuple[bytes, tuple[PmdGlyphEntry, ...]]:
    """``{count, entries}``, the merged entries, then the right-to-left bitmaps."""
    codes = sorted(font.glyphs)
    count = len(charmap.entries) + len(codes)
    entries_address = address + 8
    bitmaps_address = entries_address + count * ENTRY_BYTES
    added = [
        PmdGlyphEntry(
            code=code,
            width=font.glyphs[code].width,
            flags=RTL_FLAG,
            style=RTL_STYLE,
            bitmap=bitmaps_address + number * GLYPH_BYTES,
        )
        for number, code in enumerate(codes)
    ]
    entries = tuple(sorted((*charmap.entries, *added), key=lambda entry: entry.code))
    data = bytearray(struct.pack("<iI", count, entries_address))
    for entry in entries:
        data += entry.pack()
    for code in codes:
        data += font.glyphs[code].bitmap()
    return bytes(data), entries


def build_pmd_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    strings: tuple[PmdArabicString, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> PmdArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``strings`` and ``verify_identity`` exist for synthetic tests; a real build
    always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    charmap = _verify_anchors(rom)
    strings = strings or pmd_arabic_strings(translations)
    for string in strings:
        _verify_source(rom, string)
    font = build_pmd_rtl_font(font_path, game_latin_glyphs(rom, charmap))
    table, entries = charmap_data(charmap, font, CHARMAP_ADDRESS)
    if CHARMAP_ADDRESS + len(table) > ARABIC_TEXT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The charmap exceeds its region")
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > CHARMAP_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")

    encoded = encode_strings(PmdArabicEncoder(font), strings)
    texts = bytearray()
    addresses: dict[str, int] = {}
    for string in strings:
        addresses[string.key] = ARABIC_TEXT_ADDRESS + len(texts)
        texts += encoded[string.key][0]
        texts += bytes(-len(texts) % 4)
    if ARABIC_TEXT_ADDRESS + len(texts) > REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic strings exceed the region")

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(CHARMAP_ADDRESS, table)
    write(ARABIC_TEXT_ADDRESS, bytes(texts))
    write(SIRO_POINTER_ADDRESS, struct.pack("<I", CHARMAP_ADDRESS))
    for site in HOOK_SITES:
        write(site.address, site_patch(site))
    for string in strings:
        for reference in string.references:
            write(reference, struct.pack("<I", addresses[string.key]))

    output = bytes(target)
    _verify_output(output, rom, charmap, entries, strings, encoded, addresses)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "strings": len(strings),
        "pointers": sum(len(string.references) for string in strings),
        "string_lines": {string.key: list(encoded[string.key][1]) for string in strings},
        "string_boxes": {string.key: str(string.box) for string in strings},
        "line_width": {str(box): width for box, width in LINE_WIDTH.items()},
        "rtl_glyphs": len(font.glyphs),
        "rtl_codes": f"{ARABIC_LEAD:#x}40..{ARABIC_LEAD:#x}{max(font.glyphs) & 0xFF:02x}",
        "charmap_glyphs": len(entries),
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "charmap_address": f"{CHARMAP_ADDRESS:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(texts),
    }
    return PmdArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    rom: bytes,
    charmap: PmdCharmap,
    entries: tuple[PmdGlyphEntry, ...],
    strings: tuple[PmdArabicString, ...],
    encoded: dict[str, tuple[bytes, tuple[int, ...]]],
    addresses: dict[str, int],
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {_offset(SIRO_POINTER_ADDRESS) & ~0xFFF}
    allowed |= {_offset(site.address) & ~0xFFF for site in HOOK_SITES}
    allowed |= {
        _offset(reference) & ~0xFFF for string in strings for reference in string.references
    }
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS) & ~0xFFF, _offset(REGION_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    rebuilt = PmdCharmap.parse(output, CHARMAP_FILE_ADDRESS)
    if rebuilt.entries != entries or rebuilt.table_address != CHARMAP_ADDRESS:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The charmap does not read back")
    kept = [entry for entry in rebuilt.entries if not entry.flags & RTL_FLAG]
    if tuple(kept) != charmap.entries:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The game's own glyph entries changed"
        )
    for site in HOOK_SITES:
        start = _offset(site.address)
        patched = output[start : start + len(site.original)]
        if bl_target(site.address, patched[:4]) != HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Call at {site.address:#x} misses its hook"
            )
    for string in strings:
        for reference in string.references:
            (pointer,) = struct.unpack_from("<I", output, _offset(reference))
            if pointer != addresses[string.key]:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key}: pointer not repointed"
                )
        if read_string(output, addresses[string.key]) + b"\0" != encoded[string.key][0]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key} does not read back"
            )
    start = _offset(HOOK_CODE_ADDRESS)
    if output[start : start + len(HOOK_CODE)] != HOOK_CODE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook code was not written")


def check_pmd_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every line."""
    font = build_pmd_rtl_font(font_path) if font_path is not None else None
    if font is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    strings = pmd_arabic_strings(translations)
    encoded = encode_strings(PmdArabicEncoder(font), strings)
    if font is not None and text_preview_path is not None:
        strings_sheet(
            [
                (string.key, string_preview(font, encoded[string.key][0], string.box))
                for string in strings
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "strings": len(strings),
        "pointers": sum(len(string.references) for string in strings),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(data) for data, _ in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["rtl_glyphs"] = len(font.glyphs)
        report["widest_line"] = {
            str(box): max(
                (max(encoded[string.key][1]) for string in strings if string.box == box),
                default=0,
            )
            for box in LINE_WIDTH
        }
    return report


def encode_pmd_arabic_line(
    text: str, font_path: Path | None = None, box: PmdTextBox = PmdTextBox.DIALOGUE
) -> dict[str, object]:
    """Encode one string in notation for ``box``; with a font, report its line widths."""
    font = build_pmd_rtl_font(font_path) if font_path is not None else None
    result = PmdArabicEncoder(font).encode(parse_notation(text), box)
    payload: dict[str, object] = {"bytes": result.data.hex(" "), "count": len(result.data)}
    if font is not None:
        payload["widths"] = list(result.widths)
        payload["line_width"] = LINE_WIDTH[box]
    return payload


def write_build_outputs(
    build: PmdArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    strings: tuple[PmdArabicString, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    strings = strings or pmd_arabic_strings(translations)
    _verify_anchors(rom)
    return {string.key: pmd_notation(_verify_source(rom, string)) for string in strings}


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
