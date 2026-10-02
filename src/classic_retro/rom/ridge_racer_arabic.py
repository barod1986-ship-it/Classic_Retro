"""Arabic disc overlay for *Ridge Racer* (USA): three strings of the program.

The game is a data track and 13 audio tracks, the Redump dump's; the overlay
patches the data track (Track 01, SHA-256 below) and ships as a BPS patch of
it. The CUE sheet and the audio tracks do not change. One file changes, the
program SCUS-943.00, in place: it keeps its size and its sectors. The overlay:

1. verifies the track, the program's ISO 9660 record, every sector it reads
   (sync, header, EDC and ECC), the program's SHA-256 and header; in the
   program, every word it replaces or relies on (``SITES``, ``ANCHORS``: the
   two text routines' first words and what the hook does as they do, the
   library routines it calls, and ``CALLS``, the calls that draw the translated
   strings), the zeros the hook and its data take (``HOOK_ADDRESS`` to
   ``FREE_END``) and each translated string's room (its SHA-256);
2. draws the strings' glyphs (``engines.ridge_racer_arabic``), packs them into
   the atlas and writes the hook (``ridge_racer_arabic_hooks.s``), the fonts'
   descriptors and tables and the atlas's pixels into those zeros; puts a jump
   to the hook in place of each routine's first two words;
3. replaces each translated string in its room;
4. writes the program back to its own sectors, their subheaders kept, each with
   its EDC and ECC. Nothing moves, so the patch carries the changed sectors
   only.

The zeros after the program's data (``HOOK_ADDRESS`` to ``FREE_END``) belong
to no object: no code or data word of the program points into them, and a
mark written there stayed through the boot, the title, the menus and a race.
The glyphs go to a corner of VRAM no texture of the game takes
(``engines.ridge_racer_arabic.ATLAS_X``), uploaded once, by the first Arabic
string drawn.

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
from classic_retro.cpu.mips import NOP, j_instruction, jump_targets
from classic_retro.engines.ridge_racer import program_string, string_notation, string_room
from classic_retro.engines.ridge_racer_arabic import (
    ATLAS_TPAGE,
    ATLAS_WIDTH,
    ATLAS_X,
    ATLAS_Y,
    CELLS,
    FONTS,
    LARGE,
    SMALL,
    Atlas,
    EncodedString,
    RidgeRacerArabicEncoder,
    RrFont,
    build_atlas,
    build_ridge_racer_fonts,
    check_font_characters,
    font_preview,
    ridge_racer_glyph_codes,
    string_preview,
    strings_sheet,
    visual_text,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.cdrom import SECTOR_SIZE, IsoRecord, RawTrack, check_form1, iso_file
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.ridge_racer_arabic_script import (
    RidgeRacerString,
    ridge_racer_arabic_strings,
)

# The Redump dump's data track: "Ridge Racer (USA) (Track 01).bin".
TRACK_SHA256 = "087896cebcc2892be651a2f3e59d963daa35e2f861e25ab46e8ecfaf7c8e1c68"
TRACK_SIZE = 3_683_232
IMAGE = ImageSpec("Ridge Racer (USA), Track 01", TRACK_SHA256, TRACK_SIZE, base=0)


@dataclass(frozen=True, slots=True)
class RidgeRacerLayout:
    """The program's ISO 9660 path, first sector, size and SHA-256."""

    path: str
    lba: int
    size: int
    sha256: str


USA_LAYOUT = RidgeRacerLayout(
    "/SCUS-943.00;1", 24, 438_272,
    "bde353330bf4032d8c4b86a04dbcc78c95e6b2c5aa17dc15b79de613b52cf8c5",
)  # fmt: skip

# The program: a PS-X EXE whose code and data load at LOAD_ADDRESS, from HEADER on.
EXE_MAGIC = b"PS-X EXE"
HEADER = 0x800
LOAD_ADDRESS = 0x80010000

# The two text routines, their first two words the entries' jumps, and the
# library routines the hook calls as they do.
SMALL_ROUTINE = 0x80027ED4
LARGE_ROUTINE = 0x8003E230
LOAD_IMAGE = 0x80041750
DRAW_SYNC = 0x80041538
ADD_PRIM = 0x80043F38
SET_DRAW_MODE = 0x8004221C
# The zeros the hook and its data take: the hook, then its data.
HOOK_ADDRESS = 0x80068A00
DATA_ADDRESS = 0x80068D00
FREE_END = 0x8006AF00
# The data (the hook's DATA): the upload's flag and RECT, a descriptor for each
# font (its table, the ordering table's entry in bytes, the glyphs' texture
# page, the English cell's width, whether the palette -1 cycles), the tables
# and the atlas's pixels.
UPLOADED = DATA_ADDRESS
RECT = DATA_ADDRESS + 4
DESCRIPTORS = {SMALL: DATA_ADDRESS + 12, LARGE: DATA_ADDRESS + 24}
TABLES = {SMALL: DATA_ADDRESS + 0x30, LARGE: DATA_ADDRESS + 0x430}
PIXELS = DATA_ADDRESS + 0x840
ORDER_SLOTS = {SMALL: 2924, LARGE: 2920}
CYCLES = {SMALL: 0, LARGE: 1}
HOOK_SOURCE = Path(__file__).with_name("ridge_racer_arabic_hooks.s")

# mipsel-linux-gnu-as -march=r3000 ridge_racer_arabic_hooks.s; ld -Ttext 0x80068A00; objcopy -j .text
HOOK_CODE = bytes.fromhex(
    "0000c89000000000ffff08250200082d0400001500000000c0ffbd27b79f0008"
    "3c00bfaf0780183c98a201080c8d18270000c89000000000ffff08250200082d"
    "0400001500000000b0ffbd278ef800084c00bfaf0780183c98a20108188d1827"
    "c8ffbd273400bfaf3000b6af2c00b5af2800b4af2400b3af2000b2af1c00b1af"
    "1800b0af258080002588a0002590c0002598e00025a000030780083c008d098d"
    "000000000900201501000924008d09ad0780043c048d84240780053cd405010c"
    "4095a5244e05010c252000000000958e0000000000ffb5260200482625480000"
    "00000a910100082505004011c0500a002150550102004b91f9ff001021482b01"
    "00004a9201004b9201000c2409004c150000000008008c920000000018006c01"
    "125800002358690143580b000600001021800b0240010c242360900123608901"
    "80ff6b2521808b01801f083c0000168d0200522600005992010052263d002013"
    "c05019002150550103004b9102004c91360060112568600209008e92ffff0f24"
    "0e00c011000000000c00af15e0ff2e2706000f240200e0151b00cf010d000700"
    "127000001070000040700e0007800f3c2178ee016841ed85000000000200a105"
    "2570a0010f00ae2503710e00e001ce2580710e000f00af312170cf0100040f3c"
    "0000cfae00650f3c0400cfae0800d0a604004f81000000002178f1010a00cfa6"
    "00004f91000000000c00cfa201004f91000000000d00cfa20e00cea61000cca6"
    "1200cba621800c020400848613800f3ca40eef8d2528c00221208f00ce0f010c"
    "1400d626c3ff001000000000c1ff001021800c020600879608800f3c889fef25"
    "1000afaf2520c002252800008708010c010006240400848613800f3ca40eef8d"
    "2528c002ce0f010c21208f000c00c226801f013c000022ac3400bf8f3000b68f"
    "2c00b58f2800b48f2400b38f2000b28f1c00b18f1800b08f0800e0033800bd27"
)
HOOK_SYMBOLS = {"small_entry": 0x00, "large_entry": 0x30}
HOOKS = HookProgram(
    "Ridge Racer hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="r3000"
)
HOOK_CALLS = frozenset(
    (SMALL_ROUTINE + 8, LARGE_ROUTINE + 8, LOAD_IMAGE, DRAW_SYNC, ADD_PRIM, SET_DRAW_MODE)
)
PATCH_NAME = "ridge-racer-usa-arabic-strings.bps"


def _words(*words: int) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


SITES = (
    Site(
        SMALL_ROUTINE,
        _words(0x27BDFFC0, 0xAFBF003C),
        j_instruction(SMALL_ROUTINE, HOOKS.symbol_address("small_entry")) + NOP,
        "the small font's routine: an Arabic string to the hook",
    ),
    Site(
        LARGE_ROUTINE,
        _words(0x27BDFFB0, 0xAFBF004C),
        j_instruction(LARGE_ROUTINE, HOOKS.symbol_address("large_entry")) + NOP,
        "the large font's routine: an Arabic string to the hook",
    ),
)
# Words the hook relies on without replacing them.
ANCHORS = {
    # The small routine goes on from its third word, and draws its sprites as
    # the hook does: from the next free primitive, the palette (pal / 16 + 480)
    # << 6 | pal & 15, each added to entry 2924 of the frame's ordering table,
    # then a mode of the font's page with the routines' texture window.
    SMALL_ROUTINE + 8: _words(0xAFBE0038),
    0x80027F0C: _words(0x04E10002, 0x00E01021, 0x24E2000F, 0x00021103, 0x244201E0, 0x00021180),
    0x80027F24: _words(0x3C141F80, 0x8E940000),
    0x80027FAC: _words(0x3C048013, 0x8C840EA4, 0x26520010, 0x26940010, 0x0C010FCE, 0x24840B6C),
    0x80027FE8: _words(
        0x3C038008, 0x24639F88, 0xAFA30010, 0x02802021, 0x00002821, 0x34060001, 0x0C010887
    ),
    # The large routine likewise, to entry 2920, its palette -1 the six palettes
    # by the code less 32.
    LARGE_ROUTINE + 8: _words(0xAFBE0048),
    0x8003E274: _words(0x3C028013, 0x8C420EA4, 0x34060340, 0x34070100, 0x0C010F5D, 0x24550B68),
    0x8003E2A4: _words(0x3C1E8007, 0x27DE4168),
    0x8003E2C0: _words(0x2484FFE0),
    0x8003E2CC: _words(0x34020006, 0x0082001A),
    0x8003E374: _words(
        0x3C028008, 0x24429F88, 0xAFA20010, 0x02202021, 0x00002821, 0x34060001, 0x0C010887
    ),
    # LoadImage and DrawSync (libgpu, each naming itself to its debug print),
    # AddPrim and SetDrawMode.
    LOAD_IMAGE: _words(
        0x27BDFFE0, 0xAFB00010, 0x00808021, 0xAFB10014, 0x00A08821, 0x3C048001, 0x24841120
    ),
    0x80011120: b"LoadImage\x00",
    DRAW_SYNC: _words(0x3C028007, 0x8C4245BC, 0x27BDFFE8, 0xAFB00010, 0x00808021),
    0x800110DC: b"DrawSync(%d)...\n\x00",
    ADD_PRIM: _words(0x3C0600FF, 0x34C6FFFF, 0x3C07FF00, 0x8CA30000, 0x8C820000),
    SET_DRAW_MODE: _words(0x27BDFFE0, 0xAFB00010, 0x00808021, 0x00A02021, 0x34020002),
}
# The calls that draw the translated strings: x, y, the string, the routine and
# the palette. The menu's help line is drawn twice, the second time a pixel
# right and down in a darker palette; its x is set in the delay slot before.
CALLS = {
    "title.start": {
        0x8001C9E8: _words(0x34040060, 0x34050090, 0x3C068001, 0x24C60188, 0x0C009FB5, 0x34070064),
    },
    "menu.exit_pad": {
        0x8001E7E0: _words(0x34040058),
        # The line, then its shadow.
        0x8001E80C: _words(0x340500D0, 0x3C068001, 0x24C6027C, 0x0C009FB5, 0x34070064),
        0x8001E820: _words(0x34040059, 0x340500D1, 0x3C068001, 0x24C6027C, 0x0C009FB5, 0x3407011D),
    },
    "card.load_title": {
        0x80031968: _words(0x34040020, 0x34050020, 0x3C068001, 0x24C60614, 0x0C00F88C, 0x3407007C),
    },
}


@dataclass(frozen=True, slots=True)
class RidgeRacerArabicBuild:
    track: bytes
    patch: BpsPatch
    fonts: dict[str, RrFont]
    program: bytes
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(track: bytes) -> None:
    IMAGE.verify(track)


class _Program:
    """SCUS-943.00 by address."""

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = data

    def offset(self, address: int, length: int = 1) -> int:
        offset = HEADER + address - LOAD_ADDRESS
        if not HEADER <= offset <= len(self.data) - length:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"{address:#x} is outside SCUS-943.00"
            )
        return offset

    def read(self, address: int, length: int) -> bytes:
        offset = self.offset(address, length)
        return bytes(self.data[offset : offset + length])

    def put(self, address: int, data: bytes) -> None:
        assert isinstance(self.data, bytearray)
        offset = self.offset(address, len(data))
        self.data[offset : offset + len(data)] = data


def read_program(track: RawTrack, layout: RidgeRacerLayout) -> tuple[IsoRecord, bytes]:
    """The program, read and checked: its record and its bytes."""
    record = iso_file(track, layout.path)
    if (record.lba, record.size) != (layout.lba, layout.size):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{layout.path} is at LBA {record.lba} ({record.size} bytes), not {layout.lba}",
        )
    track.verify(record.lba, record.sectors)
    data = track.read(record.lba, record.size)
    if source_digest(data) != layout.sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{layout.path} differs from the pinned program"
        )
    _verify_program(data)
    return record, data


def _verify_program(data: bytes) -> None:
    """The header, and every word the overlay replaces or relies on."""
    load, size = struct.unpack_from("<II", data, 0x18)
    if data[:8] != EXE_MAGIC or load != LOAD_ADDRESS or HEADER + size != len(data):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "SCUS-943.00 is not the pinned PS-X EXE"
        )
    program = _Program(data)
    expected = {
        **{site.address: site.original for site in SITES},
        **ANCHORS,
        **{address: words for calls in CALLS.values() for address, words in calls.items()},
    }
    for address, original in expected.items():
        if program.read(address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected bytes at {address:#x} in the program",
            )
    if any(program.read(HOOK_ADDRESS, FREE_END - HOOK_ADDRESS)):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The room of the hook and its data is not empty"
        )
    # The hook calls the game's routines it names, and no other.
    external = {
        target
        for target in jump_targets(HOOK_ADDRESS, HOOK_CODE).values()
        if not HOOK_ADDRESS <= target < HOOK_ADDRESS + len(HOOK_CODE)
    }
    if external != HOOK_CALLS:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The hook calls " + ", ".join(f"{target:#x}" for target in sorted(external)),
        )


def _verify_source(data: bytes, entry: RidgeRacerString) -> bytes:
    """The entry's original string, its room as pinned."""
    if entry.key not in CALLS:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{entry.key}: no call of the program draws it"
        )
    program = _Program(data)
    offset = program.offset(entry.address, entry.room)
    if string_room(data, offset) != entry.room:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{entry.key}: the string's room is not as pinned"
        )
    if source_digest(program.read(entry.address, entry.room)) != entry.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{entry.key}: the original at {entry.address:#x} differs from the pinned string",
        )
    return program_string(data, offset)


# ---------------------------------------------------------------------------
# Encoding and fonts


def string_characters(entries: Sequence[RidgeRacerString]) -> dict[str, set[str]]:
    """The characters each font's strings paint."""
    used: dict[str, set[str]] = {name: set() for name in FONTS}
    for entry in entries:
        used[entry.font] |= set(visual_text(entry.notation))
    return used


def encode_strings(
    entries: Sequence[RidgeRacerString], encoder: RidgeRacerArabicEncoder
) -> dict[str, EncodedString]:
    encoded: dict[str, EncodedString] = {}
    for entry in entries:
        if entry.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"String {entry.key} twice")
        result = encoder.encode(entry.notation, entry.font, entry.mode, entry.parameter, entry.x)
        if len(result.data) > entry.room:
            raise ClassicRetroError(
                ErrorCode.TEXT_OVERFLOW,
                f"{entry.key} needs {len(result.data)} bytes; its room holds {entry.room}",
            )
        encoded[entry.key] = result
    addresses = [entry.address for entry in entries]
    if len(set(addresses)) != len(addresses):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one string")
    return encoded


def descriptor(name: str) -> bytes:
    """A font's descriptor: its table, ordering table entry, texture page, cell, cycling."""
    return struct.pack(
        "<IhHBB2x", TABLES[name], ORDER_SLOTS[name], ATLAS_TPAGE, CELLS[name].step, CYCLES[name]
    )


def hook_data(atlas: Atlas) -> bytes:
    """Everything from DATA_ADDRESS: the flag, RECT, the descriptors, tables and pixels."""
    data = bytearray(PIXELS - DATA_ADDRESS + len(atlas.pixels))
    rect = struct.pack("<4h", ATLAS_X, ATLAS_Y, ATLAS_WIDTH // 4, atlas.rows)
    data[RECT - DATA_ADDRESS : RECT - DATA_ADDRESS + len(rect)] = rect
    for name in FONTS:
        at = DESCRIPTORS[name] - DATA_ADDRESS
        data[at : at + 12] = descriptor(name)
        at = TABLES[name] - DATA_ADDRESS
        data[at : at + len(atlas.tables[name])] = atlas.tables[name]
    data[PIXELS - DATA_ADDRESS :] = atlas.pixels
    if DATA_ADDRESS + len(data) > FREE_END:
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"The glyphs need {len(atlas.pixels)} bytes; the room holds {FREE_END - PIXELS}",
        )
    return bytes(data)


def patch_program(
    data: bytes,
    atlas: Atlas,
    entries: Sequence[RidgeRacerString],
    encoded: Mapping[str, EncodedString],
) -> bytes:
    """The hook, its data and the entries' jumps in the program, and each string in its room."""
    if DATA_ADDRESS - HOOK_ADDRESS < len(HOOK_CODE):
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The hook runs into its data")
    program = _Program(bytearray(data))
    program.put(HOOK_ADDRESS, HOOK_CODE)
    program.put(DATA_ADDRESS, hook_data(atlas))
    for site in SITES:
        program.put(site.address, site.patched)
    for entry in entries:
        text = encoded[entry.key].data
        program.put(entry.address, text + bytes(entry.room - len(text)))
    return bytes(program.data)


# ---------------------------------------------------------------------------
# The build


def build_ridge_racer_arabic_image(
    track_image: bytes,
    font_path: Path,
    *,
    entries: tuple[RidgeRacerString, ...] | None = None,
    translations: TranslationSet | None = None,
    layout: RidgeRacerLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> RidgeRacerArabicBuild:
    """Build the Arabic track and its BPS patch from the original one.

    ``entries``, ``layout`` and ``verify_identity`` exist for synthetic tests; a
    real build always uses the pinned translation against the pinned image.
    """
    if verify_identity:
        verify_usa_image(track_image)
    track = RawTrack(track_image)
    record, original = read_program(track, layout)
    entries = entries or ridge_racer_arabic_strings(translations)
    for entry in entries:
        _verify_source(original, entry)

    used = string_characters(entries)
    glyph_map = ridge_racer_glyph_codes(used[SMALL] | used[LARGE])
    fonts = build_ridge_racer_fonts(font_path, glyph_map, small=used[SMALL], large=used[LARGE])
    encoded = encode_strings(entries, RidgeRacerArabicEncoder(glyph_map, fonts))
    atlas = build_atlas(fonts)
    program = patch_program(original, atlas, entries, encoded)

    output = bytearray(track_image)
    written = RawTrack(output)
    subheaders = [written.subheader(record.lba + index) for index in range(record.sectors)]
    written.write(record.lba, program, subheaders)
    result = bytes(output)
    del output, written
    changed = _verify_output(result, track_image, record, program)
    patch = create_bps(track_image, result, copy_from=())
    report: dict[str, object] = {
        **base_report(IMAGE.title, track_image, result, patch),
        "strings": {
            entry.key: {
                "font": entry.font,
                "bytes": len(encoded[entry.key].data),
                "room": entry.room,
                "width": encoded[entry.key].width,
                "pen": encoded[entry.key].pen,
            }
            for entry in entries
        },
        "arabic_glyphs": {name: len(font.glyphs) for name, font in fonts.items()},
        "arabic_codes": _code_range(glyph_map),
        "font_sizes": {name: font.font_size for name, font in fonts.items()},
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "atlas_rows": atlas.rows,
        "hook_address": f"{HOOK_ADDRESS:#x}",
        "hook_bytes": len(HOOK_CODE),
        "data_bytes": PIXELS - DATA_ADDRESS + len(atlas.pixels),
        "changed_sectors": len(changed),
        "program_sha256": source_digest(program),
    }
    return RidgeRacerArabicBuild(
        track=result, patch=patch, fonts=fonts, program=program, report=report
    )


def _code_range(glyph_map: GlyphCodes) -> str:
    codes = glyph_map.all_codes()
    return f"{min(codes):02X}..{max(codes):02X}"


def _changed_sectors(output: bytes, original: bytes) -> set[int]:
    return {
        at // SECTOR_SIZE
        for at in range(0, len(original), SECTOR_SIZE)
        if output[at : at + SECTOR_SIZE] != original[at : at + SECTOR_SIZE]
    }


def _verify_output(output: bytes, original: bytes, record: IsoRecord, program: bytes) -> set[int]:
    """Only the program's sectors changed, each one sound, and the program reads back."""
    changed = _changed_sectors(output, original)
    if any(not record.lba <= lba < record.lba + record.sectors for lba in changed):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed sectors outside the program"
        )
    track = RawTrack(output)
    for lba in sorted(changed):
        check_form1(track.sector(lba), lba)
    if len(program) != record.size or track.read(record.lba, record.size) != program:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The program does not read back")
    return changed


# ---------------------------------------------------------------------------
# Without the disc


def check_ridge_racer_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the disc; with a font, measure and draw every string."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    entries = ridge_racer_arabic_strings(translations)
    used = string_characters(entries)
    glyph_map = ridge_racer_glyph_codes(used[SMALL] | used[LARGE])
    # What each font draws is known without a font file: the pad's buttons are the small
    # font's only.
    for name in FONTS:
        check_font_characters(name, used[name])
    fonts = (
        build_ridge_racer_fonts(font_path, glyph_map, small=used[SMALL], large=used[LARGE])
        if font_path is not None
        else None
    )
    encoded = encode_strings(entries, RidgeRacerArabicEncoder(glyph_map, fonts))
    if fonts is not None and preview_path is not None:
        font_preview(fonts).save(preview_path)
    if fonts is not None and text_preview_path is not None:
        strings_sheet(
            [
                (entry.key, string_preview(encoded[entry.key], fonts[entry.font]))
                for entry in entries
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "strings": len(entries),
        "keys": [entry.key for entry in entries],
        "measured": fonts is not None,
        "encoded_bytes": {key: len(result.data) for key, result in encoded.items()},
        "arabic_glyphs": len(glyph_map.characters),
    }
    if fonts is not None:
        atlas = build_atlas(fonts)
        hook_data(atlas)
        report["font_sizes"] = {name: font.font_size for name, font in fonts.items()}
        report["widths"] = {key: result.width for key, result in encoded.items()}
        report["atlas_rows"] = atlas.rows
    return report


def encode_ridge_racer_arabic_string(
    text: str, font_name: str = SMALL, font_path: Path | None = None
) -> dict[str, object]:
    """Encode one string's glyphs in visual order; with a font, their width.

    Its codes are those of its own characters; the hook's header (mode and
    parameter) comes from the entry, and the zero ends it.
    """
    if font_name not in FONTS:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No {font_name} font")
    characters = set(visual_text(text))
    glyph_map = ridge_racer_glyph_codes(characters)
    encoder = RidgeRacerArabicEncoder(glyph_map)
    codes = encoder.codes(visual_text(text))
    payload: dict[str, object] = {
        "glyphs": codes.hex(" ").upper(),
        "count": len(codes),
        "bytes": len(codes) + 3,
    }
    if font_path is not None:
        other = LARGE if font_name == SMALL else SMALL
        fonts = build_ridge_racer_fonts(
            font_path, glyph_map, **{font_name: characters, other: set()}
        )
        payload["width"] = fonts[font_name].measure(codes)
        payload["font_size"] = fonts[font_name].font_size
    return payload


def write_build_outputs(
    build: RidgeRacerArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.fonts).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.track)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (mipsel-linux-gnu-*) and read its symbols."""
    return HOOKS.assemble(source)


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)


def extract_originals(
    track_image: bytes,
    translations: TranslationSet | None = None,
    *,
    entries: tuple[RidgeRacerString, ...] | None = None,
    layout: RidgeRacerLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(track_image)
    _, data = read_program(RawTrack(track_image), layout)
    entries = entries or ridge_racer_arabic_strings(translations)
    return {entry.key: string_notation(_verify_source(data, entry)) for entry in entries}
