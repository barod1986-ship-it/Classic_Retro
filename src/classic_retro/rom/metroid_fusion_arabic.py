"""Arabic ROM overlay for *Metroid Fusion* (USA).

The metroidret/mf decompilation names the code below, but it cannot be
shifted and takes its data from the original, so the overlay patches the
user's image (``AMTE``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced or relied on are
   verified, and every translated monologue's original is checked against its
   pinned hash and control units, and against the English monologue list;
2. the Thumb hooks (``metroid_fusion_arabic_hooks.s``), the right-to-left
   glyph widths and sheet (``engines.metroid_fusion_arabic``) and the
   translated monologues go into the 0xFF padding at the end of the image; the
   image stays 8 MiB;
3. ``GetCharacterWidth`` jumps to its hook, and six sites in the intro's text
   routines call theirs through veneers written over Dma3Transfer_Unused1,
   since the padding is out of a BL's reach;
4. the English list's pointer to every translated monologue is repointed to
   the Arabic one. A text of the Arabic bank is what the hooks turn right to
   left.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import arm_veneer, bl_instruction, literal_jump
from classic_retro.engines.metroid_fusion import (
    END,
    ENGLISH,
    FONT_CODES,
    FONT_GRAPHICS,
    FONT_WIDTHS,
    MONOLOGUE_LANGUAGES,
    MONOLOGUES,
    ROM_BASE,
    TILE_BYTES,
    command_skeleton,
    pack_units,
    parse_notation,
    read_text,
    text_notation,
    text_units,
)
from classic_retro.engines.metroid_fusion_arabic import (
    BASELINE,
    LINE_WIDTH,
    RTL_CODE_SPAN,
    RTL_FIRST_CODE,
    SPACE,
    SPACE_WIDTH,
    STRIP,
    MfArabicEncoder,
    MfRtlFont,
    build_metroid_fusion_rtl_font,
    font_preview,
    message_preview,
    messages_sheet,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.metroid_fusion_arabic_script import (
    MONOLOGUE_LIST,
    MfArabicMessage,
    metroid_fusion_arabic_messages,
)

USA_SHA256 = "a56ce3d7f8f3f4f4d0468d421fff5dd3ee3aec99a58244377e43aae769dc3fe8"
USA_SIZE = 0x800000

# The 0xFF padding at the end of the image (from 0x0879ECC8).
HOOK_CODE_ADDRESS = 0x0879F000
RTL_WIDTHS_ADDRESS = 0x0879F800
# DrawCharacter reads glyph c at FONT_GRAPHICS + 32 * c.
FONT_ADDRESS = FONT_GRAPHICS + TILE_BYTES * RTL_FIRST_CODE
FONT_END = FONT_ADDRESS + TILE_BYTES * RTL_CODE_SPAN
ARABIC_TEXT_ADDRESS = 0x087B4000
REGION_END = 0x087B8000
PADDING = 0xFF
HOOK_SOURCE = Path(__file__).with_name("metroid_fusion_arabic_hooks.s")

# The game's code the hooks call or rely on (names from the decompilation).
GET_CHARACTER_WIDTH = 0x08079118
DRAW_CHARACTER = 0x0807913C
NONGAMEPLAY_RAM = 0x03001484
# Dma3Transfer_Unused1: 64 bytes nothing calls, near the intro's text routines
# (the SHA-256 of its code).
VENEER_AREA = 0x08098940
VENEER_AREA_SIZE = 64
VENEER_AREA_SHA256 = "db472d6b4ef115eee7a30b5b677aaad91223e1740781c1cbeedd33e6632695ba"

# arm-none-eabi-as -mcpu=arm7tdmi metroid_fusion_arabic_hooks.s; ld -Ttext 0x0879F000; objcopy
HOOK_CODE = bytes.fromhex(
    "0004000c2a49884202d22a49085c70472949401a05d32949884202d22849085c"
    "70470a20704730b4264c2468264d641b264dac4210d24c091f252c40e400e418"
    "a418e0252c1b00d50024890a8902e5086d014919072323401d4ca44630bc6047"
    "30b5720000f01df801d236218a1af80130bc02bc084730b500f013f8eb2000d2"
    "0420908130bc02bc084730b500f009f802d2e221081a00e00e30002130bc10bc"
    "2047084c2468084d641b084dac427047a0040000346257080090000000080000"
    "00f879088414000300407b08004000003d910708"
)
HOOK_SYMBOLS = {
    "hook_arrow": 0x76,
    "hook_cursor": 0x8A,
    "hook_draw": 0x26,
    "hook_fade": 0x60,
    "hook_width": 0x00,
}
IMAGE = ImageSpec("Metroid Fusion (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("Metroid Fusion hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "metroid-fusion-usa-arabic-intro.bps"


@dataclass(frozen=True, slots=True)
class Veneer:
    """A jump to a hook, in the veneer area: through ip (an ARM veneer) or a low register.

    Each veneer clobbers a register its sites do not need: ip at a call (the
    callee may clobber it), otherwise a register the code reloads after the site.
    """

    address: int
    hook: str
    register: int | None = None

    def code(self) -> bytes:
        target = HOOKS.symbol_address(self.hook)
        if self.register is None:
            return arm_veneer(target)
        return literal_jump(self.address, self.register, target)


VENEERS = {
    veneer.hook: veneer
    for veneer in (
        # At the three DrawCharacter calls: ip.
        Veneer(0x08098940, "hook_draw"),
        # In the fade, ip holds the loop's end; r3 is reloaded after the site.
        Veneer(0x08098950, "hook_fade", 3),
        Veneer(0x08098958, "hook_arrow", 1),
        Veneer(0x08098960, "hook_cursor", 1),
    )
}


@dataclass(frozen=True, slots=True)
class Site:
    """Game code replaced by a BL to a hook's veneer."""

    address: int
    original: bytes
    hook: str

    def patch(self) -> bytes:
        return bl_instruction(self.address, VENEERS[self.hook].address)


def _call_site(address: int, hook: str) -> Site:
    """A call to DrawCharacter, sent to a hook instead."""
    return Site(address, bl_instruction(address, DRAW_CHARACTER), hook)


SITES = (
    # IntroProcessText, NewFileIntroProcessAdamText, SpecialCutsceneProcessMonologue.
    _call_site(0x08098690, "hook_draw"),
    _call_site(0x080988D4, "hook_draw"),
    _call_site(0x080980CC, "hook_draw"),
    # The monologue's fade (0x08098158): `lsls r2, r6, #1; lsls r0, r7, #7`.
    Site(0x080981F8, bytes.fromhex("7200f801"), "hook_fade"),
    # NewFileIntroProcessTextCursor: `movs r0, #235; strh r0, [r2, #12]`.
    Site(0x08098C1E, bytes.fromhex("eb209081"), "hook_arrow"),
    # NewFileIntroProcessAdamTextCursor: `adds r0, #14; movs r1, #0`.
    Site(0x08090740, bytes.fromhex("0e300021"), "hook_cursor"),
)
# GetCharacterWidth's first eight bytes, replaced by a jump to hook_width
# (`push {lr}; lsls r0, r0, #16; lsrs r1, r0, #16; ldr r0, =0x49F`).
WIDTH_ENTRY = bytes.fromhex("00b50004010c0348")

# Bytes the hooks rely on without replacing them:
ANCHORS = {
    # GetCharacterWidth's last code with a width and the widths it reads;
    0x0807912C: struct.pack("<II", FONT_CODES - 1, FONT_WIDTHS),
    # DrawCharacter's glyph sheet, where the right-to-left codes are found;
    0x080791D8: struct.pack("<I", FONT_GRAPHICS),
    # the game's space, which Arabic text uses;
    FONT_WIDTHS + SPACE: bytes((SPACE_WIDTH,)),
    # the text being drawn: the intro's data (IntroProcessText,
    # SpecialCutsceneProcessMonologue, NewFileIntroProcessTextCursor);
    0x08098514: struct.pack("<I", NONGAMEPLAY_RAM),
    0x08097FF0: struct.pack("<I", NONGAMEPLAY_RAM),
    0x08098C28: struct.pack("<I", NONGAMEPLAY_RAM),
    # the strip's tiles (IntroProcessText, NewFileIntroProcessAdamText);
    0x080986E4: struct.pack("<I", 0x0600D000),
    0x08098938: struct.pack("<I", 0x0600D000),
    # a monologue page's last column (`cmp r0, #27`) and its fading map;
    0x080980D2: bytes.fromhex("1b28"),
    0x0809823C: struct.pack("<II", 0x06004842, 0x06004882),
    # the typing cursor's pen (`ldrh r0, [r3, #12]` ... `adds r0, r0, r1`);
    0x08090734: bytes.fromhex("9889084c1919c00009784018"),
    # the English monologue list.
    MONOLOGUE_LANGUAGES + 4 * ENGLISH: struct.pack("<I", MONOLOGUE_LIST),
}


@dataclass(frozen=True, slots=True)
class MfArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: MfRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset
_word = IMAGE.word


def source_digest(units: tuple[int, ...]) -> str:
    """SHA-256 of an original monologue's units, up to its final ``FF00``."""
    return hashlib.sha256(pack_units(units)).hexdigest()


def stored_text(units: tuple[int, ...]) -> bytes:
    """A text as the bank holds it: its units and ``FF00``, then zeros up to a word."""
    data = pack_units((*units, END))
    return data + bytes(-len(data) % 4)


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> None:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 8 MiB")
    expected = {
        GET_CHARACTER_WIDTH: WIDTH_ENTRY,
        **{site.address: site.original for site in SITES},
        **ANCHORS,
    }
    for address, original in expected.items():
        if IMAGE.read(rom, address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x}"
            )
    veneer_area = IMAGE.read(rom, VENEER_AREA, VENEER_AREA_SIZE)
    if hashlib.sha256(veneer_area).hexdigest() != VENEER_AREA_SHA256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected code at {VENEER_AREA:#x}"
        )
    if not IMAGE.filled(rom, HOOK_CODE_ADDRESS, REGION_END, PADDING):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{HOOK_CODE_ADDRESS:#x}..{REGION_END:#x} is not empty padding",
        )
    # The hooks' literals: the bank and its size, the widths and their codes,
    # the game's widths, the intro's data and DrawCharacter.
    for value in (
        ARABIC_TEXT_ADDRESS,
        REGION_END - ARABIC_TEXT_ADDRESS,
        RTL_WIDTHS_ADDRESS,
        RTL_FIRST_CODE,
        RTL_CODE_SPAN,
        FONT_WIDTHS,
        NONGAMEPLAY_RAM,
        DRAW_CHARACTER | 1,
    ):
        if struct.pack("<I", value) not in HOOK_CODE:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The hooks do not use {value:#x}"
            )


def _verify_source(rom: bytes, message: MfArabicMessage) -> tuple[int, ...]:
    if _word(rom, message.pointer) != message.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: monologue {message.index} is not at {message.source_address:#x}",
        )
    try:
        original = read_text(rom, message.source_address)
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: no text at {message.source_address:#x}",
        ) from exc
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original at {message.source_address:#x} differs from the "
            "pinned USA script",
        )
    if command_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different control units than pinned",
        )
    return original


def encode_messages(
    encoder: MfArabicEncoder, messages: tuple[MfArabicMessage, ...] | None = None
) -> dict[str, tuple[bytes, tuple[int, ...]]]:
    """Validate every translation against its original's control units and encode it.

    The result is each stored text and, with a font, its line widths.
    """
    encoded: dict[str, tuple[bytes, tuple[int, ...]]] = {}
    indexes: set[int] = set()
    for message in messages or metroid_fusion_arabic_messages():
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Monologue {message.key} twice")
        if message.index in indexes:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{message.key} shares monologue {message.index}"
            )
        if not 0 <= message.index < MONOLOGUES:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"{message.key}: no monologue {message.index}"
            )
        indexes.add(message.index)
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces, message.renderer)
        encoded[message.key] = (stored_text(result.units), result.line_widths or ())
    return encoded


def build_metroid_fusion_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[MfArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> MfArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    _verify_anchors(rom)
    messages = messages or metroid_fusion_arabic_messages(translations)
    for message in messages:
        _verify_source(rom, message)
    font = build_metroid_fusion_rtl_font(font_path)
    sheet = font.sheet()
    widths = font.width_table()
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > RTL_WIDTHS_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")
    if FONT_ADDRESS + len(sheet) > FONT_END or FONT_END > ARABIC_TEXT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The glyphs exceed their region")

    encoded = encode_messages(MfArabicEncoder(font), messages)
    texts = bytearray()
    addresses: dict[str, int] = {}
    for message in messages:
        addresses[message.key] = ARABIC_TEXT_ADDRESS + len(texts)
        texts += encoded[message.key][0]
    if ARABIC_TEXT_ADDRESS + len(texts) > REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic texts exceed the region")

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(RTL_WIDTHS_ADDRESS, widths)
    write(FONT_ADDRESS, sheet)
    write(ARABIC_TEXT_ADDRESS, bytes(texts))
    for veneer in VENEERS.values():
        write(veneer.address, veneer.code())
    write(GET_CHARACTER_WIDTH, _width_jump())
    for site in SITES:
        write(site.address, site.patch())
    for message in messages:
        write(message.pointer, struct.pack("<I", addresses[message.key]))

    output = bytes(target)
    _verify_output(output, rom, widths, sheet, messages, encoded, addresses)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "message_lines": {message.key: list(encoded[message.key][1]) for message in messages},
        "line_width_limit": LINE_WIDTH,
        "rtl_glyphs": len(font.glyphs),
        "rtl_codes": f"{min(font.glyphs):04X}..{max(font.glyphs):04X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_sites": len(SITES) + 1,
        "veneers": len(VENEERS),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "font_address": f"{FONT_ADDRESS:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(texts),
    }
    return MfArabicBuild(rom=output, patch=patch, font=font, report=report)


def _width_jump() -> bytes:
    return literal_jump(GET_CHARACTER_WIDTH, 1, HOOKS.symbol_address("hook_width"))


def _verify_output(
    output: bytes,
    rom: bytes,
    widths: bytes,
    sheet: bytes,
    messages: tuple[MfArabicMessage, ...],
    encoded: dict[str, tuple[bytes, tuple[int, ...]]],
    addresses: dict[str, int],
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    written = [
        (GET_CHARACTER_WIDTH, len(WIDTH_ENTRY)),
        (VENEER_AREA, VENEER_AREA_SIZE),
        *((site.address, len(site.original)) for site in SITES),
        *((message.pointer, 4) for message in messages),
    ]
    allowed = {
        _offset(address + delta) & ~0xFFF
        for address, length in written
        for delta in (0, length - 1)
    }
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS) & ~0xFFF, _offset(REGION_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    expected = {
        HOOK_CODE_ADDRESS: HOOK_CODE,
        RTL_WIDTHS_ADDRESS: widths,
        FONT_ADDRESS: sheet,
        GET_CHARACTER_WIDTH: _width_jump(),
        **{veneer.address: veneer.code() for veneer in VENEERS.values()},
        **{site.address: site.patch() for site in SITES},
    }
    for address, data in expected.items():
        if IMAGE.read(output, address, len(data)) != data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{address:#x} does not read back"
            )
    for message in messages:
        address = _word(output, message.pointer)
        if address != addresses[message.key]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: pointer not repointed"
            )
        stored = encoded[message.key][0]
        if (
            IMAGE.read(output, address, len(stored)) != stored
            or stored_text(read_text(output, address)) != stored
        ):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key} does not read back"
            )


def check_metroid_fusion_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every text."""
    font = build_metroid_fusion_rtl_font(font_path) if font_path is not None else None
    if font is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    messages = metroid_fusion_arabic_messages(translations)
    encoded = encode_messages(MfArabicEncoder(font), messages)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (message.key, stored_preview(font, encoded[message.key][0], message.renderer))
                for message in messages
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "lines_measured": font is not None,
        "encoded_units": sum(len(text_units(data, 0)) for data, _ in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["rtl_glyphs"] = len(font.glyphs)
        report["widest_line"] = max(max(widths) for _, widths in encoded.values())
    return report


def stored_preview(font: MfRtlFont, stored: bytes, renderer: str = STRIP) -> Image.Image:
    """``message_preview`` of a stored text (up to its ``FF00``)."""
    return message_preview(font, text_units(stored, 0), renderer)


def encode_metroid_fusion_arabic_message(
    text: str, font_path: Path | None = None, *, renderer: str = STRIP
) -> dict[str, object]:
    """Encode one text in notation; with a font, the width of each line."""
    font = build_metroid_fusion_rtl_font(font_path) if font_path is not None else None
    result = MfArabicEncoder(font).encode(parse_notation(text), renderer)
    payload: dict[str, object] = {
        "units": " ".join(f"{unit:04X}" for unit in result.units),
        "count": len(result.units),
    }
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = LINE_WIDTH
    return payload


def write_build_outputs(
    build: MfArabicBuild, out_dir: Path, *, rom_name: str | None
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
    messages: tuple[MfArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    messages = messages or metroid_fusion_arabic_messages(translations)
    _verify_anchors(rom)
    return {message.key: text_notation(_verify_source(rom, message)) for message in messages}


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
