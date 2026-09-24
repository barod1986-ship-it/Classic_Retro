"""Arabic ROM overlay for *Mario & Luigi: Superstar Saga* (USA).

The jellees/mlss decompilation matches this exact image (``A88E``, SHA-256
below) but extracts its data from the original, so the overlay patches the
user's image and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified, and
   every translated message's original is checked against its pinned hash,
   command skeleton and header (the game's measuring rule must give it);
2. the Thumb hook (``mlss_arabic_hooks.s``), the right-to-left font
   (``engines.mlss_arabic``) and the translated messages go into the zero
   padding before the Mario Bros. image at ``0x08F50000``; the image stays
   16 MiB;
3. font 1 of the printer's three font lists (empty) becomes the right-to-left
   font, so ``FE xx`` draws its glyph ``xx`` and every measuring pass counts it;
4. the glyph printer's pen-x code at ``0x0819975C`` calls ``hook_draw_x``
   through a veneer written in the code it replaces;
5. the English pointer of every translated message's group in the story text
   table is repointed to the Arabic message, whose header is computed with
   the game's rule from the right-to-left font.

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
from classic_retro.cpu.thumb import bl_veneer_patch
from classic_retro.engines.mlss import (
    GROUP_BYTES,
    HEADER_BYTES,
    ROM_BASE,
    MlssFont,
    MlssMessage,
    command_skeleton,
    measure_text,
    message_body,
    parse_notation,
)
from classic_retro.engines.mlss_arabic import (
    ARABIC_FONT_INDEX,
    BASELINE,
    CELL_HEIGHT,
    CELL_WIDTH,
    MAX_LINE_WIDTH,
    MlssArabicEncoder,
    MlssRtlFont,
    build_mlss_rtl_font,
    font_preview,
    latin_rtl_glyphs,
    message_preview,
    messages_sheet,
    validate_command_skeleton,
)
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.mlss_arabic_script import (
    STORY_TABLE,
    MlssArabicMessage,
    mlss_arabic_messages,
)

USA_SHA256 = "af9066e7eacdab919e92987db8856d038e4b75d4ed011259c893702085a886be"
USA_SIZE = 0x1000000
STORY_GROUPS = 2434

# The printer's font lists (six fonts each; the table at 0x0851F9E8, which
# FF 4n reads, points to them): font 0, then five empty slots.
FONT_LISTS: dict[int, int] = {
    0x0851F9A0: 0x0851B014,  # the speech bubbles' font
    0x0851F9B8: 0x0851C898,  # the subtitles' font (FF 41)
    0x0851F9D0: 0x0851E11C,
}
BUBBLE_FONT = 0x0851B014
GAME_FONT_HEADER = 0x23  # 8x12 cells
FONT_LIST_SLOTS = 6

# The glyph printer (0x08199624) at 0x0819975C: `ldrb r4, [r5, #12]` ...
# `mov r9, r0` computes the pen x; 0x0819977A continues with r9 and r4.
PEN_SITE = 0x0819975C
PEN_SITE_ORIGINAL = bytes.fromhex("2c7ba146ac7c102020400028" + "07d1501a")
PEN_RESUME = 0x0819977A

# Zero padding from 0x08CDD2E8 up to the Mario Bros. image at 0x08F50000.
PADDING_START = 0x08CDD2E8
PADDING_END = 0x08F50000
HOOK_CODE_ADDRESS = 0x08D00000
FONT_ADDRESS = 0x08D00100
ARABIC_TEXT_ADDRESS = 0x08D04000
REGION_END = 0x08D10000
HOOK_SOURCE = Path(__file__).with_name("mlss_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi mlss_arabic_hooks.s; ld -Ttext 0x08D00000; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "2c7bab7cd80606d4501ac30fc018401024182406240e08980a4b98420ed1e87c"
    "8008c000ab7bc018eb7bc01a001bab7c9b07db0f9940441a2406240ea146ac7c"
    "704700000001d008"
)
HOOK_SYMBOLS = {"hook_draw_x": 0x00}
IMAGE = ImageSpec("Mario & Luigi: Superstar Saga (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram(
    "MLSS hook", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, singular=True
)
PATCH_NAME = "mario-luigi-superstar-saga-usa-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class MlssArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: MlssRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset
_word = IMAGE.word


def pen_site_patch() -> bytes:
    """``bl veneer; b resume; nop``, then the veneer: ``ldr r0, =hook_draw_x; bx r0``.

    The BL leaves the return address (with its Thumb bit) in lr; r0 is free
    there (the replaced code overwrites it too).
    """
    code = bl_veneer_patch(PEN_SITE, PEN_RESUME, HOOKS.thumb_entry("hook_draw_x"))
    if len(code) != len(PEN_SITE_ORIGINAL):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Pen site patch size")
    return code


def source_digest(message: MlssMessage) -> str:
    """SHA-256 of an original message: header and text up to and including FF 0A."""
    return hashlib.sha256(message.data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> MlssFont:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 16 MiB")
    start = _offset(PEN_SITE)
    if rom[start : start + len(PEN_SITE_ORIGINAL)] != PEN_SITE_ORIGINAL:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected code at {PEN_SITE:#x} (glyph printer)"
        )
    for font_list, font in FONT_LISTS.items():
        slots = struct.unpack_from(f"<{FONT_LIST_SLOTS}I", rom, _offset(font_list))
        if slots != (font, *(0,) * (FONT_LIST_SLOTS - 1)):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Font list at {font_list:#x} differs from the USA image",
            )
        if _word(rom, font) != GAME_FONT_HEADER:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"No 8x12 font at {font:#x}"
            )
    if not IMAGE.filled(rom, PADDING_START, PADDING_END, 0):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{PADDING_START:#x}..{PADDING_END:#x} is not empty padding",
        )
    (literal,) = struct.unpack_from("<I", HOOK_CODE, len(HOOK_CODE) - 4)
    if literal != FONT_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The hook's font address differs from FONT_ADDRESS"
        )
    return MlssFont.read(rom, BUBBLE_FONT)


def _game_fonts(game_font: MlssFont) -> list[MlssFont | None]:
    return [game_font, *([None] * (FONT_LIST_SLOTS - 1))]


def _verify_source(rom: bytes, message: MlssArabicMessage, game_font: MlssFont) -> MlssMessage:
    if (message.group - STORY_TABLE) % GROUP_BYTES or not (
        STORY_TABLE <= message.group < STORY_TABLE + STORY_GROUPS * GROUP_BYTES
    ):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{message.key}: {message.group:#x} is not a story group"
        )
    if _word(rom, message.group) != message.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the group at {message.group:#x} does not lead to "
            f"{message.source_address:#x}",
        )
    try:
        original = MlssMessage.read(rom, message.source_address)
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: no message at {message.source_address:#x}",
        ) from exc
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original at {message.source_address:#x} differs from the "
            "pinned USA script",
        )
    if command_skeleton(original.body) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different commands than pinned",
        )
    layout = measure_text(original.body, _game_fonts(game_font))
    if layout.header() != (original.width_tiles, original.height_tiles):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the game's measuring rule does not give the original header",
        )
    return original


def encode_messages(
    encoder: MlssArabicEncoder, messages: tuple[MlssArabicMessage, ...] | None = None
) -> dict[str, tuple[bytes, tuple[int, ...]]]:
    """Validate every translation against its original commands and encode it.

    With a font, the result is the stored message (header, text, zero padding)
    and its line widths; without one, the text alone.
    """
    encoded: dict[str, tuple[bytes, tuple[int, ...]]] = {}
    groups: set[int] = set()
    for message in messages or mlss_arabic_messages():
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        if message.group in groups:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{message.key} shares a group with another message"
            )
        groups.add(message.group)
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces)
        if result.layout is None:
            encoded[message.key] = (result.body, ())
            continue
        width, height = result.header()
        stored = MlssMessage(width, height, result.body).stored()
        encoded[message.key] = (stored, result.layout.line_widths)
    return encoded


def build_mlss_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[MlssArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> MlssArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    game_font = _verify_anchors(rom)
    messages = messages or mlss_arabic_messages()
    for message in messages:
        _verify_source(rom, message, game_font)
    font = build_mlss_rtl_font(font_path, latin_rtl_glyphs(game_font))
    font_data = font.game_font().pack()
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > FONT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")
    if FONT_ADDRESS + len(font_data) > ARABIC_TEXT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The font exceeds its region")

    encoded = encode_messages(MlssArabicEncoder(font, base_font=game_font), messages)
    texts = bytearray()
    addresses: dict[str, int] = {}
    for message in messages:
        addresses[message.key] = ARABIC_TEXT_ADDRESS + len(texts)
        texts += encoded[message.key][0]
    if ARABIC_TEXT_ADDRESS + len(texts) > REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic messages exceed the region")

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(FONT_ADDRESS, font_data)
    write(ARABIC_TEXT_ADDRESS, bytes(texts))
    write(PEN_SITE, pen_site_patch())
    for font_list in FONT_LISTS:
        write(font_list + 4 * ARABIC_FONT_INDEX, struct.pack("<I", FONT_ADDRESS))
    for message in messages:
        write(message.group, struct.pack("<I", addresses[message.key]))

    output = bytes(target)
    _verify_output(output, rom, font, messages, encoded, addresses)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "message_lines": {message.key: list(encoded[message.key][1]) for message in messages},
        "message_headers": {message.key: list(encoded[message.key][0][:2]) for message in messages},
        "line_width_limit": MAX_LINE_WIDTH,
        "rtl_glyphs": len(font.glyphs),
        "rtl_codes": f"FE {min(font.glyphs):02X}..FE {max(font.glyphs):02X}",
        "rtl_cell": f"{CELL_WIDTH}x{CELL_HEIGHT}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "font_address": f"{FONT_ADDRESS:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(texts),
    }
    return MlssArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    rom: bytes,
    font: MlssRtlFont,
    messages: tuple[MlssArabicMessage, ...],
    encoded: dict[str, tuple[bytes, tuple[int, ...]]],
    addresses: dict[str, int],
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {_offset(PEN_SITE) & ~0xFFF, _offset(PEN_SITE + 15) & ~0xFFF}
    allowed |= {_offset(font_list) & ~0xFFF for font_list in FONT_LISTS}
    allowed |= {_offset(message.group) & ~0xFFF for message in messages}
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS) & ~0xFFF, _offset(REGION_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    start = _offset(HOOK_CODE_ADDRESS)
    if output[start : start + len(HOOK_CODE)] != HOOK_CODE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook code was not written")
    start = _offset(PEN_SITE)
    if output[start : start + len(PEN_SITE_ORIGINAL)] != pen_site_patch():
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Pen site was not patched")
    arabic = MlssFont.read(output, FONT_ADDRESS)
    if arabic != font.game_font():
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The font does not read back")
    lists: dict[int, list[MlssFont | None]] = {}
    for font_list, game_font in FONT_LISTS.items():
        slots = struct.unpack_from(f"<{FONT_LIST_SLOTS}I", output, _offset(font_list))
        expected = [game_font, *([0] * (FONT_LIST_SLOTS - 1))]
        expected[ARABIC_FONT_INDEX] = FONT_ADDRESS
        if list(slots) != expected:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Font list {font_list:#x} was not extended"
            )
        lists[font_list] = [MlssFont.read(output, slot) if slot else None for slot in slots]
    for message in messages:
        address = _word(output, message.group)
        if address != addresses[message.key]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: group not repointed"
            )
        stored = MlssMessage.read(output, address)
        if stored.stored() != encoded[message.key][0]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key} does not read back"
            )
        # The header must be what the game measures, whichever list prints it.
        for fonts in lists.values():
            if measure_text(stored.body, fonts).header() != (
                stored.width_tiles,
                stored.height_tiles,
            ):
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: header does not measure"
                )
        # Five language slots: only English changes.
        for language in range(1, GROUP_BYTES // 4):
            slot = message.group + 4 * language
            if _word(output, slot) != _word(rom, slot):
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: language {language} moved"
                )


def stored_preview(font: MlssRtlFont, stored: bytes) -> Image.Image:
    """``message_preview`` of a stored message (header, text, padding)."""
    header = (stored[0], stored[1])
    return message_preview(font, header, message_body(stored, HEADER_BYTES))


def check_mlss_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every message."""
    font = build_mlss_rtl_font(font_path) if font_path is not None else None
    if font is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    messages = mlss_arabic_messages()
    encoded = encode_messages(MlssArabicEncoder(font), messages)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [(message.key, stored_preview(font, encoded[message.key][0])) for message in messages]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(data) for data, _ in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["rtl_glyphs"] = len(font.glyphs)
        report["widest_line"] = max(max(widths) for _, widths in encoded.values())
        report["headers"] = {key: list(data[:2]) for key, (data, _) in encoded.items()}
    return report


def encode_mlss_arabic_message(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one message text in notation (ending with {FF 0A}); with a font, its header."""
    font = build_mlss_rtl_font(font_path) if font_path is not None else None
    result = MlssArabicEncoder(font).encode(parse_notation(text))
    payload: dict[str, object] = {"bytes": result.body.hex(" "), "count": len(result.body)}
    if result.layout is not None:
        payload["widths"] = list(result.layout.line_widths)
        payload["header"] = list(result.header())
        payload["line_width"] = MAX_LINE_WIDTH
    return payload


def write_build_outputs(
    build: MlssArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
