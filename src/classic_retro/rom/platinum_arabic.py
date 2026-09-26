"""Arabic ROM overlay for *Pokémon Platinum* (USA, Rev 0).

pret/pokeplatinum builds this image byte for byte and gave every address, but
the translation patches the user's own image, so the overlay ships as a BPS
patch. Two images are accepted: the No-Intro Rev 0 dump (the one the
decompilation builds) and a dump that differs from it only in two runs of the
header's reserved bytes (``0x378..0x3A0`` and ``0xF80..0x1000``), which nothing
reads. The build:

1. verifies the input hash and every byte of the game's code that is replaced
   or relied on, the text bank's original of every translated string (its
   pinned hash and commands) and the two fonts;
2. adds the right-to-left glyphs the script uses to the system and message
   fonts (``engines.pokemon_gen4_arabic``), after their 509 glyphs, and
   rebuilds ``graphic/pl_font.narc``;
3. writes the translated strings, in paint order, into the intro's text banks
   (``platinum_arabic_script``) and rebuilds ``msgdata/pl_msg.narc``, each
   bank in place when it fits there;
4. grows the ARM9's ITCM autoload block by the hooks (``platinum_arabic_hooks.s``),
   which the startup code then copies to 0x01FF8680, and points five calls of
   the game's code at them: the glyph draw and the touch-screen icon of the
   printer, and a menu's entries, cursor and cursor erase;
   narrows the control pages' window by two tiles in the intro's overlay: it
   reaches the screen's right edge, where right-aligned lines would touch it;
5. moves the ARM9 overlay table past the image's used area, so the grown ARM9
   binary fits, and writes the files back (``patching.nitro``): the archives
   that grew go past the used area too. The header's CRC and the secure
   area's follow: the calls the hooks take over lie in the secure area's
   unencrypted part. The image stays 128 MiB.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import bl_instruction, bl_target
from classic_retro.engines.pokemon_gen4 import (
    EOS,
    Gen4Font,
    MessageBank,
    command_skeleton,
    lay_out,
    parse_notation,
    text_notation,
)
from classic_retro.engines.pokemon_gen4_arabic import (
    BASELINE,
    NAME_WIDTH,
    RTL_END,
    RTL_FIRST,
    Gen4ArabicEncoder,
    Gen4ArabicEncoding,
    Gen4RtlFont,
    build_gen4_rtl_font,
    font_preview,
    gen4_glyph_codes,
    message_preview,
    messages_sheet,
    painted_characters,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.nitro import (
    SECURE_AREA_CRC,
    Arm9Binary,
    Narc,
    NitroImage,
    header_crc_valid,
    move_arm9_overlay_table,
    replace_arm9,
    replace_files,
    secure_area_crc,
    set_header_crc,
)
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.platinum_arabic_script import (
    BANK_STRINGS,
    CONTROL_INFO,
    DIALOGUE,
    INFO,
    INFO_CHOICES,
    MESSAGE_ARCHIVE,
    RIVAL_NAMES,
    TELEVISION,
    YES_NO,
    PlatinumArabicString,
    platinum_arabic_strings,
)

TITLE = "Pokémon Platinum (USA, Rev 0)"
IMAGE_SIZE = 0x8000000
# The accepted images: the decompilation's (No-Intro) and the header variant.
ACCEPTED_SHA256 = {
    "ede62292aa7f7014ff27d42097e769753380531739889c29b968b67b80f80678": "No-Intro Rev 0",
    "67de86a1bc8e7eb6479dbbbd6e8f5edfc2fa160576a38e40e06d2180ed63b110": (
        "Rev 0, header reserved bytes cleared"
    ),
}
PATCH_NAME = "platinum-usa-arabic-intro.bps"

FONT_ARCHIVE = "graphic/pl_font.narc"
# The system and message fonts: the intro draws its menus and info pages with
# the first, its dialogue with the second.
FONTS = (0, 1)
FONT_SHA256 = "5ec0ba29eb3e8a923d57032d22f7956adf793ac6f8a6a3c6b3a93cd593cac165"
# The text banks as the pinned image holds them.
BANK_SHA256 = {
    389: "bec0626cde61191776fa4ad2bec217e86baf61cf2354e62528a942fb1f51760e",
    607: "5781252c25473668a90dcca1619262008d94721c65afcc2cf9882f0c611bb43f",
}

# The control pages' window template in the intro's overlay (rowan_intro,
# sControlInfoTextWindow at 0x021D37E4): tile 8, 24 tiles wide; 22 leaves
# right-aligned lines a margin of two tiles.
INTRO_OVERLAY = 73
INTRO_OVERLAY_RAM = 0x021D0D80
INTRO_OVERLAY_SIZE = 0x2D80
CONTROL_WINDOW = 0x021D37E4
CONTROL_WINDOW_TEMPLATE = bytes.fromhex("0008001818052d01")
CONTROL_WINDOW_NARROW = bytes.fromhex("0008001618052d01")

# The ITCM autoload block (the first) ends at 0x01FF8660; overlay 3, a
# 32-byte dummy nothing loads, sits after it; the hooks follow.
ITCM_BLOCK = 0
ITCM_BLOCK_ADDRESS = 0x01FF8000
ITCM_BLOCK_SIZE = 0x660
DUMMY_OVERLAY = 3
HOOK_CODE_ADDRESS = 0x01FF8680
HOOK_SOURCE = Path(__file__).with_name("platinum_arabic_hooks.s")

# The game's routines the hooks call (addresses from pret/pokeplatinum).
WINDOW_COPY_GLYPH = 0x0201AED0
WINDOW_FILL_RECT = 0x0201AE78
WINDOW_BLIT_RECT = 0x0201ADDC
COLORED_ARROW_PRINT = 0x02014A58
PRINT_ENTRY = 0x020015D0
RENDER_SCREEN_INDICATOR = 0x0201DB8C
LOAD_SCREEN_INDICATOR = 0x0201DB50
FONT_WORK = 0x02101D48

# arm-none-eabi-as -mcpu=arm946e-s platinum_arabic_hooks.s; ld -Ttext 0x01FF8680; objcopy
HOOK_CODE = bytes.fromhex(
    "f8b586b0039004910593050017000c9ea07ab04209d12068023800f04af87a49"
    "09780843210023310870230023331878c10727d0ea79d2002168023909880fb4"
    "080000f02ef8010001bc00290ebc05d0022188431870961bf61b13e081070dd4"
    "0221084318700cb4200000f03df80cbc121a921b921b210024310a8021002431"
    "088836183604360c00960d9801900e980290039804993a00059b22f0d9fb06b0"
    "f8bd5a49401a5a498842002000d20120704710b504002088564988420dd011d8"
    "554988420ed05549411a01290ad9fff7e8ff002807d10234ede7a08803304000"
    "2418e8e7002010bdf8b504004c4d2d682000203000780007800e2d1894352d68"
    "2668023e002730884249884217d01bd84149884218d04149411a012914d901b4"
    "fff7bfff010001bc00290dd1411e28002a6f90473f18208a3f180236e3e7b088"
    "033040003618dee7208a381af8bd1fb500680068002802d00830fff7aaff2a49"
    "0870009ad2682f490b68002801d00a6002e0934200d108600fbc08f0e9fe2249"
    "0020087010bd1fb5264c24688c4202d140681e4c04810fbc1cf01ef910bd30b4"
    "204c2468844204d1c479e400a41a029d621b30bc01b41c48844601bc6047f8b5"
    "86b004001f00250023352d78ed0702d125f09cf916e0206b002802d125f078f9"
    "20630321c9017943411818220092049220220192059200220292039200236068"
    "22f0acfa06b0f8bdac88ff01fe01000002020000feff000000e00000bc250000"
    "481d1002b088ff0179ae01020000c04600000000"
)
HOOK_SYMBOLS = {
    "hook_glyph": 0x0,
    "hook_entry": 0x14E,
    "hook_cursor": 0x186,
    "hook_erase": 0x19E,
    "hook_icon": 0x1BE,
}
HOOKS = HookProgram(
    "Platinum hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="arm946e-s"
)


@dataclass(frozen=True, slots=True)
class Site:
    """A call in the game's code that goes to a hook instead of ``target``."""

    address: int
    target: int
    hook: str

    @property
    def original(self) -> bytes:
        return bl_instruction(self.address, self.target)

    def patch(self) -> bytes:
        return bl_instruction(self.address, HOOKS.symbol_address(self.hook))


SITES = (
    # RenderText: Window_CopyGlyph(window, gfx, width, height, x, y, table), r4 the printer.
    Site(0x02002692, WINDOW_COPY_GLYPH, "hook_glyph"),
    # RenderText: Text_RenderScreenIndicator(printer, x, y, icon).
    Site(0x0200252E, RENDER_SCREEN_INDICATOR, "hook_icon"),
    # PrintEntries: PrintEntry(menu, string, x, y).
    Site(0x02001702, PRINT_ENTRY, "hook_entry"),
    # PrintCursor: ColoredArrow_Print(arrow, window, x, y).
    Site(0x02001772, COLORED_ARROW_PRINT, "hook_cursor"),
    # EraseCursor: Window_FillRectWithColor(window, colour, x, y, 8, 16).
    Site(0x020017D8, WINDOW_FILL_RECT, "hook_erase"),
)

# Bytes the hooks rely on without replacing them:
ANCHORS = {
    # RenderText's glyph: the printer in r4, the font from its substruct (+0x20),
    # the pen at +0x0C and +0x0E, and the pen moved by the glyph's width;
    0x02002668: bytes.fromhex(
        "3078291c0007000f00f044fb051ca0892a1c2b1c0090e089803281330190208b291c0290"
        "12781b78606818f01dfc80352978208aa28903b008181018a081002078bd"
    ),
    # its touch-screen icon: the printer in r0;
    0x02002526: bytes.fromhex("030ca189e289201c1bf02dfb"),
    # PrintEntries: the menu in r0, an entry's string, x and y;
    0x020016F6: bytes.fromhex("2a680299281c5158019a3b1cfff765ff"),
    # PrintCursor: the arrow and the window;
    0x0200176E: bytes.fromhex("a06ae16813f071f9"),
    # EraseCursor: an 8x16 rectangle at the cursor's x;
    0x020017B8: bytes.fromhex(
        "0820009010200190217ee068a27de47d09076b432407240fe3181b04090f1b0c19f04efb"
    ),
    # the routines the hooks call;
    WINDOW_COPY_GLYPH: bytes.fromhex("f0b5ffb0c6b0051ccc980091cc90c6a9"),
    WINDOW_FILL_RECT: bytes.fromhex("38b584b00d1cc168141c0291c1791a1c"),
    WINDOW_BLIT_RECT: bytes.fromhex("30b587b006ac258a0095a58a0195258b"),
    COLORED_ARROW_PRINT: bytes.fromhex("70b584b0061c0093ff20019030680d1c"),
    PRINT_ENTRY: bytes.fromhex("70b586b00d1c061c141c002d52d02430"),
    RENDER_SCREEN_INDICATOR: bytes.fromhex("f8b586b0041c206b1f1c6568002802d1"),
    LOAD_SCREEN_INDICATOR: bytes.fromhex("38b582b0062100200902faf7f3fa0022"),
    # a window's width in tiles at +7 (Window_GetWidth);
    0x0201C294: bytes.fromhex("c0797047"),
    # the font managers at sFontWork + 0x94 (Font_TryLoadGlyph), and a
    # manager's width function at +0x70, called with the glyph's index
    # (FontManager_CalcStringWidth).
    0x02002CFC: bytes.fromhex("08b5054a8000126810189430006820f0c9fb0148006808bd"),
    0x02002D14: struct.pack("<I", FONT_WORK),
    0x02023648: bytes.fromhex("2a6f281c491e9047"),
}


@dataclass(frozen=True, slots=True)
class PlatinumArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: Gen4RtlFont
    report: dict[str, object] = field(default_factory=dict)


def source_digest(codes: Sequence[int]) -> str:
    """SHA-256 of a string's 16-bit codes, without its final ``FFFF``."""
    body = codes[: len(codes) - 1] if codes and codes[-1] == EOS else codes
    return hashlib.sha256(struct.pack(f"<{len(body)}H", *body)).hexdigest()


def verify_platinum_image(rom: bytes) -> str:
    """The accepted image's name; any other image is refused."""
    digest = hashlib.sha256(rom).hexdigest()
    if len(rom) != IMAGE_SIZE or digest not in ACCEPTED_SHA256:
        raise ClassicRetroError(
            ErrorCode.UNKNOWN_GAME_REVISION,
            f"Input is not {TITLE} with SHA-256 " + " or ".join(ACCEPTED_SHA256),
        )
    return ACCEPTED_SHA256[digest]


def _verify_code(image: NitroImage) -> Arm9Binary:
    """Every byte the overlay relies on or replaces, and room for the hooks in ITCM."""
    arm9 = Arm9Binary.from_image(image)
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    for address, original in expected.items():
        if arm9.read(address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x}"
            )
    block = arm9.autoloads()[ITCM_BLOCK]
    if (block.address, block.size, block.bss) != (ITCM_BLOCK_ADDRESS, ITCM_BLOCK_SIZE, 0):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The ITCM autoload block is not as pinned"
        )
    dummy = image.overlays()[DUMMY_OVERLAY]
    if dummy.ram + dummy.size + dummy.bss_size > HOOK_CODE_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "An ITCM overlay reaches the hooks' address"
        )
    for overlay in image.overlays():
        if overlay.id != DUMMY_OVERLAY and overlay.ram < 0x02000000:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Overlay {overlay.id} loads to ITCM"
            )
    # The hooks' literals: the routines they call and the font managers.
    for value in (WINDOW_FILL_RECT | 1, FONT_WORK):
        if struct.pack("<I", value) not in HOOK_CODE:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The hooks do not use {value:#x}"
            )
    return arm9


def _verify_intro_overlay(image: NitroImage) -> tuple[int, bytes]:
    """The intro's overlay file (id and bytes), holding the control pages' window as pinned."""
    overlay = image.overlays()[INTRO_OVERLAY]
    data = image.read(overlay.file_id)
    at = CONTROL_WINDOW - INTRO_OVERLAY_RAM
    if (
        (overlay.ram, overlay.size) != (INTRO_OVERLAY_RAM, INTRO_OVERLAY_SIZE)
        or len(data) != INTRO_OVERLAY_SIZE
        or data[at : at + len(CONTROL_WINDOW_TEMPLATE)] != CONTROL_WINDOW_TEMPLATE
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The intro's overlay differs from the pinned one"
        )
    return overlay.file_id, data


def _verify_fonts(image: NitroImage) -> tuple[bytes, dict[int, Gen4Font]]:
    """The font archive's bytes and its two fonts, as pinned."""
    archive = image.read(FONT_ARCHIVE)
    narc = Narc.read(archive)
    fonts = {}
    for index in FONTS:
        member = narc.member(archive, index)
        if hashlib.sha256(member).hexdigest() != FONT_SHA256:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Font {index} differs from the pinned font"
            )
        fonts[index] = Gen4Font.read(member)
    return archive, fonts


def _verify_banks(image: NitroImage) -> tuple[bytes, dict[int, MessageBank]]:
    """The text archive's bytes and the intro's banks, as pinned."""
    archive = image.read(MESSAGE_ARCHIVE)
    narc = Narc.read(archive)
    banks = {}
    for number, digest in BANK_SHA256.items():
        data = narc.member(archive, number)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Text bank {number} differs from the pinned USA bank",
            )
        banks[number] = MessageBank.read(data)
        if len(banks[number].strings) != BANK_STRINGS[number]:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Text bank {number} holds {len(banks[number].strings)} strings",
            )
    return archive, banks


def _verify_source(
    banks: Mapping[int, MessageBank], string: PlatinumArabicString
) -> tuple[int, ...]:
    bank = banks.get(string.bank)
    if bank is None or not 0 <= string.index < len(bank.strings):
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"{string.key}: no string")
    original = bank.strings[string.index]
    if source_digest(original) != string.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: string {string.index} differs from the pinned USA script",
        )
    if command_skeleton(original) != string.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: the original has different commands than pinned",
        )
    return original


def script_glyph_codes(strings: Sequence[PlatinumArabicString]) -> GlyphCodes:
    """The codes of every character the translated strings paint."""
    characters: set[str] = set()
    for string in strings:
        characters |= painted_characters(string.pieces)
    return gen4_glyph_codes(characters)


def encode_strings(
    encoder: Gen4ArabicEncoder,
    strings: Sequence[PlatinumArabicString],
    game_font: Gen4Font | None = None,
) -> dict[str, Gen4ArabicEncoding]:
    """Validate every translation against its original's commands and rows, and encode it."""
    encoded: dict[str, Gen4ArabicEncoding] = {}
    places: set[tuple[int, int]] = set()
    game_width = None if game_font is None else game_font.width
    for string in strings:
        if string.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"String {string.key} twice")
        if (string.bank, string.index) in places:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID,
                f"{string.key} shares string {string.index} of bank {string.bank}",
            )
        places.add((string.bank, string.index))
        validate_command_skeleton(string.source_skeleton, string.pieces)
        result = encoder.encode(string.pieces, string.window, game_width=game_width)
        _check_rows(string, result)
        encoded[string.key] = result
    return encoded


def _check_rows(string: PlatinumArabicString, result: Gen4ArabicEncoding) -> None:
    """A control page keeps the original's rows: the same count, blank where it was blank."""
    if string.fixed_rows is None:
        return
    lines = lay_out(result.codes, lambda code: 1, rows=len(string.fixed_rows), name_width=0)
    rows = tuple(bool(line.places) for line in lines)
    if rows != string.fixed_rows:
        expected = "".join("x" if row else "." for row in string.fixed_rows)
        found = "".join("x" if row else "." for row in rows)
        raise ClassicRetroError(
            ErrorCode.TEXT_BOX_OVERFLOW,
            f"{string.key}: its rows must be {expected} (x text, . blank), not {found}",
        )


def build_platinum_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    strings: tuple[PlatinumArabicString, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> PlatinumArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``strings`` and ``verify_identity`` exist for synthetic tests; a real build
    always uses the pinned script against a pinned image.
    """
    base = verify_platinum_image(rom) if verify_identity else "unverified"
    image = NitroImage(rom)
    arm9 = _verify_code(image)
    intro_file, intro = _verify_intro_overlay(image)
    font_archive, fonts = _verify_fonts(image)
    message_archive, banks = _verify_banks(image)
    strings = strings or platinum_arabic_strings(translations)
    for string in strings:
        _verify_source(banks, string)

    glyph_map = script_glyph_codes(strings)
    rtl_font = build_gen4_rtl_font(font_path, glyph_map)
    encoded = encode_strings(Gen4ArabicEncoder(glyph_map, rtl_font), strings, fonts[FONTS[0]])

    new_banks = {
        number: bank.replaced(
            {string.index: encoded[string.key].codes for string in strings if string.bank == number}
        ).build()
        for number, bank in banks.items()
    }
    new_messages = Narc.read(message_archive).rebuilt(message_archive, new_banks)
    new_fonts = Narc.read(font_archive).rebuilt(
        font_archive, {index: rtl_font.extend(fonts[index]).build() for index in FONTS}
    )

    if len(HOOK_CODE) + HOOK_CODE_ADDRESS > 0x02000000:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The hooks exceed ITCM")
    new_arm9 = arm9.patched({site.address: site.patch() for site in SITES}).with_block_grown(
        ITCM_BLOCK, bytes(HOOK_CODE_ADDRESS - ITCM_BLOCK_ADDRESS - ITCM_BLOCK_SIZE) + HOOK_CODE
    )

    target = bytearray(rom)
    move_arm9_overlay_table(target)
    replace_arm9(target, new_arm9.data)
    at = CONTROL_WINDOW - INTRO_OVERLAY_RAM
    placed = replace_files(
        target,
        {
            image.file_id(MESSAGE_ARCHIVE): new_messages,
            image.file_id(FONT_ARCHIVE): new_fonts,
            intro_file: intro[:at]
            + CONTROL_WINDOW_NARROW
            + intro[at + len(CONTROL_WINDOW_NARROW) :],
        },
    )
    stored_crc = image.header.secure_area_crc
    struct.pack_into("<H", target, SECURE_AREA_CRC, secure_area_crc(rom, bytes(target), stored_crc))
    set_header_crc(target)
    output = bytes(target)

    _verify_output(output, strings, encoded, rtl_font, fonts, new_arm9)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(TITLE, rom, output, patch),
        "base": base,
        "strings": len(strings),
        "string_lines": {key: list(result.line_widths or ()) for key, result in encoded.items()},
        "rtl_glyphs": len(rtl_font.glyphs),
        "rtl_codes": f"{min(rtl_font.glyphs):04X}..{max(rtl_font.glyphs):04X}",
        "font_size": rtl_font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_sites": len(SITES),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "hook_bytes": len(HOOK_CODE),
        "text_banks": sorted(BANK_SHA256),
        "files": {
            str(file_id): f"{start:#x}..{end:#x}" for file_id, (start, end) in placed.items()
        },
    }
    return PlatinumArabicBuild(rom=output, patch=patch, font=rtl_font, report=report)


def _verify_output(
    output: bytes,
    strings: Sequence[PlatinumArabicString],
    encoded: Mapping[str, Gen4ArabicEncoding],
    rtl_font: Gen4RtlFont,
    fonts: Mapping[int, Gen4Font],
    arm9: Arm9Binary,
) -> None:
    """Read the built image back: its code, its fonts and every translated string."""
    if not header_crc_valid(output):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header CRC is wrong")
    image = NitroImage(output)
    overlay = image.read(image.overlays()[INTRO_OVERLAY].file_id)
    at = CONTROL_WINDOW - INTRO_OVERLAY_RAM
    if overlay[at : at + len(CONTROL_WINDOW_NARROW)] != CONTROL_WINDOW_NARROW:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The control pages' window is not narrowed"
        )
    built = Arm9Binary.from_image(image)
    if built.data != arm9.data:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ARM9 does not read back")
    block = built.autoloads()[ITCM_BLOCK]
    hooks_at = built.block_data_offset(ITCM_BLOCK) + HOOK_CODE_ADDRESS - ITCM_BLOCK_ADDRESS
    if built.data[hooks_at : hooks_at + len(HOOK_CODE)] != HOOK_CODE or (
        block.address + block.size != HOOK_CODE_ADDRESS + len(HOOK_CODE)
    ):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The hooks do not read back")
    for site in SITES:
        call = built.read(site.address, 4)
        if bl_target(site.address, call) != HOOKS.symbol_address(site.hook):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{site.address:#x} does not call its hook"
            )
    archive = image.read(FONT_ARCHIVE)
    narc = Narc.read(archive)
    for index in FONTS:
        font = Gen4Font.read(narc.member(archive, index))
        if font.build() != rtl_font.extend(fonts[index]).build():
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Font {index} does not read back"
            )
    archive = image.read(MESSAGE_ARCHIVE)
    narc = Narc.read(archive)
    banks = {number: MessageBank.read(narc.member(archive, number)) for number in BANK_SHA256}
    for string in strings:
        codes = banks[string.bank].strings[string.index]
        if codes != encoded[string.key].codes:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key} does not read back"
            )
        if not any(RTL_FIRST <= code < RTL_END for code in codes):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key} holds no right-to-left glyph"
            )


def check_platinum_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every string."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    strings = platinum_arabic_strings(translations)
    glyph_map = script_glyph_codes(strings)
    font = build_gen4_rtl_font(font_path, glyph_map) if font_path is not None else None
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    encoded = encode_strings(Gen4ArabicEncoder(glyph_map, font), strings)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (
                    string.key,
                    message_preview(font, encoded[string.key].lines or (), string.window),
                )
                for string in strings
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "strings": len(strings),
        "lines_measured": font is not None,
        "encoded_codes": sum(len(result.codes) for result in encoded.values()),
        "rtl_glyphs": len(glyph_map.characters),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["widest_line"] = max(max(result.line_widths or (0,)) for result in encoded.values())
        report["name_width"] = NAME_WIDTH
    return report


# The windows ``encode_platinum_arabic_string`` lays a string out in.
WINDOWS = {
    "dialogue": DIALOGUE,
    "control": CONTROL_INFO,
    "adventure": INFO,
    "info-menu": INFO_CHOICES,
    "yes-no": YES_NO,
    "rival-menu": RIVAL_NAMES,
    "television": TELEVISION,
}


def encode_platinum_arabic_string(
    text: str, font_path: Path | None = None, *, window: str = "dialogue"
) -> dict[str, object]:
    """Encode one string in notation for one of the intro's windows; with a font, the
    width of each line. Its codes are those of its own characters."""
    pieces = parse_notation(text)
    glyph_map = gen4_glyph_codes(painted_characters(pieces))
    font = build_gen4_rtl_font(font_path, glyph_map) if font_path is not None else None
    result = Gen4ArabicEncoder(glyph_map, font).encode(pieces, WINDOWS[window])
    payload: dict[str, object] = {
        "codes": " ".join(f"{code:04X}" for code in result.codes),
        "count": len(result.codes),
    }
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = WINDOWS[window].width - WINDOWS[window].text_x
    return payload


def write_build_outputs(
    build: PlatinumArabicBuild, out_dir: Path, *, rom_name: str | None
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
    strings: tuple[PlatinumArabicString, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_platinum_image(rom)
    image = NitroImage(rom)
    _verify_code(image)
    _verify_intro_overlay(image)
    _, banks = _verify_banks(image)
    strings = strings or platinum_arabic_strings(translations)
    return {string.key: text_notation(_verify_source(banks, string)) for string in strings}


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
