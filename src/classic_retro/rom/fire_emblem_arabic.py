"""Arabic ROM overlay for *Fire Emblem: The Sacred Stones* (USA).

The fireemblem8u decompilation (https://github.com/FireEmblemUniverse/fireemblem8u)
builds this exact image and was used to find every address below, but most of
its data is still included as binary blobs, so the overlay patches the user's
image (``BE8E``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified, and
   the original messages are decoded to check the pinned script;
2. the Thumb hooks (``fire_emblem_arabic_hooks.s``), the right-to-left glyph
   table and the translated messages go into the linker padding (``0xFF``)
   at ``0x08F00000``; the image stays 16 MiB;
3. translated messages are stored uncompressed and their message table
   entries get bit 31; ``CallARM_DecompText`` jumps to a hook that copies
   such messages and decodes every other one as before;
4. four calls of the talk code become ``BL`` to ARM veneers placed over an
   unused debug routine (``0x08003ABC``); each veneer jumps to its hook;
5. the seven legend images shown before a new game are redrawn in Arabic
   (``engines.fire_emblem_legend``), LZ77-compressed into the same region,
   and their entries in ``gOpSubtitleGfxLut`` are repointed.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import arm_veneer, bl_instruction, bl_target, literal_jump
from classic_retro.engines.fire_emblem import (
    RAW_POINTER_FLAG,
    FireEmblemFont,
    FireEmblemHuffmanModel,
    FireEmblemTextBank,
    command_skeleton,
    message_notation,
    read_message,
)
from classic_retro.engines.fire_emblem_arabic import (
    ARABIC_CODE_BASE,
    BASELINE,
    CELL_HEIGHT,
    LINE_WIDTH,
    RTL_MARKER,
    USA_TALK_ADVANCES,
    FireEmblemArabicEncoder,
    FireEmblemRtlFont,
    TalkBox,
    build_fire_emblem_arabic_glyph_map,
    build_fire_emblem_rtl_font,
    fire_emblem_stream,
    font_preview,
    latin_rtl_glyphs,
    validate_command_skeleton,
)
from classic_retro.engines.fire_emblem_legend import (
    EncodedLegend,
    LegendImage,
    decode_legend_image,
    encode_legend_image,
    legend_budget,
    legend_font_size,
    legend_sheet,
    render_legend_image,
    validate_legend_lines,
)
from classic_retro.font.shaped_text import ShapedLineRenderer
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rebuild.lz77 import compress_lz77, decompress_lz77
from classic_retro.rom.fire_emblem_arabic_script import (
    FireEmblemArabicMessage,
    FireEmblemArabicSubtitle,
    fire_emblem_arabic_legend,
    fire_emblem_arabic_messages,
)

USA_SHA256 = "638cda9d9b72657220fbf7e7a500cd3b64d9686c36e8a56fca69d26d13886f2f"
USA_SIZE = 0x1000000
ROM_BASE = 0x08000000

MESSAGE_TABLE_ADDRESS = 0x0815D48C
MESSAGE_COUNT = 3404
HUFFMAN_TABLE_ADDRESS = 0x0815A72C
HUFFMAN_ROOT_POINTER = 0x0815D488
TALK_GLYPHS_ADDRESS = 0x0858F6F4
# The hooks reach the talk state through the game's own pointer to it.
TALK_STATE_POINTER = 0x0859133C
TALK_STATE_ADDRESS = 0x03000048
# The whole message buffer (sMsgString); the longest English message uses 4000.
MESSAGE_BUFFER_BYTES = 0x1000

HOOK_CODE_ADDRESS = 0x08F00000
RTL_FONT_ADDRESS = 0x08F01000
ARABIC_TEXT_ADDRESS = 0x08F08000
ARABIC_LEGEND_ADDRESS = 0x08F10000
REGION_END = 0x08F20000
FREE_FILL = 0xFF
HOOK_SOURCE = Path(__file__).with_name("fire_emblem_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi fire_emblem_arabic_hooks.s; ld -Ttext 0x08F00000; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "002802db3c4a126810474000400802780a7001300131002af9d1704702781e2a"
    "09d10130354a126810608032138834490b4313800021334a1047304a12688032"
    "1288120401d4304a1047027801309200284b9a58002a01d1fc229a5852790a60"
    "7047264a1268803213882020034201d0dc207047723a10780238c00070471f4a"
    "126880321288120401d4204a1047f0b5041c0d1c2a789200164b9e58002e01d1"
    "fc229e58fff7ddffa7787279c01b801a00d50020a070bf18154b1b689b68201c"
    "311c00f016f8a770681cf0bc02bc08470a4a126880321288120401d480787047"
    "10b58478fff7bdff001b103810bc02bc084718470010f008504100033c135908"
    "00800000458b00083d3f000881410008708e0202"
)
HOOK_SYMBOLS = {
    "hook_decomp": 0x000,
    "hook_start": 0x01C,
    "hook_width": 0x03A,
    "hook_draw": 0x07E,
    "hook_arrow": 0x0D0,
    "rtl_glyphs_pointer": 0x0F4,
}
IMAGE = ImageSpec("Fire Emblem: The Sacred Stones (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("Fire Emblem hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "fire-emblem-sacred-stones-usa-arabic-opening.bps"

# CallARM_DecompText: push {lr}; ldr r2, =0x03004150; ldr r2, [r2];
# bl _call_via_r2; pop {r0}; bx r0 (and its literal). The first eight bytes
# become ldr r2, [pc]; bx r2; .word hook_decomp.
DECODER_ADDRESS = 0x08002BA4
DECODER_ORIGINAL = bytes.fromhex("00b5034a1268cef08dfe01bc0047000050410003")

# sub_8003ABC: a debug routine nothing calls or points to. Each 16-byte veneer
# is "bx pc; nop; ldr ip, [pc]; bx ip; .word hook" (Thumb to ARM to Thumb).
VENEER_ADDRESS = 0x08003ABC
VENEER_ORIGINAL = bytes.fromhex(
    "10b50004040c0904090c02200140002901d0002021e0fff7b3ff114bd868114a"
    "8118002900da0021021c143a002a00da002240202040002804d01869814201d2"
    "0138186180202040002805d004490869824201d901300861012010bc02bc0847"
    "306e020200ffffff"
)
VENEER_BYTES = 16

# gOpSubtitleGfxLut: {LZ77 tiles, LZ77 tile map, display frames} per legend image.
LEGEND_TABLE_ADDRESS = 0x08206FE4
LEGEND_ORIGINAL = (
    (0x08AA23BC, 0x08AA5C84, 335),
    (0x08AA31B4, 0x08AA5EE0, 280),
    (0x08AA3AE4, 0x08AA6098, 120),
    (0x08AA3D7C, 0x08AA6170, 280),
    (0x08AA435C, 0x08AA629C, 330),
    (0x08AA5344, 0x08AA6548, 300),
    (0x08AA5954, 0x08AA6674, 250),
)
LEGEND_ENTRY_BYTES = 12


@dataclass(frozen=True, slots=True)
class HookSite:
    """A ``BL`` in the talk code, redirected to a veneer that jumps to a hook."""

    address: int
    original: bytes
    symbol: str
    purpose: str


HOOK_SITES = (
    HookSite(0x080069F2, bytes.fromhex("02f0a7f8"), "hook_start", "StartTalkExt: RTL marker"),
    HookSite(0x08008EFA, bytes.fromhex("fbf71ff8"), "hook_width", "GetStrTalkLen: glyph width"),
    HookSite(0x08006D08, bytes.fromhex("fdf73afa"), "hook_draw", "Talk_OnIdle: mirrored glyph"),
    HookSite(0x08007328, bytes.fromhex("fcf792fd"), "hook_arrow", "TalkInterpret: key arrow"),
)


@dataclass(frozen=True, slots=True)
class FireEmblemArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: FireEmblemRtlFont
    legend: tuple[LegendImage, ...] = ()
    report: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BuiltSubtitle:
    subtitle: FireEmblemArabicSubtitle
    image: LegendImage
    encoded: EncodedLegend


@dataclass(frozen=True, slots=True)
class BuiltLegend:
    font_size: int
    items: tuple[BuiltSubtitle, ...]


_offset = IMAGE.offset


def veneer(target: int) -> bytes:
    return arm_veneer(target)


def decoder_jump(target: int) -> bytes:
    return literal_jump(DECODER_ADDRESS, 2, target)


def source_digest(data: bytes) -> str:
    """SHA-256 of an original message's decoded bytes, terminator included."""
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _parse_bank(rom: bytes) -> FireEmblemTextBank:
    return FireEmblemTextBank.parse(
        rom,
        _offset(MESSAGE_TABLE_ADDRESS),
        MESSAGE_COUNT,
        _offset(HUFFMAN_TABLE_ADDRESS),
        _offset(HUFFMAN_ROOT_POINTER),
    )


def _verify_anchors(rom: bytes) -> tuple[FireEmblemFont, FireEmblemTextBank]:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 16 MiB")
    for address, original, purpose in (
        (DECODER_ADDRESS, DECODER_ORIGINAL, "CallARM_DecompText"),
        (VENEER_ADDRESS, VENEER_ORIGINAL, "unused debug routine"),
        *((site.address, site.original, site.purpose) for site in HOOK_SITES),
    ):
        start = _offset(address)
        if rom[start : start + len(original)] != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected code at {address:#x} ({purpose})"
            )
    for number, original in enumerate(LEGEND_ORIGINAL):
        entry = struct.unpack_from(
            "<III", rom, _offset(LEGEND_TABLE_ADDRESS) + number * LEGEND_ENTRY_BYTES
        )
        if entry != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Legend image {number} differs from the USA subtitle table",
            )
    (state,) = struct.unpack_from("<I", rom, _offset(TALK_STATE_POINTER))
    if state != TALK_STATE_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The talk state pointer differs from the USA image"
        )
    if not IMAGE.filled(rom, HOOK_CODE_ADDRESS, REGION_END, FREE_FILL):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH, "Region 0x08F00000 is not empty padding"
        )
    talk = FireEmblemFont.parse(rom, _offset(TALK_GLYPHS_ADDRESS))
    latin = {chr(code): glyph.width for code, glyph in latin_rtl_glyphs(talk).items()}
    if latin != USA_TALK_ADVANCES:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "Talk glyphs differ from the pinned USA font"
        )
    return talk, _parse_bank(rom)


def _verify_source_message(bank: FireEmblemTextBank, message: FireEmblemArabicMessage) -> None:
    if not 0 <= message.index < len(bank.messages):
        raise ClassicRetroError(
            ErrorCode.RESOURCE_OUT_OF_BOUNDS, f"Message {message.index:#x} is not in the table"
        )
    original = bank.messages[message.index]
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Message {message.index:#x} differs from the pinned USA script",
        )
    if command_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Message {message.index:#x} has different commands than pinned",
        )


def encode_translations(
    encoder: FireEmblemArabicEncoder,
    messages: tuple[FireEmblemArabicMessage, ...] | None = None,
) -> dict[int, tuple[bytes, list[int]]]:
    """Validate every translation against its original commands and encode it."""
    encoded: dict[int, tuple[bytes, list[int]]] = {}
    for message in messages or fire_emblem_arabic_messages():
        if message.index in encoded:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.index:#x} twice"
            )
        validate_command_skeleton(message.source_skeleton, message.stream)
        result = encoder.encode_message(message.stream, message.box)
        if len(result.data) > MESSAGE_BUFFER_BYTES:
            raise ClassicRetroError(
                ErrorCode.TEXT_OVERFLOW,
                f"Message {message.index:#x} needs {len(result.data)} bytes; "
                f"the message buffer holds {MESSAGE_BUFFER_BYTES}",
            )
        encoded[message.index] = (result.data, [line.width for line in result.lines])
    return encoded


def build_legend(
    font_path: Path, subtitles: tuple[FireEmblemArabicSubtitle, ...] | None = None
) -> BuiltLegend:
    """Render and encode every legend image with the user's font."""
    subtitles = subtitles or fire_emblem_arabic_legend()
    if sorted(subtitle.index for subtitle in subtitles) != list(range(len(LEGEND_ORIGINAL))):
        raise ClassicRetroError(
            ErrorCode.RESOURCE_SET_MISMATCH,
            f"The legend needs one entry per image (0..{len(LEGEND_ORIGINAL) - 1})",
        )
    size = legend_font_size(font_path)
    renderer = ShapedLineRenderer(font_path, size)
    built = []
    for subtitle in sorted(subtitles, key=lambda item: item.index):
        image = render_legend_image(renderer, subtitle.lines)
        encoded = encode_legend_image(image, legend_budget(subtitle.index))
        built.append(BuiltSubtitle(subtitle=subtitle, image=image, encoded=encoded))
    return BuiltLegend(font_size=size, items=tuple(built))


def build_fire_emblem_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[FireEmblemArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> FireEmblemArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    talk, bank = _verify_anchors(rom)
    messages = messages or fire_emblem_arabic_messages(translations)
    for message in messages:
        _verify_source_message(bank, message)
    font = build_fire_emblem_rtl_font(font_path, talk)
    font_data = font.data(RTL_FONT_ADDRESS)
    if RTL_FONT_ADDRESS + len(font_data) > ARABIC_TEXT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Glyph table exceeds its region")
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > RTL_FONT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")

    encoded = encode_translations(FireEmblemArabicEncoder(advances=font.advances()), messages)
    texts = bytearray()
    pointers: dict[int, int] = {}
    for index in sorted(encoded):
        pointers[index] = ARABIC_TEXT_ADDRESS + len(texts)
        texts += encoded[index][0]
        texts += bytes(-len(texts) % 4)
    if ARABIC_TEXT_ADDRESS + len(texts) > ARABIC_LEGEND_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic messages exceed the region")

    legend = build_legend(font_path, fire_emblem_arabic_legend(translations))
    blobs = bytearray()
    legend_pointers: list[tuple[int, int]] = []
    for item in legend.items:
        gfx = ARABIC_LEGEND_ADDRESS + len(blobs)
        blobs += compress_lz77(item.encoded.tiles)
        tile_map = ARABIC_LEGEND_ADDRESS + len(blobs)
        blobs += compress_lz77(item.encoded.tile_map)
        legend_pointers.append((gfx, tile_map))
    if ARABIC_LEGEND_ADDRESS + len(blobs) > REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Legend images exceed the region")

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(RTL_FONT_ADDRESS, font_data)
    write(ARABIC_TEXT_ADDRESS, bytes(texts))
    write(DECODER_ADDRESS, decoder_jump(HOOK_CODE_ADDRESS + HOOK_SYMBOLS["hook_decomp"]))
    for number, site in enumerate(HOOK_SITES):
        stub = VENEER_ADDRESS + number * VENEER_BYTES
        write(stub, veneer(HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol]))
        write(site.address, bl_instruction(site.address, stub))
    for index, address in pointers.items():
        write(MESSAGE_TABLE_ADDRESS + 4 * index, struct.pack("<I", address | RAW_POINTER_FLAG))
    write(ARABIC_LEGEND_ADDRESS, bytes(blobs))
    for item, (gfx, tile_map) in zip(legend.items, legend_pointers, strict=True):
        entry = LEGEND_TABLE_ADDRESS + item.subtitle.index * LEGEND_ENTRY_BYTES
        write(entry, struct.pack("<II", gfx, tile_map))

    output = bytes(target)
    replacements = {index: data for index, (data, _) in encoded.items()}
    _verify_output(output, rom, bank, replacements, font_data, legend.items)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": [f"{index:#x}" for index in sorted(replacements)],
        "message_lines": {f"{index:#x}": encoded[index][1] for index in sorted(encoded)},
        "message_boxes": {f"{message.index:#x}": str(message.box) for message in messages},
        "line_width": {str(box): width for box, width in LINE_WIDTH.items()},
        "arabic_glyphs": len(build_fire_emblem_arabic_glyph_map().characters),
        "rtl_glyphs": len(font.glyphs),
        "arabic_code_base": f"{ARABIC_CODE_BASE:#x}",
        "rtl_marker": f"{RTL_MARKER:#x}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "glyph_height": CELL_HEIGHT,
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "rtl_font_address": f"{RTL_FONT_ADDRESS:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(texts),
        "veneer_address": f"{VENEER_ADDRESS:#x}",
        "legend": [
            {
                "index": item.subtitle.index,
                "lines": list(item.subtitle.lines),
                "widths": list(item.image.widths),
                "tiles": item.encoded.tile_count,
            }
            for item in legend.items
        ],
        "legend_font_size": legend.font_size,
        "arabic_legend_address": f"{ARABIC_LEGEND_ADDRESS:#x}",
        "arabic_legend_bytes": len(blobs),
    }
    return FireEmblemArabicBuild(
        rom=output,
        patch=patch,
        font=font,
        legend=tuple(item.image for item in legend.items),
        report=report,
    )


def _verify_output(
    output: bytes,
    rom: bytes,
    bank: FireEmblemTextBank,
    replacements: dict[int, bytes],
    font_data: bytes,
    legend: tuple[BuiltSubtitle, ...],
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {_offset(address) & ~0xFFF for address in (DECODER_ADDRESS, VENEER_ADDRESS)}
    allowed |= {_offset(site.address) & ~0xFFF for site in HOOK_SITES}
    allowed |= {_offset(MESSAGE_TABLE_ADDRESS + 4 * index) & ~0xFFF for index in replacements}
    allowed |= {
        _offset(LEGEND_TABLE_ADDRESS + number * LEGEND_ENTRY_BYTES) & ~0xFFF
        for number in range(len(LEGEND_ORIGINAL))
    }
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS), _offset(REGION_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    model = FireEmblemHuffmanModel.parse(
        output, _offset(HUFFMAN_TABLE_ADDRESS), _offset(HUFFMAN_ROOT_POINTER)
    )
    pointers = struct.unpack_from(f"<{MESSAGE_COUNT}I", output, _offset(MESSAGE_TABLE_ADDRESS))
    for index, pointer in enumerate(pointers):
        if index in replacements:
            if not pointer & RAW_POINTER_FLAG:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"Message {index:#x} is not raw"
                )
            data = read_message(output, pointer, model)
            if data != replacements[index] or data[0] != RTL_MARKER:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"Message {index:#x} does not read back"
                )
        elif (
            pointer != bank.pointers[index]
            or read_message(output, pointer, model) != bank.messages[index]
        ):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Untranslated message {index:#x} changed"
            )
    start = _offset(RTL_FONT_ADDRESS)
    if output[start : start + len(font_data)] != font_data:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Glyph table was not written")
    (glyphs,) = struct.unpack_from(
        "<I", output, _offset(HOOK_CODE_ADDRESS + HOOK_SYMBOLS["rtl_glyphs_pointer"])
    )
    if glyphs != RTL_FONT_ADDRESS:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook glyph table is wrong")
    for number, site in enumerate(HOOK_SITES):
        stub = VENEER_ADDRESS + number * VENEER_BYTES
        start = _offset(site.address)
        if bl_target(site.address, output[start : start + 4]) != stub:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Call at {site.address:#x} misses its veneer"
            )
        (target,) = struct.unpack_from("<I", output, _offset(stub + 12))
        if target != HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol] | 1:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Veneer {number} misses {site.symbol}"
            )
    for item in legend:
        number = item.subtitle.index
        gfx, tile_map, frames = struct.unpack_from(
            "<III", output, _offset(LEGEND_TABLE_ADDRESS + number * LEGEND_ENTRY_BYTES)
        )
        if frames != LEGEND_ORIGINAL[number][2] or not all(
            ARABIC_LEGEND_ADDRESS <= address < REGION_END and address % 4 == 0
            for address in (gfx, tile_map)
        ):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Legend entry {number} is wrong"
            )
        tiles = decompress_lz77(output[_offset(gfx) :])
        arrangement = decompress_lz77(output[_offset(tile_map) :])
        if (
            tiles != item.encoded.tiles
            or arrangement != item.encoded.tile_map
            or decode_legend_image(tiles, arrangement) != item.image.pixels
        ):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Legend image {number} does not read back"
            )


def check_fire_emblem_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    legend_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw everything."""
    glyph_map = build_fire_emblem_arabic_glyph_map()
    subtitles = fire_emblem_arabic_legend(translations)
    for subtitle in subtitles:
        validate_legend_lines(subtitle.lines)
    font = build_fire_emblem_rtl_font(font_path) if font_path is not None else None
    if preview_path is not None:
        if font is None:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
        font_preview(font).save(preview_path)
    advances = font.advances() if font is not None else _unmeasured_advances()
    encoded = encode_translations(
        FireEmblemArabicEncoder(advances=advances, glyph_map=glyph_map),
        fire_emblem_arabic_messages(translations),
    )
    report: dict[str, object] = {
        "messages": [f"{index:#x}" for index in sorted(encoded)],
        "arabic_glyphs": len(glyph_map.characters),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(data) for data, _ in encoded.values()),
        "legend_images": len(subtitles),
    }
    if legend_preview_path is not None and font_path is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A legend preview needs --font")
    if font is not None and font_path is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["widest_line"] = {
            f"{index:#x}": max(widths) for index, (_, widths) in sorted(encoded.items())
        }
        legend = build_legend(font_path, subtitles)
        report["legend_font_size"] = legend.font_size
        report["legend_tiles"] = [item.encoded.tile_count for item in legend.items]
        report["legend_widest_line"] = [max(item.image.widths) for item in legend.items]
        if legend_preview_path is not None:
            legend_sheet([item.image for item in legend.items]).save(legend_preview_path)
    return report


def _unmeasured_advances() -> dict[int, int]:
    glyph_map = build_fire_emblem_arabic_glyph_map()
    advances = {ord(character): 0 for character in USA_TALK_ADVANCES}
    advances.update((ARABIC_CODE_BASE + slot, 0) for slot in range(len(glyph_map.characters)))
    advances[0x20] = 0
    advances[0x1F] = 0
    return advances


def encode_fire_emblem_arabic_line(
    text: str, font_path: Path | None = None, box: TalkBox = TalkBox.BUBBLE
) -> dict[str, object]:
    """Encode one logical line (bracket commands allowed); with a font, report its width."""
    font = build_fire_emblem_rtl_font(font_path) if font_path is not None else None
    advances = font.advances() if font is not None else _unmeasured_advances()
    encoder = FireEmblemArabicEncoder(advances=advances)
    result = encoder.encode_message(fire_emblem_stream(text + "[X]"), box)
    payload: dict[str, object] = {
        "bytes": result.data.hex(" "),
        "count": len(result.data),
    }
    if font is not None:
        payload["widths"] = [line.width for line in result.lines]
        payload["line_width"] = LINE_WIDTH[box]
    return payload


def write_build_outputs(
    build: FireEmblemArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    if build.legend:
        legend_path = out_dir / "arabic_legend_preview.png"
        legend_sheet(list(build.legend)).save(legend_path)
        written["legend_preview"] = str(legend_path)
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[FireEmblemArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned message, verified, in the engine's notation, by entry id.

    The legend is seven images, not text: its entries have no original to extract.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    messages = messages or fire_emblem_arabic_messages(translations)
    _, bank = _verify_anchors(rom)
    originals: dict[str, str] = {}
    for message in messages:
        _verify_source_message(bank, message)
        originals[f"message.{message.index:#x}"] = message_notation(bank.messages[message.index])
    return originals


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
