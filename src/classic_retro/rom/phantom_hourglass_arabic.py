"""Arabic ROM overlay for *The Legend of Zelda: Phantom Hourglass* (USA): its prologue.

zeldaret/ph rebuilds the game from the user's own copy and is not finished, so
the overlay patches the user's image (``AZEE``, SHA-256 below) and ships as a
BPS patch. The addresses and names are zeldaret/ph's.

1. The input hash and every structure the overlay relies on are verified: the
   header, the ARM9 binary (its SHA-256 packed and unpacked, its module
   parameters and footer, the padding before the overlay table), the glyph
   call the hook takes over and the code around it, the first bytes of every
   routine the hook calls, the routine the hook replaces, the font (its
   SHA-256, its cell and the kana it gives up), the prologue's message file
   and every translated message's original (its pinned hash, escapes and line
   ends).
2. The Arabic glyphs replace the font's kana, in place: the font keeps its
   size.
3. The hook (``phantom_hourglass_arabic_hooks.s``) is written over
   ``func_0204f358``, a routine of the C++ runtime that nothing calls, and
   the message printer's glyph call (``0x02033564``) calls it. The ARM9 is
   packed again into its place like the original (``repack_blz``): the
   original's items stay wherever the binary did not change, so the patch
   carries the hook and not the game's code. Its end moves by a few bytes,
   inside the padding before the overlay table; the header and the module
   parameters get the new size, and the secure area's CRC follows the module
   parameters (``secure_area_crc``).
4. The message file is rebuilt with the Arabic texts; a file that grows moves
   past the used area (``replace_files``). The header CRC comes last.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.arm import bl_instruction, bl_target, branch_targets
from classic_retro.engines.phantom_hourglass import (
    CELL_HEIGHT,
    CELL_WIDTH,
    DEMO_MESSAGES,
    FONT_FILE,
)
from classic_retro.engines.phantom_hourglass_arabic import (
    ARABIC_CODES,
    BASELINE,
    LINE_WIDTH,
    PhArabicEncoder,
    PhArabicFont,
    build_ph_arabic_font,
    font_preview,
    message_preview,
    messages_sheet,
    painted_characters,
    ph_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.font.nftr import GlyphWidth, NftrFont
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.nitro import (
    ARM9_OVERLAY_TABLE,
    ARM9_SIZE,
    SECURE_AREA_CRC,
    NdsHeader,
    NitroImage,
    header_crc_valid,
    replace_files,
    secure_area_crc,
    set_header_crc,
)
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.blz import decompress_blz, decompress_blz_in_place, repack_blz
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.phantom_hourglass_arabic_script import PhArabicMessage, ph_arabic_messages
from classic_retro.text.bmg import (
    Bmg,
    Piece,
    encode_text,
    notation_skeleton,
    parse_notation,
    text_notation,
)

USA_SHA256 = "2dd43288c1b7b428cbd09d9a74464b9a46fe0239eaed82849369f261678011f7"
USA_SIZE = 0x4000000
TITLE = "The Legend of Zelda: Phantom Hourglass (USA)"
IMAGE = ImageSpec(TITLE, USA_SHA256, USA_SIZE, 0)
PATCH_NAME = "zelda-phantom-hourglass-usa-arabic-prologue.bps"

# The ARM9 binary: where the image keeps it and where it runs. Its module
# parameters hold, 0x14 bytes in, where its packed data ends in RAM, and 0x1C
# bytes in the SDK's magic words.
ARM9_OFFSET = 0x4000
ARM9_RAM = 0x02000000
MODULE_PARAMS = 0xB64
PACKED_END = MODULE_PARAMS + 0x14
NITROCODE = struct.pack("<II", 0xDEC00621, 0x2106C0DE)

# The message printer's glyph call, in func_020334b4:
# DrawChar(canvas, font, x, y, colour, code), NitroSystem's
# NNS_G2dCharCanvasDrawChar (func_020296e0).
GLYPH_SITE = 0x02033564
DRAW_CHAR = 0x020296E0
GET_GLYPH_INDEX = 0x02023EA4
GET_CHAR_WIDTHS = 0x02023EEC
# func_0204f358: a routine of the C++ runtime no branch of the ARM9 or of any
# overlay reaches and no word of them points to. The hook takes its place.
HOOK_CODE_ADDRESS = 0x0204F314
HOOK_ROOM = 0xEC
HOOK_SOURCE = Path(__file__).with_name("phantom_hourglass_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm946e-s phantom_hourglass_arabic_hooks.s;
# ld -Ttext 0x0204F314; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "1f402de91c409de558309fe5033044e0bc0053e31100002a0100a0e10410a0e1"
    "da52ffeb40109fe5010050e104009d0500009005b200d0010010a0e104009de5"
    "e452ffeb0100d0e500109de5041091e508209de5812162e0002042e008208de5"
    "1f40bde8d868ffea41300000ffff0000"
)
HOOK_SYMBOLS = {"hook_glyph": 0x0}
HOOKS = HookProgram(
    "Phantom Hourglass hook",
    HOOK_SOURCE,
    HOOK_CODE_ADDRESS,
    HOOK_CODE,
    HOOK_SYMBOLS,
    cpu="arm946e-s",
    singular=True,
)


@dataclass(frozen=True, slots=True)
class PhLayout:
    """What the overlay relies on in the image, and the SHA-256 it pins it by."""

    arm9_size: int
    arm9_stored_sha256: str
    arm9_sha256: str
    # The 12 bytes after the ARM9: the SDK's magic, the module parameters'
    # offset and a word of its own.
    arm9_footer: bytes
    # Where the ARM9 overlay table starts: the ARM9 may grow up to it.
    overlay_table: int
    font_sha256: str
    messages_sha256: str
    # Bytes the hook relies on without replacing them, by address.
    anchors: Mapping[int, bytes] = field(default_factory=dict)
    # The SHA-256 of the routine the hook replaces.
    hook_room_sha256: str = ""


USA_LAYOUT = PhLayout(
    arm9_size=0x41A18,
    arm9_stored_sha256="0b00700fd8a437e0e29dec3ee1816ef9484c3e86eb3d94ba826f9a6a9b932f20",
    arm9_sha256="951476f52f74a4e316774d19065fc074cdac4ec8cc381cad757857fd61eb72e7",
    arm9_footer=bytes.fromhex("2106c0de640b000000000000"),
    overlay_table=0x45C00,
    font_sha256="edb1ddcc77d3f453564a66265f73a9029ca50916a15f4d9b81804d3060e7800e",
    messages_sha256="190c63d10f883a9ef02ce7d833d1e40ab2fb694d88e72919de650692dad11389",
    anchors={
        # func_020334b4 before the call: the colour and the code on the stack,
        # the canvas (this + 0x10), the font (+0x2C) and the pen's x and y.
        0x02033540: bytes.fromhex(
            "fe10d7e128309de5100089e202018de8f820d7e1fa60d7e12c1099e5052082e0033086e0"
        ),
        # The first bytes of the routines the hook calls.
        DRAW_CHAR: bytes.fromhex("f0412de910d04de20170a0e1bc12dde1"),
        GET_GLYPH_INDEX: bytes.fromhex("08402de9000090e5100090e5000050e3"),
        GET_CHAR_WIDTHS: bytes.fromhex("00c090e50c309ce5000053e30c00000a"),
    },
    hook_room_sha256="65b98d8428ea6ebfca33a3ae8192269754f4e7e8b65cad529f8b3c147df2ad09",
)


@dataclass(frozen=True, slots=True)
class ImageParts:
    """The verified parts of the input image the overlay reads."""

    nitro: NitroImage
    stored_arm9: bytes
    arm9: bytes
    font: NftrFont
    kana_glyphs: tuple[int, ...]
    messages: Bmg


@dataclass(frozen=True, slots=True)
class PhArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: PhArabicFont
    report: dict[str, object] = field(default_factory=dict)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mismatch(what: str) -> ClassicRetroError:
    return ClassicRetroError(
        ErrorCode.SOURCE_BASELINE_MISMATCH, f"{what} differs from the pinned USA image"
    )


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _arm9_read(arm9: bytes, address: int, length: int) -> bytes:
    return arm9[address - ARM9_RAM : address - ARM9_RAM + length]


def read_parts(rom: bytes, layout: PhLayout = USA_LAYOUT) -> ImageParts:
    """Every part the overlay relies on, checked against ``layout`` before any change."""
    if not header_crc_valid(rom):
        raise _mismatch("The header CRC")
    header = NdsHeader.read(rom)
    footer_at = ARM9_OFFSET + layout.arm9_size
    padding = rom[footer_at + len(layout.arm9_footer) : layout.overlay_table]
    if (
        header.arm9_offset != ARM9_OFFSET
        or header.arm9_ram != ARM9_RAM
        or header.arm9_size != layout.arm9_size
        or rom[footer_at : footer_at + len(layout.arm9_footer)] != layout.arm9_footer
        or struct.unpack_from("<I", rom, ARM9_OVERLAY_TABLE)[0] != layout.overlay_table
        or padding.strip(b"\xff")
    ):
        raise _mismatch("The ARM9's place")
    stored = bytes(rom[ARM9_OFFSET:footer_at])
    if _sha256(stored) != layout.arm9_stored_sha256:
        raise _mismatch("The ARM9 binary")
    arm9 = decompress_blz(stored)
    if _sha256(arm9) != layout.arm9_sha256:
        raise _mismatch("The unpacked ARM9 binary")
    if arm9[MODULE_PARAMS + 0x1C : MODULE_PARAMS + 0x24] != NITROCODE or (
        struct.unpack_from("<I", arm9, PACKED_END)[0] != ARM9_RAM + layout.arm9_size
    ):
        raise _mismatch("The ARM9's module parameters")
    site = _arm9_read(arm9, GLYPH_SITE, 4)
    if len(site) != 4 or bl_target(GLYPH_SITE, site) != DRAW_CHAR:
        raise _mismatch("The glyph call")
    for address, expected in layout.anchors.items():
        if _arm9_read(arm9, address, len(expected)) != expected:
            raise _mismatch(f"The code at {address:#x}")
    if _sha256(_arm9_read(arm9, HOOK_CODE_ADDRESS, HOOK_ROOM)) != layout.hook_room_sha256:
        raise _mismatch("The routine the hook replaces")
    nitro = NitroImage(rom)
    font_data = nitro.read(FONT_FILE)
    if _sha256(font_data) != layout.font_sha256:
        raise _mismatch("The font")
    font = NftrFont(font_data)
    if (font.cell_width, font.cell_height, font.bits) != (CELL_WIDTH, CELL_HEIGHT, 2):
        raise _mismatch("The font's cell")
    kana = tuple(font.codes.get(code, -1) for code in ARABIC_CODES)
    others = {glyph for code, glyph in font.codes.items() if code not in ARABIC_CODES}
    if -1 in kana or len(set(kana)) != len(kana) or others & set(kana):
        raise _mismatch("The font's kana")
    data = nitro.read(DEMO_MESSAGES)
    if _sha256(data) != layout.messages_sha256:
        raise _mismatch(DEMO_MESSAGES)
    return ImageParts(nitro, stored, arm9, font, kana, Bmg.parse(data))


def source_digest(pieces: Sequence[Piece]) -> str:
    """SHA-256 of an original message's UTF-16 text (without its final zero)."""
    return _sha256(encode_text(pieces))


def _verify_source(parts: ImageParts, message: PhArabicMessage) -> tuple[Piece, ...]:
    texts = parts.messages.texts
    if not 0 <= message.index < len(texts):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{message.key}: no message {message.index}"
        )
    original = texts[message.index]
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.index} of {DEMO_MESSAGES} differs from the "
            "pinned USA script",
        )
    if notation_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different escapes than pinned",
        )
    return original


def script_glyph_codes(messages: Sequence[PhArabicMessage]) -> GlyphCodes:
    """The codes of every character the translated messages draw."""
    characters: set[str] = set()
    for message in messages:
        characters |= painted_characters(message.pieces)
    return ph_glyph_codes(characters)


@dataclass(frozen=True, slots=True)
class PhEncodedMessage:
    pieces: tuple[Piece, ...]
    line_widths: tuple[int, ...]


def encode_messages(
    encoder: PhArabicEncoder, messages: Sequence[PhArabicMessage]
) -> dict[str, PhEncodedMessage]:
    """Validate every translation against its original's escapes and encode it."""
    encoded: dict[str, PhEncodedMessage] = {}
    places: set[int] = set()
    for message in messages:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        if message.index in places:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{message.key} shares message {message.index}"
            )
        places.add(message.index)
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces)
        encoded[message.key] = PhEncodedMessage(result.pieces, result.line_widths or ())
    return encoded


def arabic_game_font(original: NftrFont, kana_glyphs: Sequence[int], font: PhArabicFont) -> bytes:
    """The game's font with the Arabic glyphs in place of its kana; unused kana are blank."""
    game_font = NftrFont(original.to_bytes())
    blank = tuple((0,) * CELL_WIDTH for _ in range(CELL_HEIGHT))
    for code, glyph_index in zip(ARABIC_CODES, kana_glyphs, strict=True):
        glyph = font.glyphs.get(code)
        if glyph is None:
            game_font.set_glyph(glyph_index, blank, GlyphWidth(0, 0, 0))
        else:
            game_font.set_glyph(glyph_index, glyph.pixels, glyph.widths)
    return game_font.to_bytes()


def hooked_arm9(arm9: bytes) -> bytes:
    """The unpacked ARM9 with the hook over the unused routine and the glyph call to it."""
    if len(HOOK_CODE) > HOOK_ROOM:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The hook needs {len(HOOK_CODE)} bytes; the routine it replaces has {HOOK_ROOM}",
        )
    calls = {
        target
        for target in branch_targets(HOOK_CODE_ADDRESS, HOOK_CODE).values()
        if not HOOK_CODE_ADDRESS <= target < HOOK_CODE_ADDRESS + len(HOOK_CODE)
    }
    if calls != {DRAW_CHAR, GET_GLYPH_INDEX, GET_CHAR_WIDTHS}:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The hook calls " + ", ".join(f"{call:#x}" for call in sorted(calls)),
        )
    data = bytearray(arm9)
    start = HOOK_CODE_ADDRESS - ARM9_RAM
    data[start : start + len(HOOK_CODE)] = HOOK_CODE
    site = GLYPH_SITE - ARM9_RAM
    data[site : site + 4] = bl_instruction(GLYPH_SITE, HOOKS.symbol_address("hook_glyph"))
    return bytes(data)


def packed_arm9(parts: ImageParts, layout: PhLayout) -> tuple[bytes, bytes]:
    """The unpacked ARM9 with the hook, and the packed one, with its packed end."""
    arm9 = bytearray(hooked_arm9(parts.arm9))
    stored = bytearray(repack_blz(parts.stored_arm9, bytes(arm9)))
    room = layout.overlay_table - ARM9_OFFSET - len(layout.arm9_footer)
    if len(stored) > room:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The ARM9 packs to {len(stored):#x} bytes; its place holds {room:#x}",
        )
    # The end of the packed data lies in the part stored as it is.
    struct.pack_into("<I", stored, PACKED_END, ARM9_RAM + len(stored))
    struct.pack_into("<I", arm9, PACKED_END, ARM9_RAM + len(stored))
    return bytes(arm9), bytes(stored)


def build_ph_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[PhArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    layout: PhLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> PhArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages``, ``layout`` and ``verify_identity`` exist for synthetic tests;
    a real build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    parts = read_parts(rom, layout)
    messages = messages or ph_arabic_messages(translations)
    for message in messages:
        _verify_source(parts, message)
    glyph_map = script_glyph_codes(messages)
    font = build_ph_arabic_font(font_path, glyph_map)
    encoded = encode_messages(PhArabicEncoder(glyph_map, font), messages)

    font_data = arabic_game_font(parts.font, parts.kana_glyphs, font)
    arm9, stored = packed_arm9(parts, layout)
    target = bytearray(rom)
    end = layout.overlay_table
    target[ARM9_OFFSET:end] = (
        stored
        + layout.arm9_footer
        + b"\xff" * (end - ARM9_OFFSET - len(stored) - len(layout.arm9_footer))
    )
    struct.pack_into("<I", target, ARM9_SIZE, len(stored))
    texts = list(parts.messages.texts)
    for message in messages:
        texts[message.index] = encoded[message.key].pieces
    files = {
        parts.nitro.file_id(FONT_FILE): font_data,
        parts.nitro.file_id(DEMO_MESSAGES): parts.messages.with_texts(texts).build(),
    }
    placed = replace_files(target, files)
    stored_crc = NdsHeader.read(rom).secure_area_crc
    struct.pack_into("<H", target, SECURE_AREA_CRC, secure_area_crc(rom, bytes(target), stored_crc))
    set_header_crc(target)

    output = bytes(target)
    _verify_output(output, rom, layout, parts, arm9, files, placed)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "message_lines": {key: list(entry.line_widths) for key, entry in encoded.items()},
        "line_width": LINE_WIDTH,
        "arabic_glyphs": len(font.glyphs),
        "arabic_codes": f"U+{min(font.glyphs):04X}..U+{max(font.glyphs):04X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "hook_bytes": len(HOOK_CODE),
        "hook_room": HOOK_ROOM,
        "arm9_bytes": len(stored),
        "arm9_room": layout.overlay_table - ARM9_OFFSET - len(layout.arm9_footer),
        "message_file": f"{placed[parts.nitro.file_id(DEMO_MESSAGES)][0]:#x}",
    }
    return PhArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    rom: bytes,
    layout: PhLayout,
    parts: ImageParts,
    arm9: bytes,
    files: Mapping[int, bytes],
    placed: Mapping[int, tuple[int, int]],
) -> None:
    """Read the new image back: its header, ARM9, hook, files and untouched bytes."""
    if not header_crc_valid(output):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header CRC is wrong")
    header = NdsHeader.read(output)
    stored = output[ARM9_OFFSET : ARM9_OFFSET + header.arm9_size]
    footer = output[ARM9_OFFSET + header.arm9_size :][: len(layout.arm9_footer)]
    unpacked = decompress_blz_in_place(stored)
    if unpacked != arm9:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ARM9 does not unpack")
    if footer != layout.arm9_footer or struct.unpack_from("<I", stored, PACKED_END)[0] != (
        ARM9_RAM + header.arm9_size
    ):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ARM9's ends disagree")
    hook = HOOKS.symbol_address("hook_glyph")
    if _arm9_read(unpacked, HOOK_CODE_ADDRESS, len(HOOK_CODE)) != HOOK_CODE or (
        bl_target(GLYPH_SITE, _arm9_read(unpacked, GLYPH_SITE, 4)) != hook
    ):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The hook does not read back")
    changed = [
        index
        for index, (old, new) in enumerate(zip(parts.arm9, unpacked, strict=True))
        if old != new
    ]
    allowed = (
        range(PACKED_END, PACKED_END + 4),
        range(GLYPH_SITE - ARM9_RAM, GLYPH_SITE - ARM9_RAM + 4),
        range(HOOK_CODE_ADDRESS - ARM9_RAM, HOOK_CODE_ADDRESS - ARM9_RAM + len(HOOK_CODE)),
    )
    if any(not any(index in span for span in allowed) for index in changed):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The ARM9 changed outside the hook and its call"
        )
    nitro = NitroImage(output)
    for file_id, data in files.items():
        if nitro.file_range(file_id) != placed[file_id]:
            raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, f"File {file_id} moved")
        start, end = placed[file_id]
        if output[start:end] != data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"File {file_id} does not read back"
            )
    # Outside the header, the ARM9's place, the FAT entries and the files'
    # places (old and new), nothing changed.
    fat = parts.nitro.header.fat_offset
    written = [
        (0, 0x200),
        (ARM9_OFFSET, layout.overlay_table),
        *((fat + 8 * file_id, fat + 8 * file_id + 8) for file_id in files),
        *(parts.nitro.file_range(file_id) for file_id in files),
        *placed.values(),
        (parts.nitro.header.used_size, header.used_size + 0x100),
    ]
    position = 0
    for start, end in sorted(written):
        if output[position:start] != rom[position:start]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"The overlay changed bytes between {position:#x} and {start:#x}",
            )
        position = max(position, end)
    if output[position:] != rom[position:]:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, f"The overlay changed bytes after {position:#x}"
        )


def check_ph_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every message."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    messages = ph_arabic_messages(translations)
    glyph_map = script_glyph_codes(messages)
    font = build_ph_arabic_font(font_path, glyph_map) if font_path is not None else None
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    encoded = encode_messages(PhArabicEncoder(glyph_map, font), messages)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (message.key, message_preview(font, encoded[message.key].pieces))
                for message in messages
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "lines_measured": font is not None,
        "encoded_units": sum(len(encode_text(entry.pieces)) // 2 for entry in encoded.values()),
        "arabic_characters": len(glyph_map.characters),
        "arabic_codes": len(glyph_map.all_codes()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["widest_line"] = max(max(entry.line_widths) for entry in encoded.values())
        report["line_width"] = LINE_WIDTH
    return report


def encode_ph_arabic_message(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one message in notation (its UTF-16 bytes, in paint order); with a font, the
    width of each line. Its codes are those of its own characters."""
    pieces = parse_notation(text)
    glyph_map = ph_glyph_codes(painted_characters(pieces))
    font = build_ph_arabic_font(font_path, glyph_map) if font_path is not None else None
    result = PhArabicEncoder(glyph_map, font).encode(pieces)
    stored = encode_text(result.pieces)
    payload: dict[str, object] = {"bytes": stored.hex(" ").upper(), "units": len(stored) // 2}
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = LINE_WIDTH
    return payload


def write_build_outputs(
    build: PhArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[PhArabicMessage, ...] | None = None,
    layout: PhLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the BMG notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    parts = read_parts(rom, layout)
    messages = messages or ph_arabic_messages(translations)
    return {message.key: text_notation(_verify_source(parts, message)) for message in messages}


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Re-assemble the hook source with arm-none-eabi binutils; bytes and symbol offsets."""
    return HOOKS.assemble(source)


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
