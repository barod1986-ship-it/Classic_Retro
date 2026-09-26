"""Arabic disc overlay for *Castlevania: Symphony of the Night* (USA).

The sotn-decomp decompilation gave every address, but it takes its data from
the original disc, so the overlay patches the user's image: the data track
(Track 1) of the Redump dump, SHA-256 below, and ships as a BPS patch of that
file. The CUE sheet and the audio track stay as they are.

The prologue's dialogue is the cutscene of stage ST0 (``ST/ST0/ST0.BIN``),
which DRA.BIN's table of stages loads at 0x80180000 by its sector and length.
The overlay:

1. verifies the track, the ISO 9660 records of ST0.BIN and DRA.BIN, every
   sector it reads (sync, header, EDC and ECC), the stage table's entry, the
   script and each translated message's original (its pinned hash and
   commands) and the speakers' names;
2. builds a new ST0.BIN: the original with its dialogue patched (``SITES``:
   the lines 16 rows apart and three to the box, the glyph and name calls
   taken by the hooks, the script read from the Arabic one) and, after its
   end, the MIPS hooks (``sotn_arabic_hooks.s``), the Arabic font's widths and
   glyphs, the speakers' names, the Arabic script and the hooks' line images;
3. writes it to the empty sectors at the end of the data track, after the
   extent of its last file, since it has outgrown its own place; the original
   stays where it was;
4. points the stage table's entry and the ISO 9660 record of ST0.BIN at the
   new file. Every sector written gets its EDC and ECC.

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
from classic_retro.cpu.mips import (
    NOP,
    addiu,
    address_pair,
    jal_instruction,
    jump_targets,
    li,
    pair_address,
    sll,
    slti,
)
from classic_retro.engines.sotn import (
    command_skeleton,
    parse_notation,
    script_messages,
    split_script,
    text_notation,
)
from classic_retro.engines.sotn_arabic import (
    ARABIC_CODES,
    BASELINE,
    GLYPH_BYTES,
    LINE_WIDTH,
    SotnArabicEncoder,
    SotnFont,
    build_sotn_font,
    font_preview,
    message_preview,
    messages_sheet,
    painted_characters,
    sotn_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.cdrom import (
    DATA_SIZE,
    SECTOR_SIZE,
    IsoRecord,
    RawTrack,
    check_form1,
    claimed,
    iso_file,
    sector_count,
    set_file_extent,
    volume_space,
)
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.sotn_arabic_script import (
    NAME_TABLE,
    SCRIPT_ADDRESS,
    SCRIPT_END,
    SCRIPT_SHA256,
    SotnArabicMessage,
    SotnArabicName,
    sotn_arabic_messages,
    sotn_arabic_names,
)

# The Redump dump's data track: "Castlevania - Symphony of the Night (USA) (Track 1).bin".
TRACK_SHA256 = "ce01203a9df93e001b88ef4c350889c19f11ffba89d20f214bdd8dec0b2d8d7c"
TRACK_SIZE = 538_655_040
IMAGE = ImageSpec(
    "Castlevania: Symphony of the Night (USA), Track 1", TRACK_SHA256, TRACK_SIZE, base=0
)

ST0_PATH = "/ST/ST0/ST0.BIN;1"
DRA_PATH = "/DRA.BIN;1"
# ST0.BIN's size: its code, data and BSS, which end where the overlay's part starts.
ST0_SIZE = 0x425C4


@dataclass(frozen=True, slots=True)
class SotnLayout:
    """Where the image holds what the overlay reads and writes, and the SHA-256 it pins it by."""

    st0_lba: int
    st0_sha256: str
    dra_lba: int
    dra_sha256: str
    # DRA.BIN's table of stages: ST0's entry (its graphics' sector, then the
    # overlay's sector and length), at this offset of the file.
    stage_entry: int
    graphics_lba: int
    # ST0's cutscene script, SCRIPT_ADDRESS to SCRIPT_END.
    script_sha256: str
    # The empty sectors at the end of the data track, after the extent of its
    # last file: where the new ST0.BIN goes.
    free_lba: int
    free_sectors: int


USA_LAYOUT = SotnLayout(
    st0_lba=0x90F9,
    st0_sha256="70e824ca670f25e19e56c5966f64efab9474b83fb5a5fb5391d0de253a65940e",
    dra_lba=0x12B,
    dra_sha256="6cb1383b5b94e0bcad041af9856853907226091c184071917a739b91734af66b",
    stage_entry=0x4194,
    graphics_lba=0x9044,
    script_sha256=SCRIPT_SHA256,
    # After the extent of SD/XA_STR1, the track's last file, up to the track's
    # last sector (which is not blank: it holds parity bytes).
    free_lba=228_870,
    free_sectors=149,
)

# Where ST0.BIN is loaded, and the part the overlay adds after its end.
ST0_BASE = 0x80180000
HOOK_CODE_ADDRESS = 0x801C2600
WIDTHS_ADDRESS = 0x801C2A00
NAMES_ADDRESS = 0x801C2A80
NAME_SLOT = 16
NAME_SLOTS = 8
ARABIC_SCRIPT_ADDRESS = 0x801C2B00
GLYPHS_ADDRESS = 0x801C3400
GLYPHS_END = GLYPHS_ADDRESS + len(ARABIC_CODES) * GLYPH_BYTES
LINE_IMAGE_ADDRESS = 0x801C7400
NAME_IMAGE_ADDRESS = 0x801C7A00
LINE_IMAGE_BYTES = 0x600
PEN_ADDRESS = 0x801C8000
FILE_END = PEN_ADDRESS + 4
HOOK_SOURCE = Path(__file__).with_name("sotn_arabic_hooks.s")

# The game's routines and data the hooks call or read.
MOVE_IMAGE = 0x80012BEC
LOAD_IMAGE = 0x80012B24
ALLOC_PRIMITIVES = 0x8003C7B8
PRIM_BUF = 0x80086FEC
DIALOGUE = 0x801C24CC
DESTROY_ENTITY = 0x801B4908
DRAW_ACTOR_NAME = 0x801A8CB0
# Where the cutscene loads its script's address (``lui``/``addiu``).
SCRIPT_POINTER = 0x801A9384
# The dialogue's palette, for both speakers (``clut_indexes``).
TEXT_CLUT_TABLE = 0x80180794
TEXT_CLUT = 0x01A1

# mipsel-linux-gnu-as -march=r3000 sotn_arabic_hooks.s; ld -Ttext 0x801C2600; objcopy -j .text
HOOK_CODE = bytes.fromhex(
    "1c80083ccc24098d00000000ffff29910000000080002a2d0300401100000000"
    "fb4a000800000000e0ffbd271800bfaf1400b0af1000b1af2580c00025882001"
    "d8240a851c80063c0600aa140074c6240c0a070c2520c000a00008241d80013c"
    "008028ac1c80013c21083100802929901d80013c0080258c252020022328a900"
    "008025ac1c80063c210a070c0074c624252000021c80053c130a070c0074a524"
    "1800bf8f1400b08f1000b18f0800e0032000bd27d8ffbd272400bfaf2000b3af"
    "1c00b2af1800b1af1400b0afffff90302588a0000480023cb8c7428c06000424"
    "09f84000010005240014020003140200ffff0824050048140000000042d2060c"
    "2520200243000010000000001c80013c002522ac404002002140020180400800"
    "21400201804008000880123cec6f5226219048021c80043c0c0a070c007a8424"
    "008110001c80013c21083000802a302400001392a00005241000a5af0e006012"
    "01001026000004921000a58f1c80013c2108240080292990000000002328a900"
    "1000a5af1c80063c210a070c007ac624f2ff0010ffff7326c00104241c80053c"
    "130a070c007aa5241000a98f06000824070048a2100008241a0048a6a1010824"
    "0e0048a60c0049a2c00008240d0048a2a000082423400901180048a210000824"
    "190048a2ff010824260048a608000824320048a61c80013cd0242884d4242a84"
    "2140090104000825080048a601004a250a004aa62400bf8f2000b38f1c00b28f"
    "1800b18f1400b08f0800e0032800bd2700060824fcff082521488800fdff0015"
    "000020ad0800e00300000000e0ffbd271800bfaf1000a0a71200a4a730000824"
    "1400a8a7100008241600a8a7c94a000c1000a4271800bf8f000000000800e003"
    "2000bd271c80013c210824008029399080ff8824c04108001c80093c00342925"
    "2140090110001824255000001700591142580a0021580b0100006b9101004c31"
    "020080110f006d3102690b000d00a0112170aa0042780e002178cf000000eb91"
    "0100ce310400c0110f006c3100690d000300001025588d01f0006b3125586d01"
    "0000eba1e9ff001001004a2508000825ffff1827e4ff00176000c6240800e003"
    "00000000000000000000000000000000"
)
HOOK_SYMBOLS = {"hook_glyph": 0x00, "hook_name": 0xB4}
HOOKS = HookProgram(
    "SOTN hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="r3000"
)
# What the hooks call, and nothing else.
HOOK_CALLS = frozenset((MOVE_IMAGE, LOAD_IMAGE, DESTROY_ENTITY))
PATCH_NAME = "sotn-usa-arabic-prologue.bps"


def _words(*words: int) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


# sll v0, a0, 1; addu v0, v0, a0; sll v0, v0, 2: the line's row times 12.
_ROW_TIMES_12 = _words(0x00041040, 0x00441021, 0x00021080)
_ROW_TIMES_16 = sll("v0", "a0", 4) + NOP + NOP


def sites() -> tuple[Site, ...]:
    """Every word of ST0's dialogue code the overlay replaces (the addresses from sotn-decomp)."""
    return (
        # CutsceneUnk3 clears the line's image in VRAM, now 16 rows a line.
        Site(0x801A8BA8, _ROW_TIMES_12, _ROW_TIMES_16, "clear: a line's VRAM row"),
        Site(0x801A8BC4, li("v0", 12), li("v0", 16), "clear: rows a line"),
        # CutsceneUnk4 points a line's sprite at its image.
        Site(0x801A8C74, li("v0", 12), li("v0", 16), "line sprite: height"),
        Site(0x801A8C88, _ROW_TIMES_12, _ROW_TIMES_16, "line sprite: v"),
        # ScaleCutsceneAvatar scrolls the box: four lines in turn, not five.
        Site(0x801A911C, slti("v0", "a3", 5), slti("v0", "a3", 4), "scroll: the oldest line"),
        Site(0x801A9128, addiu("a3", "a3", -5), addiu("a3", "a3", -4), "scroll: wrap"),
        Site(0x801A912C, slti("v0", "a3", 5), slti("v0", "a3", 4), "scroll: wrap"),
        Site(0x801A9134, addiu("a3", "a3", -5), addiu("a3", "a3", -4), "scroll: wrap"),
        Site(0x801A9138, addiu("a3", "a3", 5), addiu("a3", "a3", 4), "scroll: wrap"),
        Site(0x801A91E8, slti("v0", "v1", 5), slti("v0", "v1", 4), "scroll: the lines moved"),
        # EntityCutscene: the script, the lines, the name and the glyphs.
        Site(
            SCRIPT_POINTER,
            address_pair("a0", SCRIPT_ADDRESS),
            address_pair("a0", ARABIC_SCRIPT_ADDRESS),
            "the cutscene's script",
        ),
        Site(0x801A94E4, addiu("v0", "v0", 12), addiu("v0", "v0", 16), "line end: line spacing"),
        Site(0x801A9504, slti("v0", "v0", 5), slti("v0", "v0", 4), "line end: four line images"),
        Site(0x801A9538, slti("v0", "v0", 4), slti("v0", "v0", 3), "line end: three in the box"),
        Site(
            0x801A9718,
            jal_instruction(0x801A9718, DRAW_ACTOR_NAME),
            jal_instruction(0x801A9718, HOOKS.symbol_address("hook_name")),
            "the speaker's name",
        ),
        Site(
            0x801A9C44,
            _words(0x00033040, 0x00C33021, 0x00063080),
            sll("a2", "v1", 4) + NOP + NOP,
            "glyph: the line's VRAM row",
        ),
        Site(
            0x801A9C58,
            jal_instruction(0x801A9C58, MOVE_IMAGE),
            jal_instruction(0x801A9C58, HOOKS.symbol_address("hook_glyph")),
            "glyph: drawn by the hook",
        ),
        Site(0x801A9C94, slti("v0", "v0", 6), slti("v0", "v0", 8), "scroll: 16 rows, 2 a frame"),
    )


SITES = sites()

# ST0 bytes the hooks rely on without replacing them.
ANCHORS = {
    # The dialogue's palette for both speakers.
    TEXT_CLUT_TABLE: struct.pack("<HH", TEXT_CLUT, TEXT_CLUT),
    # The glyph's path: the byte at scriptCur, then the routine's pen (nextCharX,
    # g_Dialogue + 0x0A) and the line (nextCharY, + 0x0E) for the call.
    0x801A9468: _words(0x8E220000, 0x00000000, 0x24430001, 0xAE230000, 0x90460000),
    0x801A9C1C: _words(0x3C05801C, 0x84A524D6, 0x3C03801C, 0x846324DA),
    # The name's routine: the primitives it allocates are g_Dialogue.primIndex[1].
    0x801A8D18: _words(0x3C028004, 0x8C42C7B8),
    0x801A8D6C: _words(0x3C03801C, 0x24632500),
    0x801A8D40: jal_instruction(0x801A8D40, DESTROY_ENTITY),
    # The line end: the pen back to the line's start (nextLineX).
    0x801A94C8: _words(0x96020008, 0x96030002),
    # ST0's end: its BSS, the last thing the stage uses.
    ST0_BASE + ST0_SIZE - 4: bytes(4),
}


@dataclass(frozen=True, slots=True)
class SotnArabicBuild:
    track: bytes
    patch: BpsPatch
    font: SotnFont
    st0: bytes
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(track: bytes) -> None:
    IMAGE.verify(track)


def _file(
    track: RawTrack, path: str, lba: int, size: int | None, digest: str
) -> tuple[IsoRecord, bytes]:
    """A file of the image, read and checked: its record, its sectors, its bytes."""
    record = iso_file(track, path)
    if record.lba != lba or (size is not None and record.size != size):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{path} is at LBA {record.lba} ({record.size} bytes), not {lba}",
        )
    track.verify(record.lba, record.sectors)
    data = track.read(record.lba, record.size)
    if source_digest(data) != digest:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{path} differs from the pinned USA file"
        )
    return record, data


def read_files(track: RawTrack, layout: SotnLayout) -> tuple[IsoRecord, bytes, IsoRecord, bytes]:
    """ST0.BIN and DRA.BIN, read and checked: their sectors and SHA-256, DRA's entry for
    ST0, and every byte of ST0 the overlay replaces or relies on."""
    st0_record, st0 = _file(track, ST0_PATH, layout.st0_lba, ST0_SIZE, layout.st0_sha256)
    dra_record, dra = _file(track, DRA_PATH, layout.dra_lba, None, layout.dra_sha256)
    _verify_stage_entry(dra, st0_record, layout)
    _verify_st0(st0, layout)
    return st0_record, st0, dra_record, dra


def _st0_offset(address: int, length: int = 1) -> int:
    offset = address - ST0_BASE
    if not 0 <= offset <= ST0_SIZE - length:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"{address:#x} is outside ST0.BIN")
    return offset


def _st0_read(st0: bytes, address: int, length: int) -> bytes:
    offset = _st0_offset(address, length)
    return bytes(st0[offset : offset + length])


def _verify_st0(st0: bytes, layout: SotnLayout) -> None:
    """Every byte of ST0 the overlay replaces or relies on."""
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    for address, original in expected.items():
        if _st0_read(st0, address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x} in ST0.BIN"
            )
    script = _st0_read(st0, SCRIPT_ADDRESS, SCRIPT_END - SCRIPT_ADDRESS)
    if source_digest(script) != layout.script_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "ST0's cutscene script differs from the pinned one"
        )
    # The hooks call the game's routines they name, and no other.
    external = {
        target
        for target in jump_targets(HOOK_CODE_ADDRESS, HOOK_CODE).values()
        if not HOOK_CODE_ADDRESS <= target < HOOK_CODE_ADDRESS + len(HOOK_CODE)
    }
    if external != HOOK_CALLS:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The hooks call " + ", ".join(f"{target:#x}" for target in sorted(external)),
        )


def _verify_stage_entry(dra: bytes, st0: IsoRecord, layout: SotnLayout) -> None:
    """DRA.BIN's table entry for ST0: its graphics, then the overlay's sector and length."""
    if len(dra) < layout.stage_entry + 12:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "DRA.BIN is too short")
    entry = struct.unpack_from("<III", dra, layout.stage_entry)
    if entry != (layout.graphics_lba, st0.lba, st0.size):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"DRA.BIN's stage table has no ST0 entry at {layout.stage_entry:#x}",
        )


def _verify_relocation(track: RawTrack, count: int, layout: SotnLayout) -> None:
    """The new ST0.BIN's sectors: empty, claimed by no file, inside the volume."""
    first, free = layout.free_lba, layout.free_sectors
    if count > free:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW, f"ST0.BIN needs {count} sectors; {free} are free"
        )
    if not track.empty(first, free):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH, f"LBA {first}..{first + free} is not empty"
        )
    owners = claimed(track, first, free)
    if owners:
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH, f"{', '.join(owners)} claims the free sectors"
        )
    if first + free > volume_space(track):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH, "The free sectors are outside the volume"
        )


def _message_starts(st0: bytes) -> list[int]:
    """The address of every message of ST0's cutscene script."""
    messages = script_messages(st0, SCRIPT_ADDRESS - ST0_BASE, SCRIPT_END - ST0_BASE)
    return [ST0_BASE + start for start, _ in messages]


def _verify_source(st0: bytes, message: SotnArabicMessage, starts: Sequence[int]) -> bytes:
    if message.source_address not in starts:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: no message starts at {message.source_address:#x}",
        )
    original = _st0_read(st0, message.source_address, message.source_end - message.source_address)
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original at {message.source_address:#x} differs from the "
            "pinned USA script",
        )
    if command_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different commands than pinned",
        )
    return original


def _name_bytes(st0: bytes, address: int) -> bytes:
    """A name as the game stores it: its codes up to and with ``FF 00``."""
    offset = _st0_offset(address)
    end = st0.find(b"\xff\x00", offset)
    if end < 0:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No name at {address:#x}")
    return bytes(st0[offset : end + 2])


def _verify_name(st0: bytes, name: SotnArabicName) -> bytes:
    (pointer,) = struct.unpack("<I", _st0_read(st0, NAME_TABLE + 4 * name.speaker, 4))
    if pointer != name.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{name.key}: speaker {name.speaker}'s name is not at {name.source_address:#x}",
        )
    original = _name_bytes(st0, name.source_address)
    if source_digest(original) != name.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{name.key}: the original at {name.source_address:#x} differs from the pinned name",
        )
    return original


def name_notation(data: bytes) -> str:
    """A name's text: each code is ASCII minus 0x20."""
    return "".join(chr(code + 0x20) for code in data[:-2])


def script_glyph_codes(
    messages: Sequence[SotnArabicMessage], names: Sequence[SotnArabicName]
) -> GlyphCodes:
    """The codes of every character the translated messages and names paint."""
    characters: set[str] = set()
    for message in messages:
        characters |= painted_characters(message.pieces)
    for name in names:
        characters |= painted_characters((name.text,))
    return sotn_glyph_codes(characters)


@dataclass(frozen=True, slots=True)
class EncodedScript:
    """The Arabic script, each message's bytes and line widths, and the names' codes."""

    script: bytes
    messages: dict[str, bytes]
    line_widths: dict[str, tuple[int, ...]]
    names: dict[int, bytes]
    name_widths: dict[int, int]


def encode_script(
    script: bytes,
    encoder: SotnArabicEncoder,
    messages: Sequence[SotnArabicMessage],
    names: Sequence[SotnArabicName],
) -> EncodedScript:
    """The original script with every translated message replaced, and the names encoded."""
    encoded: dict[str, bytes] = {}
    widths: dict[str, tuple[int, ...]] = {}
    for message in messages:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        validate_command_skeleton(message.source_skeleton, message.pieces)
        result = encoder.encode(message.pieces)
        encoded[message.key] = result.data
        widths[message.key] = result.line_widths or ()
    output = bytearray()
    position = SCRIPT_ADDRESS
    for message in sorted(messages, key=lambda item: item.source_address):
        if message.source_address < position:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{message.key} overlaps another message"
            )
        output += script[position - SCRIPT_ADDRESS : message.source_address - SCRIPT_ADDRESS]
        output += encoded[message.key]
        position = message.source_end
    output += script[position - SCRIPT_ADDRESS :]
    name_codes: dict[int, bytes] = {}
    name_widths: dict[int, int] = {}
    for name in names:
        if name.speaker in name_codes:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Speaker {name.speaker} twice")
        result = encoder.encode_name(name.text)
        if len(result.data) >= NAME_SLOT or not 0 <= name.speaker < NAME_SLOTS:
            raise ClassicRetroError(ErrorCode.TEXT_OVERFLOW, f"{name.key} does not fit its slot")
        name_codes[name.speaker] = result.data
        name_widths[name.speaker] = (result.line_widths or (0,))[0]
    return EncodedScript(bytes(output), encoded, widths, name_codes, name_widths)


def names_table(names: Mapping[int, bytes]) -> bytes:
    """A slot of 16 bytes a speaker: the glyph count, then the codes in paint order."""
    table = bytearray(NAME_SLOT * NAME_SLOTS)
    for speaker, codes in names.items():
        start = NAME_SLOT * speaker
        table[start : start + 1 + len(codes)] = bytes((len(codes),)) + codes
    return bytes(table)


def build_st0(st0: bytes, widths: bytes, glyphs: bytes, names: bytes, script: bytes) -> bytes:
    """The new ST0.BIN: the original, its sites patched, then the overlay's part."""
    if len(script) > GLYPHS_ADDRESS - ARABIC_SCRIPT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The Arabic script is too long")
    if GLYPHS_ADDRESS + len(glyphs) > GLYPHS_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The glyphs exceed their region")
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > WIDTHS_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")
    output = bytearray(st0) + bytes(FILE_END - ST0_BASE - len(st0))

    def put(address: int, data: bytes) -> None:
        output[address - ST0_BASE : address - ST0_BASE + len(data)] = data

    for site in SITES:
        put(site.address, site.patched)
    put(HOOK_CODE_ADDRESS, HOOK_CODE)
    put(WIDTHS_ADDRESS, widths)
    put(NAMES_ADDRESS, names)
    put(ARABIC_SCRIPT_ADDRESS, script)
    put(GLYPHS_ADDRESS, glyphs)
    return bytes(output)


def build_sotn_arabic_image(
    track_image: bytes,
    font_path: Path,
    *,
    messages: tuple[SotnArabicMessage, ...] | None = None,
    names: tuple[SotnArabicName, ...] | None = None,
    translations: TranslationSet | None = None,
    layout: SotnLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> SotnArabicBuild:
    """Build the Arabic data track and its BPS patch from the original one.

    ``messages``, ``names``, ``layout`` and ``verify_identity`` exist for
    synthetic tests; a real build always uses the pinned script against the
    pinned image.
    """
    if verify_identity:
        verify_usa_image(track_image)
    track = RawTrack(track_image)
    st0_record, st0, dra_record, _ = read_files(track, layout)
    _verify_relocation(track, sector_count(FILE_END - ST0_BASE), layout)
    messages = messages or sotn_arabic_messages(translations)
    names = names or sotn_arabic_names(translations)
    script = _st0_read(st0, SCRIPT_ADDRESS, SCRIPT_END - SCRIPT_ADDRESS)
    starts = _message_starts(st0)
    for message in messages:
        _verify_source(st0, message, starts)
    for name in names:
        _verify_name(st0, name)

    glyph_map = script_glyph_codes(messages, names)
    font = build_sotn_font(font_path, glyph_map)
    encoded = encode_script(script, SotnArabicEncoder(glyph_map, font), messages, names)
    for speaker, width in encoded.name_widths.items():
        if width > LINE_WIDTH:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW, f"Speaker {speaker}'s name needs {width}px"
            )
    widths = font.width_table()
    glyphs = font.glyph_table()
    new_st0 = build_st0(st0, widths, glyphs, names_table(encoded.names), encoded.script)

    target = bytearray(track_image)
    output = RawTrack(target)
    output.write_file(layout.free_lba, new_st0)
    output.patch(
        dra_record.lba,
        layout.stage_entry + 4,
        struct.pack("<II", layout.free_lba, len(new_st0)),
    )
    set_file_extent(output, st0_record, layout.free_lba, len(new_st0))
    result = bytes(target)
    _verify_output(result, track_image, new_st0, encoded.script, st0_record, dra_record, layout)
    old_start = st0_record.lba * SECTOR_SIZE
    patch = create_bps(
        track_image,
        result,
        copy_from=((old_start, old_start + st0_record.sectors * SECTOR_SIZE),),
    )
    report: dict[str, object] = {
        **base_report(IMAGE.title, track_image, result, patch),
        "messages": len(messages),
        "names": len(names),
        "message_lines": {key: list(value) for key, value in encoded.line_widths.items()},
        "name_widths": {str(speaker): width for speaker, width in encoded.name_widths.items()},
        "line_width_limit": LINE_WIDTH,
        "arabic_glyphs": len(font.glyphs),
        "arabic_codes": f"{min(font.glyphs):02X}..{max(font.glyphs):02X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_sites": len(SITES),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "arabic_script_address": f"{ARABIC_SCRIPT_ADDRESS:#x}",
        "arabic_script_bytes": len(encoded.script),
        "st0_original_lba": st0_record.lba,
        "st0_lba": layout.free_lba,
        "st0_bytes": len(new_st0),
        "st0_sha256": source_digest(new_st0),
    }
    return SotnArabicBuild(track=result, patch=patch, font=font, st0=new_st0, report=report)


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
    new_st0: bytes,
    script: bytes,
    st0: IsoRecord,
    dra: IsoRecord,
    layout: SotnLayout,
) -> None:
    """Only the sectors the overlay writes changed, and every one of them reads back."""
    count = sector_count(len(new_st0))
    written = set(range(layout.free_lba, layout.free_lba + count))
    written.add(dra.lba + (layout.stage_entry + 4) // DATA_SIZE)
    written.add(dra.lba + (layout.stage_entry + 11) // DATA_SIZE)
    written.add(st0.record_lba)
    if not _changed_sectors(output, original) <= written:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed sectors outside its own"
        )
    track = RawTrack(output)
    for lba in sorted(written):
        check_form1(track.sector(lba), lba)
    if track.read(layout.free_lba, len(new_st0)) != new_st0:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "ST0.BIN does not read back")
    record = iso_file(track, ST0_PATH)
    if (record.lba, record.size) != (layout.free_lba, len(new_st0)):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "ST0.BIN's record does not point at it"
        )
    entry = struct.unpack_from(
        "<III", track.read(dra.lba, layout.stage_entry + 12), layout.stage_entry
    )
    if entry != (layout.graphics_lba, layout.free_lba, len(new_st0)):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "DRA.BIN's stage entry does not point at ST0.BIN"
        )
    for site in SITES:
        offset = site.address - ST0_BASE
        if new_st0[offset : offset + len(site.patched)] != site.patched:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{site.address:#x} does not read back"
            )
    pointer = SCRIPT_POINTER - ST0_BASE
    if pair_address(new_st0[pointer : pointer + 8]) != ARABIC_SCRIPT_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The cutscene does not read the Arabic script"
        )
    stored = new_st0[ARABIC_SCRIPT_ADDRESS - ST0_BASE :][: len(script)]
    if stored != script:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The script does not read back")
    split_script(script)


def check_sotn_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the disc; with a font, measure and draw every message."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    messages = sotn_arabic_messages(translations)
    names = sotn_arabic_names(translations)
    glyph_map = script_glyph_codes(messages, names)
    font = build_sotn_font(font_path, glyph_map) if font_path is not None else None
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    encoder = SotnArabicEncoder(glyph_map, font)
    encoded: dict[str, bytes] = {}
    widths: dict[str, tuple[int, ...]] = {}
    for message in messages:
        validate_command_skeleton(message.source_skeleton, message.pieces)
        result = encoder.encode(message.pieces)
        encoded[message.key] = result.data
        widths[message.key] = result.line_widths or ()
    name_codes = {name.speaker: encoder.encode_name(name.text) for name in names}
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (
                    message.key,
                    message_preview(font, name_codes[message.speaker].data, encoded[message.key]),
                )
                for message in messages
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "names": len(names),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(data) for data in encoded.values()),
        "arabic_glyphs": len(glyph_map.characters),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["widest_line"] = max(max(line) for line in widths.values())
        report["line_width_limit"] = LINE_WIDTH
    return report


def encode_sotn_arabic_message(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one message in notation; with a font, the width of each line.

    Its codes are those of its own characters.
    """
    pieces = parse_notation(text)
    glyph_map = sotn_glyph_codes(painted_characters(pieces))
    font = build_sotn_font(font_path, glyph_map) if font_path is not None else None
    result = SotnArabicEncoder(glyph_map, font).encode(pieces)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = LINE_WIDTH
    return payload


def write_build_outputs(
    build: SotnArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.track)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (mipsel-linux-gnu-*) and read its symbols."""
    return HOOKS.assemble(source)


def extract_originals(
    track_image: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[SotnArabicMessage, ...] | None = None,
    names: tuple[SotnArabicName, ...] | None = None,
    layout: SotnLayout = USA_LAYOUT,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(track_image)
    _, st0, _, _ = read_files(RawTrack(track_image), layout)
    messages = messages or sotn_arabic_messages(translations)
    names = names or sotn_arabic_names(translations)
    starts = _message_starts(st0)
    originals = {
        message.key: text_notation(_verify_source(st0, message, starts)) for message in messages
    }
    originals |= {name.key: name_notation(_verify_name(st0, name)) for name in names}
    return originals


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
