"""Arabic ROM overlay for *New Super Mario Bros.* (USA): its menus and prompts.

The NSMB-Decomp/nsmb decompilation cannot build a ROM yet, so the overlay
patches the user's image (``A2DE``, SHA-256 below) and ships as a BPS patch.
It changes no code: the game draws every line as stored, centred, and the
Arabic is stored in visual order (``engines.nsmb_arabic``).

1. The input hash and every structure the overlay relies on are verified: the
   header, the ARM9 binary (its SHA-256 packed and unpacked), the NARC inside
   it that holds the font, the font (its SHA-256, its cell and the kana it
   gives up), the three message files and every translated message's original
   (its pinned hash, escapes and line ends).
2. The Arabic glyphs replace the font's kana, and the font is packed again
   into its place in the NARC (``compress_lz77_optimal``: the original was
   packed tighter than a greedy compressor can), whose file table gets the
   font's new end.
3. The ARM9 binary is packed again into its place like the original
   (``repack_blz``): the original's items stay wherever the binary did not
   change, so the patch carries the font and not the game's code. It
   shrinks: the footer that follows it moves up, the header and the module
   parameters get the new size, and the secure area's CRC follows the
   module parameters (``secure_area_crc``).
4. The three message files are rebuilt with the Arabic texts; a file that
   grows moves past the used area (``replace_files``). The header CRC comes
   last.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.nsmb import (
    CELL_HEIGHT,
    CELL_WIDTH,
    FONT_FILE,
    MESSAGE_FILES,
    PACKED_MAGIC,
    notation_skeleton,
    parse_notation,
    text_notation,
)
from classic_retro.engines.nsmb_arabic import (
    ARABIC_CODES,
    BASELINE,
    NsmbArabicEncoder,
    NsmbArabicFont,
    build_nsmb_arabic_font,
    font_preview,
    message_preview,
    messages_sheet,
    nsmb_glyph_codes,
    painted_characters,
    validate_command_skeleton,
)
from classic_retro.font.nftr import GlyphWidth, NftrFont
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.nitro import (
    ARM9_SIZE,
    SECURE_AREA_CRC,
    Narc,
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
from classic_retro.rebuild.lz77 import compress_lz77_optimal, decompress_lz77
from classic_retro.rom.nsmb_arabic_script import NsmbArabicMessage, nsmb_arabic_messages
from classic_retro.text.bmg import Bmg, Piece, encode_text

USA_SHA256 = "9f67fef1b4c73e966767f6153431ada3751dc1b0da2c70f386c14a5e3017f354"
USA_SIZE = 0x2000000
IMAGE = ImageSpec("New Super Mario Bros. (USA)", USA_SHA256, USA_SIZE, 0)
PATCH_NAME = "new-super-mario-bros-usa-arabic-menus.bps"

# The ARM9 binary: where the image keeps it and where it runs. Its module
# parameters hold, 0x14 bytes in, where its packed data ends in RAM, and 0x1C
# bytes in the SDK's two magic words.
ARM9_OFFSET = 0x4000
ARM9_RAM = 0x02000000
MODULE_PARAMS = 0xB48
PACKED_END = MODULE_PARAMS + 0x14
NITROCODE = struct.pack("<II", 0xDEC00621, 0x2106C0DE)
# The header's field for the ARM9 overlay table, which follows the ARM9 and
# the 12 bytes after it: the ARM9 may shrink, never grow.
ARM9_OVERLAY_TABLE = 0x50


@dataclass(frozen=True, slots=True)
class NsmbLayout:
    """What the overlay relies on in the image, and the SHA-256 it pins it by."""

    arm9_size: int
    arm9_stored_sha256: str
    arm9_sha256: str
    # The 12 bytes after the ARM9: the SDK's magic, the module parameters'
    # offset and a word of its own.
    arm9_footer: bytes
    # Where the NARC with the font starts in the unpacked ARM9.
    font_archive: int
    font_sha256: str
    files: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))


USA_LAYOUT = NsmbLayout(
    arm9_size=0x5EFA4,
    arm9_stored_sha256="72a43c39fa4ab0e233519d5ecbcd90813117fdd2c330cbebd864331817ff695a",
    arm9_sha256="50917f1a6b56adcc8746d2ad360a01adbe4d5ce04f2e1440035987c25a118269",
    arm9_footer=bytes.fromhex("2106c0de480b00003c290400"),
    font_archive=0x3267C,
    font_sha256="ea3f857971ba5270cc52ff56f837ab0149d1c63e31117a9521dbddb70422c537",
    files={
        "script/course.bmg": "5514c2079e3356415a0cb938e01be83b9c8061bde2da58ba4722b843ae9c2586",
        "script/data.bmg": "a4420f89e1ba38af899baba9bf450e705d9e02e30998d5168a89933c2b53b713",
        "script/game.bmg": "b7b50d973dfdf4632ed97a62456b11fe75191331b81d93b3b1e52bcc74f7fd1b",
    },
)


@dataclass(frozen=True, slots=True)
class ImageParts:
    """The verified parts of the input image the overlay reads."""

    nitro: NitroImage
    stored_arm9: bytes
    arm9: bytes
    archive: Narc
    font: NftrFont
    kana_glyphs: tuple[int, ...]
    messages: Mapping[str, Bmg]


@dataclass(frozen=True, slots=True)
class NsmbArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: NsmbArabicFont
    report: dict[str, object] = field(default_factory=dict)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mismatch(what: str) -> ClassicRetroError:
    return ClassicRetroError(
        ErrorCode.SOURCE_BASELINE_MISMATCH, f"{what} differs from the pinned USA image"
    )


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def read_parts(rom: bytes, layout: NsmbLayout = USA_LAYOUT) -> ImageParts:
    """Every part the overlay relies on, checked against ``layout`` before any change."""
    if not header_crc_valid(rom):
        raise _mismatch("The header CRC")
    header = NdsHeader.read(rom)
    footer_at = ARM9_OFFSET + layout.arm9_size
    if (
        header.arm9_offset != ARM9_OFFSET
        or header.arm9_ram != ARM9_RAM
        or header.arm9_size != layout.arm9_size
        or rom[footer_at : footer_at + len(layout.arm9_footer)] != layout.arm9_footer
        or struct.unpack_from("<I", rom, ARM9_OVERLAY_TABLE)[0]
        != footer_at + len(layout.arm9_footer)
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
    archive = Narc.read(arm9, layout.font_archive)
    start, end = archive.file_range(FONT_FILE)
    if arm9[start : start + len(PACKED_MAGIC)] != PACKED_MAGIC:
        raise _mismatch("The packed font")
    font_data = decompress_lz77(arm9[start + len(PACKED_MAGIC) : end])
    if _sha256(font_data) != layout.font_sha256:
        raise _mismatch("The font")
    font = NftrFont(font_data)
    if (font.cell_width, font.cell_height, font.bits) != (CELL_WIDTH, CELL_HEIGHT, 2):
        raise _mismatch("The font's cell")
    kana = tuple(font.codes.get(code, -1) for code in ARABIC_CODES)
    others = {glyph for code, glyph in font.codes.items() if code not in ARABIC_CODES}
    if -1 in kana or len(set(kana)) != len(kana) or others & set(kana):
        raise _mismatch("The font's kana")
    nitro = NitroImage(rom)
    messages: dict[str, Bmg] = {}
    for path in MESSAGE_FILES:
        data = nitro.read(path)
        if _sha256(data) != layout.files.get(path):
            raise _mismatch(path)
        messages[path] = Bmg.parse(data)
    return ImageParts(nitro, stored, arm9, archive, font, kana, messages)


def source_digest(pieces: Sequence[Piece]) -> str:
    """SHA-256 of an original message's UTF-16 text (without its final zero)."""
    return _sha256(encode_text(pieces))


def _verify_source(parts: ImageParts, message: NsmbArabicMessage) -> tuple[Piece, ...]:
    texts = parts.messages[message.file].texts
    if not 0 <= message.index < len(texts):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{message.key}: no message {message.index}"
        )
    original = texts[message.index]
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.index} of {message.file} differs from the "
            "pinned USA script",
        )
    if notation_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different escapes than pinned",
        )
    return original


def script_glyph_codes(messages: Sequence[NsmbArabicMessage]) -> GlyphCodes:
    """The codes of every character the translated messages draw."""
    characters: set[str] = set()
    for message in messages:
        characters |= painted_characters(message.pieces)
    return nsmb_glyph_codes(characters)


@dataclass(frozen=True, slots=True)
class NsmbEncodedMessage:
    pieces: tuple[Piece, ...]
    line_widths: tuple[int, ...]


def encode_messages(
    encoder: NsmbArabicEncoder, messages: Sequence[NsmbArabicMessage]
) -> dict[str, NsmbEncodedMessage]:
    """Validate every translation against its original's escapes and encode it."""
    encoded: dict[str, NsmbEncodedMessage] = {}
    places: set[tuple[str, int]] = set()
    for message in messages:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        if (message.file, message.index) in places:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID,
                f"{message.key} shares message {message.index} of {message.file}",
            )
        places.add((message.file, message.index))
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces, message.line_width)
        encoded[message.key] = NsmbEncodedMessage(result.pieces, result.line_widths or ())
    return encoded


def arabic_game_font(original: NftrFont, kana_glyphs: Sequence[int], font: NsmbArabicFont) -> bytes:
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


def packed_arm9(parts: ImageParts, font_data: bytes) -> tuple[bytes, bytes, int]:
    """The unpacked ARM9 with the font in place, the packed one, and the packed font's size."""
    arm9 = bytearray(parts.arm9)
    start, _ = parts.archive.file_range(FONT_FILE)
    room = parts.archive.room(FONT_FILE)
    packed_font = PACKED_MAGIC + compress_lz77_optimal(font_data)
    if len(packed_font) > room:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The packed font needs {len(packed_font)} bytes; its place holds {room}",
        )
    arm9[start : start + room] = packed_font + b"\xff" * (room - len(packed_font))
    parts.archive.set_end(arm9, FONT_FILE, start + len(packed_font))
    stored = bytearray(repack_blz(parts.stored_arm9, bytes(arm9)))
    # The end of the packed data lies in the part stored as it is.
    struct.pack_into("<I", stored, PACKED_END, ARM9_RAM + len(stored))
    struct.pack_into("<I", arm9, PACKED_END, ARM9_RAM + len(stored))
    return bytes(arm9), bytes(stored), len(packed_font)


def build_nsmb_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[NsmbArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    layout: NsmbLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> NsmbArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages``, ``layout`` and ``verify_identity`` exist for synthetic tests;
    a real build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    parts = read_parts(rom, layout)
    messages = messages or nsmb_arabic_messages(translations)
    for message in messages:
        _verify_source(parts, message)
    glyph_map = script_glyph_codes(messages)
    font = build_nsmb_arabic_font(font_path, glyph_map)
    encoded = encode_messages(NsmbArabicEncoder(glyph_map, font), messages)

    font_data = arabic_game_font(parts.font, parts.kana_glyphs, font)
    arm9, stored, packed_font = packed_arm9(parts, font_data)
    if len(stored) > layout.arm9_size:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The ARM9 packs to {len(stored):#x} bytes; its place holds {layout.arm9_size:#x}",
        )
    target = bytearray(rom)
    end = ARM9_OFFSET + layout.arm9_size + len(layout.arm9_footer)
    target[ARM9_OFFSET:end] = (
        stored
        + layout.arm9_footer
        + b"\xff" * (end - ARM9_OFFSET - len(stored) - len(layout.arm9_footer))
    )
    struct.pack_into("<I", target, ARM9_SIZE, len(stored))
    texts = _message_texts(parts, messages, encoded)
    files = {
        parts.nitro.file_id(path): parts.messages[path].with_texts(texts[path]).build()
        for path in MESSAGE_FILES
    }
    placed = replace_files(target, files)
    stored_crc = NdsHeader.read(rom).secure_area_crc
    struct.pack_into("<H", target, SECURE_AREA_CRC, secure_area_crc(rom, bytes(target), stored_crc))
    set_header_crc(target)

    output = bytes(target)
    _verify_output(output, rom, layout, parts, arm9, font_data, files, placed)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "message_lines": {key: list(entry.line_widths) for key, entry in encoded.items()},
        "line_widths": {message.key: message.line_width for message in messages},
        "arabic_glyphs": len(font.glyphs),
        "arabic_codes": f"U+{min(font.glyphs):04X}..U+{max(font.glyphs):04X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "packed_font_bytes": packed_font,
        "packed_font_room": parts.archive.room(FONT_FILE),
        "arm9_bytes": len(stored),
        "arm9_room": layout.arm9_size,
        "message_files": {
            path: f"{placed[parts.nitro.file_id(path)][0]:#x}" for path in MESSAGE_FILES
        },
    }
    return NsmbArabicBuild(rom=output, patch=patch, font=font, report=report)


def _message_texts(
    parts: ImageParts,
    messages: Sequence[NsmbArabicMessage],
    encoded: Mapping[str, NsmbEncodedMessage],
) -> dict[str, list[tuple[Piece, ...]]]:
    """Every file's texts, the translated ones replaced."""
    texts = {path: list(parts.messages[path].texts) for path in MESSAGE_FILES}
    for message in messages:
        texts[message.file][message.index] = encoded[message.key].pieces
    return texts


def _verify_output(
    output: bytes,
    rom: bytes,
    layout: NsmbLayout,
    parts: ImageParts,
    arm9: bytes,
    font_data: bytes,
    files: Mapping[int, bytes],
    placed: Mapping[int, tuple[int, int]],
) -> None:
    """Read the new image back: its header, ARM9, font, files and untouched bytes."""
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
    archive = Narc.read(unpacked, layout.font_archive)
    start, end = archive.file_range(FONT_FILE)
    if decompress_lz77(unpacked[start + len(PACKED_MAGIC) : end]) != font_data:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The font does not unpack")
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
        (ARM9_OFFSET, ARM9_OFFSET + layout.arm9_size + len(layout.arm9_footer)),
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


def check_nsmb_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every message."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    messages = nsmb_arabic_messages(translations)
    glyph_map = script_glyph_codes(messages)
    font = build_nsmb_arabic_font(font_path, glyph_map) if font_path is not None else None
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    encoded = encode_messages(NsmbArabicEncoder(glyph_map, font), messages)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (
                    message.key,
                    message_preview(font, encoded[message.key].pieces, message.line_width),
                )
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
    return report


def encode_nsmb_arabic_message(
    text: str, font_path: Path | None = None, *, line_width: int = 200
) -> dict[str, object]:
    """Encode one message in notation (its UTF-16 bytes, in visual order); with a font, the
    width of each line. Its codes are those of its own characters."""
    pieces = parse_notation(text)
    glyph_map = nsmb_glyph_codes(painted_characters(pieces))
    font = build_nsmb_arabic_font(font_path, glyph_map) if font_path is not None else None
    result = NsmbArabicEncoder(glyph_map, font).encode(pieces, line_width)
    stored = encode_text(result.pieces)
    payload: dict[str, object] = {"bytes": stored.hex(" ").upper(), "units": len(stored) // 2}
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = line_width
    return payload


def write_build_outputs(
    build: NsmbArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[NsmbArabicMessage, ...] | None = None,
    layout: NsmbLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    parts = read_parts(rom, layout)
    messages = messages or nsmb_arabic_messages(translations)
    return {message.key: text_notation(_verify_source(parts, message)) for message in messages}
