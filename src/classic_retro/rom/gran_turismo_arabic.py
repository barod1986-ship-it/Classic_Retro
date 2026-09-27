"""Arabic disc overlay for *Gran Turismo* (USA) (Rev 1): three license test briefings.

The game is one data track, the Redump dump's (SHA-256 below); the overlay
patches the user's and ships as a BPS patch of it. Three of its files take
part: the race program GTMAIN.EXE, packed with PSLZ (``rebuild.pslz``), which
lays the briefings out and holds the fonts' glyph and kerning tables; the
fonts' page GAMEFONT.DAT, packed with GT-ZIP (``rebuild.gtzip``); and the text
archive MESSAGES.DAT, whose file 18 is the US English briefings
(``engines.gran_turismo``). The overlay:

1. verifies the track, the three files' ISO 9660 records, every sector it
   reads (sync, header, EDC and ECC) and each file's SHA-256 and, unpacked,
   the race program's and the page's; in the race program, every word it
   replaces or relies on (``SITES``, ``ANCHORS``, the font tables' addresses
   in the routine that selects a font, the empty kerning row of the space) and
   each translated briefing's original (its SHA-256);
2. draws the translation's glyphs (``engines.gran_turismo_arabic``) into the
   page (below) and gives their codes glyph table entries and the empty
   kerning row in fonts 1 and 2; puts the hook (``gran_turismo_arabic_hooks.s``)
   in place of the briefing layout's word loop and a call of its line step
   after the loop;
3. packs the race program and the page again in their originals' places
   (``repack_pslz``, ``repack_gtzip``): the same sizes, and the same bytes but
   around the changes; a page that does not fit its stream is packed afresh,
   as long as the file (``pack_page``);
4. replaces the translated briefings in the license file, which keeps to its
   room in the archive;
5. writes the three files back to their own sectors, their subheaders kept,
   each sector with its EDC and ECC. Nothing moves, so the patch carries the
   changed sectors only.

The glyphs go first over the glyphs of the codes they take over in fonts 1 and
2 (the Latin-1 letters, which the US game never draws): their pixels pack much
as those did, so the packed page keeps its size. Then into the page's blank
pixels: those no glyph of fonts 0 to 2 uses, off the fonts' palettes (the first
four rows' first 64 pixels) and the rows the game draws over while it runs
(from ``MOVING_ROW``), and blank in the low plane.

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
from classic_retro.cpu.mips import NOP, jal_instruction, jump_targets, pair_address
from classic_retro.engines.gran_turismo import (
    BRIEFINGS,
    LICENSE_FILE,
    briefing_bytes,
    briefing_notation,
    gt_arc_file,
    gt_arc_room,
    join_briefings,
    parse_briefing,
    parse_notation,
    replace_gt_arc_file,
    split_briefings,
)
from classic_retro.engines.gran_turismo_arabic import (
    ARABIC_CODES,
    BODY,
    CELLS,
    PAGE_ROWS,
    PAGE_WIDTH,
    ROW_BYTES,
    TITLE,
    EncodedBriefing,
    GranTurismoArabicEncoder,
    GtFont,
    briefing_characters,
    briefing_preview,
    briefings_sheet,
    build_gran_turismo_fonts,
    draw_glyph,
    font_preview,
    gran_turismo_glyph_codes,
    place_glyphs,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.cdrom import SECTOR_SIZE, IsoRecord, RawTrack, check_form1, iso_file
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rebuild.gtzip import compress_gtzip, decompress_gtzip, repack_gtzip
from classic_retro.rebuild.pslz import read_pslz, repack_pslz, unpack_in_place, unpack_pslz
from classic_retro.rom.gran_turismo_arabic_script import (
    GranTurismoBriefing,
    gran_turismo_arabic_briefings,
)

# The Redump dump: "Gran Turismo (USA) (Rev 1).bin", its only track.
TRACK_SHA256 = "e1ba7def96b7f213637fa82658b53c34a3a5f6c54df7d7e5ab9c3f53a2d41f03"
TRACK_SIZE = 693_668_304
IMAGE = ImageSpec("Gran Turismo (USA) (Rev 1)", TRACK_SHA256, TRACK_SIZE, base=0)
PAGE_SIZE = PAGE_ROWS * ROW_BYTES


@dataclass(frozen=True, slots=True)
class GtFile:
    """A file of the track: its ISO 9660 path, first sector, size and SHA-256."""

    path: str
    lba: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class GranTurismoLayout:
    """The files the overlay reads and writes, and the SHA-256 it pins what they hold by."""

    gtmain: GtFile
    gamefont: GtFile
    messages: GtFile
    # GTMAIN's image and the font page, unpacked, and the briefing layout's
    # word loop, which the hook replaces.
    image_sha256: str
    page_sha256: str
    word_loop_sha256: str


USA_LAYOUT = GranTurismoLayout(
    gtmain=GtFile(
        "/GTMAIN.EXE;1", 202, 346_112,
        "3fd17ae24e23b9c939d15951d6dafe254fa6611488327c128dfe4637f83d36f8",
    ),
    gamefont=GtFile(
        "/GAMEFONT.DAT;1", 617, 23_077,
        "b907a277f33d99392661d70ce67427a0a3f8cbc0c020589fb61f0c09590da696",
    ),
    messages=GtFile(
        "/MESSAGES.DAT;1", 629, 135_168,
        "7f5483ccb323dd9289ebfa1195870cfa064a1b5a24cfd39e846bc7cb6de2d5f2",
    ),
    image_sha256="0d7e00755c0d9234113607daf39ced3728ffe42d4e1984e32eb664f4542f48fd",
    page_sha256="4a77a46dad24a49f911047c253ce25478aeb5441f351956a82b08e2f551982d7",
    word_loop_sha256="59d010ae291d5fd060e49d2796292338700069ba1a8fc3ce45833edd94171eb2",
)  # fmt: skip

# The glyph tables (256 entries of 8 bytes) and kerning tables (a row pointer
# for each code) of fonts 0 to 2, and where the routine that selects a font
# (0x8006C770) loads each: the glyph table's lui/addiu pair, then the
# kerning table's.
FONT_TABLES = {0: 0x800999DC, 1: 0x8009BE5C, 2: 0x800A1D5C}
KERN_TABLES = {0: 0x8009BA5C, 1: 0x800A195C, 2: 0x800A725C}
FONT_SELECT = {0: 0x8006C7C0, 1: 0x8006C7D8, 2: 0x8006C7F4}
GLYPH_ENTRY = 8
KERN_ROW = 128
# The space, whose kerning row is empty: the Arabic codes take it.
SPACE = 0x20
ARABIC_FONTS = (BODY, TITLE)
# The fonts' palettes: 16 colours each on the page's first four rows.
PALETTE_ROWS = 4
PALETTE_PIXELS = 64
# The page's rows from here hold graphics the game draws over while it runs.
MOVING_ROW = 231

# The briefing layout (0x800290F8): its word loop, which the hook replaces
# (the first word, the delay slot before it, as it was), and the line's end.
HOOK_ADDRESS = 0x80029290
HOOK_END = 0x80029370
LINE_STEP_CALL = 0x80029384
MEASURE = 0x8006C8E0
DRAW_WORD = 0x8006C9F0
HOOK_SOURCE = Path(__file__).with_name("gran_turismo_arabic_hooks.s")

# mipsel-linux-gnu-as -march=r3000 gran_turismo_arabic_hooks.s; ld -Ttext 0x80029290; objcopy -j .text
HOOK_CODE = bytes.fromhex(
    "21a8c0023000a88f010004240100102538b2010c252800022588400000000992"
    "1800a68f8600292d050020152528600240010a24232853012328b1000600c624"
    "2000a48f7cb2010c25380002040062263000a98f21985100000023914800a88f"
    "21182301010063241d0048123000a3af2310b6021800c2031218000021107e00"
    "000000001a0074001220000000000000000000001a0054001210000023104400"
    "0f0000102198620200000992000000008600292d020020150000000003000825"
    "0800e00300000000000000000000000000000000000000000000000000000000"
)
HOOK_SYMBOLS = {"word": 0x04, "line_step": 0xA8}
HOOKS = HookProgram(
    "Gran Turismo hook", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="r3000",
    singular=True,
)  # fmt: skip
HOOK_CALLS = frozenset((MEASURE, DRAW_WORD))
PATCH_NAME = "gran-turismo-usa-rev1-arabic-licenses.bps"


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
        LINE_STEP_CALL,
        NOP,
        jal_instruction(LINE_STEP_CALL, HOOKS.symbol_address("line_step")),
        "the line's end: 15 rows after an Arabic line",
    ),
)
# Words the hook relies on without replacing them.
ANCHORS = {
    # The branch into the word loop, whose delay slot starts the hook.
    0x8002928C: _words(0x1040003C),
    # The loop's end, the next word, and the line's end: y += 12.
    HOOK_END: _words(0x26B50001, 0x02B2102A, 0x1440FFC6, 0x00000000, 0x8FA80018),
    LINE_STEP_CALL + 4: _words(0x2508000C, 0xAFA80018),
}


@dataclass(frozen=True, slots=True)
class GranTurismoArabicBuild:
    track: bytes
    patch: BpsPatch
    fonts: dict[int, GtFont]
    gtmain: bytes
    gamefont: bytes
    messages: bytes
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(track: bytes) -> None:
    IMAGE.verify(track)


def _file(track: RawTrack, spec: GtFile) -> tuple[IsoRecord, bytes]:
    """A file of the track, read and checked: its record and its bytes."""
    record = iso_file(track, spec.path)
    if (record.lba, record.size) != (spec.lba, spec.size):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{spec.path} is at LBA {record.lba} ({record.size} bytes), not {spec.lba}",
        )
    track.verify(record.lba, record.sectors)
    data = track.read(record.lba, record.size)
    if source_digest(data) != spec.sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{spec.path} differs from the pinned file"
        )
    return record, data


@dataclass(frozen=True, slots=True)
class GranTurismoFiles:
    """The three files, read and checked, and what the two packed ones hold."""

    records: dict[str, IsoRecord]
    gtmain: bytes
    image: bytes
    gamefont: bytes
    page: bytes
    messages: bytes
    briefings: tuple[bytes, ...]


def read_files(track: RawTrack, layout: GranTurismoLayout) -> GranTurismoFiles:
    """GTMAIN.EXE, GAMEFONT.DAT and MESSAGES.DAT, checked, and what they hold unpacked."""
    records = {}
    data = {}
    for name, spec in (
        ("gtmain", layout.gtmain),
        ("gamefont", layout.gamefont),
        ("messages", layout.messages),
    ):
        records[name], data[name] = _file(track, spec)
    image = unpack_pslz(data["gtmain"])
    if source_digest(image) != layout.image_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "GTMAIN unpacks to another program than pinned"
        )
    page = decompress_gtzip(data["gamefont"], PAGE_SIZE)
    if source_digest(page) != layout.page_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "GAMEFONT unpacks to another page than pinned"
        )
    info = read_pslz(data["gtmain"])
    _verify_image(image, info.load, layout)
    texts = split_briefings(gt_arc_file(data["messages"], LICENSE_FILE))
    return GranTurismoFiles(
        records, data["gtmain"], image, data["gamefont"], page, data["messages"], texts
    )


class _Image:
    """GTMAIN's unpacked image by address."""

    def __init__(self, data: bytes | bytearray, load: int) -> None:
        self.data = data
        self.load = load

    def offset(self, address: int, length: int = 1) -> int:
        offset = address - self.load
        if not 0 <= offset <= len(self.data) - length:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"{address:#x} is outside GTMAIN's image"
            )
        return offset

    def read(self, address: int, length: int) -> bytes:
        offset = self.offset(address, length)
        return bytes(self.data[offset : offset + length])

    def word(self, address: int) -> int:
        return int(struct.unpack("<I", self.read(address, 4))[0])

    def put(self, address: int, data: bytes) -> None:
        assert isinstance(self.data, bytearray)
        offset = self.offset(address, len(data))
        self.data[offset : offset + len(data)] = data


def _verify_image(data: bytes, load: int, layout: GranTurismoLayout) -> None:
    """Every word of GTMAIN the overlay replaces or relies on."""
    image = _Image(data, load)
    loop = image.read(HOOK_ADDRESS, HOOK_END - HOOK_ADDRESS)
    if source_digest(loop) != layout.word_loop_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "The briefing's word loop differs from the pinned one",
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    for address, original in expected.items():
        if image.read(address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x} in GTMAIN"
            )
    for font, at in FONT_SELECT.items():
        tables = (pair_address(image.read(at, 8)), pair_address(image.read(at + 8, 8)))
        if tables != (FONT_TABLES[font], KERN_TABLES[font]):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Font {font}'s tables are not where pinned"
            )
    for font in ARABIC_FONTS:
        row = image.word(KERN_TABLES[font] + 4 * SPACE)
        if image.read(row, KERN_ROW) != bytes(KERN_ROW):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Font {font}'s space has kerning"
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


def _verify_source(texts: Sequence[bytes], briefing: GranTurismoBriefing) -> bytes:
    if not 0 <= briefing.index < BRIEFINGS:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{briefing.key}: no briefing {briefing.index}"
        )
    original = texts[briefing.index]
    if source_digest(original) != briefing.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{briefing.key}: the original of {briefing.test} differs from the pinned text",
        )
    return original


# ---------------------------------------------------------------------------
# Encoding and fonts


def briefing_glyph_codes(
    briefings: Sequence[GranTurismoBriefing],
) -> tuple[GlyphCodes, set[str], set[str]]:
    """The codes of every character the briefings paint, and the title's and body's characters."""
    titles: set[str] = set()
    body: set[str] = set()
    for briefing in briefings:
        title, paragraphs = briefing_characters(briefing.title, briefing.paragraphs)
        titles |= title
        body |= paragraphs
    return gran_turismo_glyph_codes(titles | body), titles, body


def encode_briefings(
    briefings: Sequence[GranTurismoBriefing],
    encoder: GranTurismoArabicEncoder,
) -> dict[str, EncodedBriefing]:
    encoded: dict[str, EncodedBriefing] = {}
    for briefing in briefings:
        if briefing.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Briefing {briefing.key} twice")
        encoded[briefing.key] = encoder.encode(briefing.title, briefing.paragraphs)
    indexes = [briefing.index for briefing in briefings]
    if len(set(indexes)) != len(indexes):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one briefing")
    return encoded


def page_occupancy(image: bytes, load: int, page: bytes) -> tuple[list[int], list[int]]:
    """The pixels of the page the Arabic glyphs must leave alone, a bit each, row by row:
    first everything but the glyphs of the codes the Arabic takes over in fonts 1 and 2,
    then only what the game still uses (its other glyphs, the palettes, the rows it draws
    over and anything else it inked)."""
    source = _Image(image, load)
    full = (1 << PAGE_WIDTH) - 1
    kept = [0] * PAGE_ROWS
    taken = [0] * PAGE_ROWS
    for font, table in FONT_TABLES.items():
        for code in range(256):
            u, v, width, height = source.read(table + GLYPH_ENTRY * code, 4)
            mask = ((1 << width) - 1) << u & full
            rows = taken if font in ARABIC_FONTS and code in ARABIC_CODES else kept
            for y in range(v, min(PAGE_ROWS, v + height)):
                rows[y] |= mask
    for y in range(PAGE_ROWS):
        inked = 0
        for x in range(PAGE_WIDTH):
            if page[y * ROW_BYTES + x // 2] >> 4 * (x % 2) & 0x3:
                inked |= 1 << x
        kept[y] |= inked & ~taken[y]
        if y < PALETTE_ROWS:
            kept[y] |= (1 << PALETTE_PIXELS) - 1
        if y >= MOVING_ROW:
            kept[y] = full
    preferred = [full & ~(taken[y] & ~kept[y]) for y in range(PAGE_ROWS)]
    return preferred, kept


@dataclass(frozen=True, slots=True)
class GlyphPlacement:
    """Where each font's glyphs went in the page, and the pixels they took over Latin-1
    glyphs and in blank room."""

    places: dict[tuple[int, int], tuple[int, int]]
    over_latin: int
    blank: int


def place_fonts(
    image: bytes, load: int, page: bytes, fonts: Mapping[int, GtFont]
) -> GlyphPlacement:
    """Room in the page for every glyph with rows, the tallest first, over the glyphs of the
    codes they take first: their pixels pack much as those did, and the page's packed
    size stays."""
    glyphs = sorted(
        (
            (index, code, glyph)
            for index, font in fonts.items()
            for code, glyph in font.glyphs.items()
            if glyph.height
        ),
        key=lambda item: (-item[2].height, -item[2].width, item[0], item[1]),
    )
    preferred, kept = page_occupancy(image, load, page)
    sizes = [(glyph.width, glyph.height) for _, _, glyph in glyphs]
    spots = place_glyphs((preferred, kept), sizes)
    places = {(index, code): spot for (index, code, _), spot in zip(glyphs, spots, strict=True)}
    over_latin = blank = 0
    for (width, height), (u, v) in zip(sizes, spots, strict=True):
        area = width * height
        inside = all(not preferred[y] >> u & ((1 << width) - 1) for y in range(v, v + height))
        over_latin += area if inside else 0
        blank += 0 if inside else area
    return GlyphPlacement(places, over_latin, blank)


def patch_fonts(
    image: bytearray, load: int, page: bytearray, fonts: Mapping[int, GtFont]
) -> GlyphPlacement:
    """The glyphs into the page, and their entries and the empty kerning row into the tables."""
    placement = place_fonts(bytes(image), load, bytes(page), fonts)
    target = _Image(image, load)
    for index, font in fonts.items():
        cell = CELLS[index]
        empty_row = target.word(KERN_TABLES[index] + 4 * SPACE)
        for code, glyph in font.glyphs.items():
            u, v = placement.places.get((index, code), (0, 0))
            if glyph.height:
                draw_glyph(page, u, v, glyph)
            target.put(FONT_TABLES[index] + GLYPH_ENTRY * code, glyph.entry(u, v, cell.dy))
            target.put(KERN_TABLES[index] + 4 * code, struct.pack("<I", empty_row))
    return placement


def patch_code(image: bytearray, load: int) -> None:
    """The hook in place of the word loop, and the line step's call."""
    target = _Image(image, load)
    target.put(HOOK_ADDRESS, HOOK_CODE)
    for site in SITES:
        target.put(site.address, site.patched)


# ---------------------------------------------------------------------------
# The build


def build_gran_turismo_arabic_image(
    track_image: bytes,
    font_path: Path,
    *,
    briefings: tuple[GranTurismoBriefing, ...] | None = None,
    translations: TranslationSet | None = None,
    layout: GranTurismoLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> GranTurismoArabicBuild:
    """Build the Arabic track and its BPS patch from the original one.

    ``briefings``, ``layout`` and ``verify_identity`` exist for synthetic
    tests; a real build always uses the pinned translation against the pinned
    image.
    """
    if verify_identity:
        verify_usa_image(track_image)
    track = RawTrack(track_image)
    files = read_files(track, layout)
    briefings = briefings or gran_turismo_arabic_briefings(translations)
    for briefing in briefings:
        _verify_source(files.briefings, briefing)

    glyph_map, titles, body = briefing_glyph_codes(briefings)
    fonts = build_gran_turismo_fonts(font_path, glyph_map, body=body, title=titles)
    encoded = encode_briefings(briefings, GranTurismoArabicEncoder(glyph_map, fonts))

    load = read_pslz(files.gtmain).load
    image = bytearray(files.image)
    page = bytearray(files.page)
    placement = patch_fonts(image, load, page, fonts)
    patch_code(image, load)
    gtmain = repack_pslz(files.gtmain, bytes(image))
    gamefont, repacked = pack_page(files.gamefont, bytes(page))
    texts = list(files.briefings)
    for briefing in briefings:
        texts[briefing.index] = briefing_bytes(encoded[briefing.key].briefing)
    license_file = join_briefings(texts)
    messages = replace_gt_arc_file(files.messages, LICENSE_FILE, license_file)

    output = bytearray(track_image)
    written = RawTrack(output)
    for name, data in (("gtmain", gtmain), ("gamefont", gamefont), ("messages", messages)):
        record = files.records[name]
        subheaders = [written.subheader(record.lba + index) for index in range(record.sectors)]
        written.write(record.lba, data, subheaders)
    result = bytes(output)
    del output, written
    changed = _verify_output(
        result, track_image, files.records, gtmain, gamefont, messages, bytes(image), bytes(page)
    )
    patch = create_bps(track_image, result, copy_from=())
    report: dict[str, object] = {
        **base_report(IMAGE.title, track_image, result, patch),
        "briefings": {
            briefing.key: {
                "test": briefing.test,
                "title_width": _title_width(encoded[briefing.key]),
                "lines": [
                    sum(word.width for word in line.words)
                    for line in encoded[briefing.key].lines or ()
                ],
            }
            for briefing in briefings
        },
        "arabic_glyphs": {str(index): len(font.glyphs) for index, font in fonts.items()},
        "arabic_codes": f"{min(glyph_map.all_codes()):02X}..{max(glyph_map.all_codes()):02X}",
        "font_sizes": {str(index): font.font_size for index, font in fonts.items()},
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "page_pixels_over_latin_glyphs": placement.over_latin,
        "page_pixels_blank": placement.blank,
        "gamefont_repacked_in_place": repacked,
        "hook_address": f"{HOOK_ADDRESS:#x}",
        "license_file_bytes": len(license_file),
        "license_file_room": gt_arc_room(files.messages, LICENSE_FILE),
        "changed_sectors": {name: len(lbas) for name, lbas in changed.items()},
        "gtmain_sha256": source_digest(gtmain),
        "gamefont_sha256": source_digest(gamefont),
        "messages_sha256": source_digest(messages),
    }
    return GranTurismoArabicBuild(
        track=result,
        patch=patch,
        fonts=fonts,
        gtmain=gtmain,
        gamefont=gamefont,
        messages=messages,
        report=report,
    )


def pack_page(original: bytes, page: bytes) -> tuple[bytes, bool]:
    """The page packed in the original stream's place (``repack_gtzip``), and True; or,
    when it does not fit there, packed afresh, as long as the original file, and False."""
    try:
        return repack_gtzip(original, page), True
    except ClassicRetroError:
        stream = compress_gtzip(page)
    if len(stream) > len(original):
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The font page packs into {len(stream)} bytes; GAMEFONT.DAT holds {len(original)}",
        )
    return stream + bytes(len(original) - len(stream)), False


def _title_width(encoded: EncodedBriefing) -> int:
    return 0 if encoded.title is None else encoded.title.width


def _changed_sectors(output: bytes, original: bytes) -> set[int]:
    """The sectors that differ, found a MiB at a time."""
    changed: set[int] = set()
    chunk = 448 * SECTOR_SIZE
    for start in range(0, len(original), chunk):
        if output[start : start + chunk] == original[start : start + chunk]:
            continue
        for at in range(start, min(start + chunk, len(original)), SECTOR_SIZE):
            if output[at : at + SECTOR_SIZE] != original[at : at + SECTOR_SIZE]:
                changed.add(at // SECTOR_SIZE)
    return changed


def _verify_output(
    output: bytes,
    original: bytes,
    records: Mapping[str, IsoRecord],
    gtmain: bytes,
    gamefont: bytes,
    messages: bytes,
    image: bytes,
    page: bytes,
) -> dict[str, set[int]]:
    """Only the three files' sectors changed, each one sound, and every file reads back
    and unpacks to what was built; the changed sectors by file."""
    changed = _changed_sectors(output, original)
    by_file = {
        name: {lba for lba in changed if record.lba <= lba < record.lba + record.sectors}
        for name, record in records.items()
    }
    if set().union(*by_file.values()) != changed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed sectors outside its files"
        )
    track = RawTrack(output)
    for lba in sorted(changed):
        check_form1(track.sector(lba), lba)
    for name, data in (("gtmain", gtmain), ("gamefont", gamefont), ("messages", messages)):
        record = records[name]
        if len(data) != record.size or track.read(record.lba, record.size) != data:
            raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, f"{name} does not read back")
    if unpack_in_place(gtmain) != image or decompress_gtzip(gamefont, PAGE_SIZE) != page:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "A repacked file does not unpack to what was built"
        )
    split_briefings(gt_arc_file(messages, LICENSE_FILE))
    return by_file


# ---------------------------------------------------------------------------
# Without the disc


def check_gran_turismo_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the disc; with a font, lay out and draw every briefing."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    briefings = gran_turismo_arabic_briefings(translations)
    glyph_map, titles, body = briefing_glyph_codes(briefings)
    fonts = (
        build_gran_turismo_fonts(font_path, glyph_map, body=body, title=titles)
        if font_path is not None
        else None
    )
    encoded = encode_briefings(briefings, GranTurismoArabicEncoder(glyph_map, fonts))
    if fonts is not None and preview_path is not None:
        font_preview(fonts).save(preview_path)
    if fonts is not None and text_preview_path is not None:
        briefings_sheet(
            [
                (briefing.test, briefing_preview(encoded[briefing.key], fonts))
                for briefing in briefings
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "briefings": len(briefings),
        "tests": [briefing.test for briefing in briefings],
        "lines_measured": fonts is not None,
        "encoded_bytes": sum(len(briefing_bytes(result.briefing)) for result in encoded.values()),
        "arabic_glyphs": len(glyph_map.characters),
    }
    if fonts is not None:
        report["font_sizes"] = {str(index): font.font_size for index, font in fonts.items()}
        report["lines"] = {key: len(result.lines or ()) for key, result in encoded.items()}
        report["widest_title"] = max(
            result.title.width for result in encoded.values() if result.title is not None
        )
    return report


def encode_gran_turismo_arabic_briefing(
    text: str, font_path: Path | None = None
) -> dict[str, object]:
    """Encode one briefing in notation; with a font, the width of each line.

    Its codes are those of its own characters.
    """
    title, paragraphs = parse_notation(text)
    characters = briefing_characters(title, paragraphs)
    glyph_map = gran_turismo_glyph_codes(characters[0] | characters[1])
    fonts = (
        build_gran_turismo_fonts(font_path, glyph_map, body=characters[1], title=characters[0])
        if font_path is not None
        else None
    )
    result = GranTurismoArabicEncoder(glyph_map, fonts).encode(title, paragraphs)
    data = briefing_bytes(result.briefing)
    payload: dict[str, object] = {"bytes": data.hex(" ").upper(), "count": len(data)}
    if result.lines is not None and result.title is not None:
        payload["title_width"] = result.title.width
        payload["lines"] = [sum(word.width for word in line.words) for line in result.lines]
    return payload


def write_build_outputs(
    build: GranTurismoArabicBuild, out_dir: Path, *, rom_name: str | None
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
    briefings: tuple[GranTurismoBriefing, ...] | None = None,
    layout: GranTurismoLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(track_image)
    files = read_files(RawTrack(track_image), layout)
    briefings = briefings or gran_turismo_arabic_briefings(translations)
    return {
        briefing.key: briefing_notation(parse_briefing(_verify_source(files.briefings, briefing)))
        for briefing in briefings
    }
