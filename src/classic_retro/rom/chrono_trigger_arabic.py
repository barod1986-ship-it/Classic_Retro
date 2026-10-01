"""Arabic ROM overlay for *Chrono Trigger* (USA): the dialogue, table by table.

The ROM is the No-Intro dump (SHA-256 below), 4 MiB mapped as HiROM, whose
banks $C0 to $FF are its bytes in order; the overlay patches the user's and
ships as a BPS patch of it. The overlay:

1. verifies the ROM, every byte of the text engine it replaces or relies on
   (``SITES``, ``ANCHORS``: the engine's code where the hooks go back to, its
   tile tables and steps, the font's widths and addresses, the cursor
   routine's ends and tiles), and each translated message's original (its
   table's count and pointer, the SHA-256 of its bytes and, where pinned,
   its commands);
2. adds a third and a fourth MiB to the ROM (``EXPANDED_SIZE``,
   ``EXPANSION_FILL``), banks $40 to $5F of an ExHiROM (the header's map
   mode from $31 to $35 and its size code from $0C to $0D); the upper half of
   each added bank is a copy of the upper half of the ROM's bank of the same
   number, because the console reads banks $00 to $1F there where the HiROM
   mapping read the ROM's first banks, and the game does (its tables at
   $00:F300, $00:F800, $00:FD00, $00:FE00, the vectors' stubs at $00:FF00);
3. draws the translation's glyphs (``engines.chrono_trigger_arabic``), holds
   each translation's commands against its original's (``command_skeleton``:
   everything but the layout the encoder writes itself), encodes each message
   and writes into the lower halves of the added banks the hooks
   (``chrono_trigger_arabic_hooks.s``), the list of the translated string
   tables (``TABLES``, reached by bank through ``BANK_INDEX``), a table of
   entries for each of them (``ENTRIES``: three bytes a string, its Arabic's
   address, or zero for the English), the glyphs' widths and pixels and the
   Arabic messages (``ARABIC_TEXT``, none across a half bank; a message that
   is the tail of another, as the opening's chained messages are, is stored
   once);
4. puts a long call or jump to a hook in place of four places of the game
   (``SITES``);
5. sets the header's checksum, in the header and in its copy;
6. reads everything back from the image before accepting it: the hooks, the
   sites, the header, the mirrors, the lists and each Arabic message through
   them as the hooks find it (``read_redirects``, the engine's
   ``string_bytes``), with the translation's commands; and proves nothing
   else changed.

The English messages stay where they were, as they were: a translated one is
read from its Arabic instead, and the hooks tell an Arabic message by its
bank.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with cc65 so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.m65816 import jml_long, jsl_long, nop_fill
from classic_retro.engines.chrono_trigger import (
    command_skeleton,
    dictionary,
    string_bytes,
    string_notation,
    table_count,
)
from classic_retro.engines.chrono_trigger_arabic import (
    ARABIC_CODES,
    GLYPH_BYTES,
    ChronoTriggerArabicEncoder,
    CtFont,
    EncodedMessage,
    build_chrono_trigger_font,
    chrono_trigger_glyph_codes,
    font_preview,
    message_characters,
    message_preview,
    messages_sheet,
    notation_skeleton,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.patching.overlay import verify_bytes, verify_untouched
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.chrono_trigger_arabic_script import (
    TABLES,
    ChronoTriggerMessage,
    chrono_trigger_arabic_messages,
)

# No-Intro "Chrono Trigger (USA)".
ROM_SHA256 = "06d1c2b06b716052c5596aaa0c2e5632a027fee1a9a28439e509f813c30829a9"
ROM_SIZE = 4 * 1024 * 1024
IMAGE = ImageSpec("Chrono Trigger (USA)", ROM_SHA256, ROM_SIZE, base=0)
# HiROM: bank $C0 is the ROM's first 64 KiB.
ROM_BANK = 0xC00000
BANK = 0x10000
HALF_BANK = 0x8000
HEADER = 0xFFC0
MAP_MODE_BYTE = HEADER + 0x15  # $31 HiROM, fast; $35 ExHiROM, fast
ROM_SIZE_BYTE = HEADER + 0x17  # 2 ** n KiB: $0C for 4 MiB, $0D for the 6 of a 48 Mbit cartridge
CHECKSUM = HEADER + 0x1C  # the complement, then the checksum
MAP_MODES = {ROM_SIZE: 0x31}
ROM_SIZE_CODES = {ROM_SIZE: 0x0C}
# The added 2 MiB: banks $40-$5F, whose file offset is their address; 0xFF where
# the overlay writes nothing but the mirrors.
EXPANDED_SIZE = 6 * 1024 * 1024
EXPANSION_FILL = 0xFF
EXTENSION = 0x400000
EXTENSION_BANKS = range(0x40, 0x60)
MAP_MODES[EXPANDED_SIZE] = 0x35
ROM_SIZE_CODES[EXPANDED_SIZE] = 0x0D
# The header's copy, in the mirror of the ROM's first bank.
HEADER_COPY = EXTENSION + HEADER

# The overlay's data, in the lower halves of the added banks: the hooks; the
# bank index (a word a bank from $C0: the offset in bank $40 of the bank's
# first table entry, 0 for none); the tables (8 bytes each: the English
# table's address, its strings times two, its entries' address; a zero bank
# ends the list); a width a glyph; 48 bytes a glyph; the entries of each table
# (3 bytes a string: its Arabic's address, or 0); then the Arabic messages.
HOOK_ADDRESS = 0x400000
BANK_INDEX = 0x400800
BANK_INDEX_COUNT = 0x40
TABLE_LIST = 0x400900
TABLE_LIST_END = 0x402000
TABLE_ENTRY = 8
ARABIC_WIDTHS = 0x402000
ARABIC_FONT = 0x402100
ARABIC_FONT_END = 0x405000
ENTRIES = 0x410000
ENTRIES_END = 0x418000
ENTRY = 3
ARABIC_TEXT = 0x420000
ARABIC_TEXT_END = 0x600000
FIRST_ARABIC_BANK = ARABIC_TEXT >> 16
END_ARABIC_BANK = ARABIC_TEXT_END >> 16
HOOK_SOURCE = Path(__file__).with_name("chrono_trigger_arabic_hooks.s")

# ca65 --cpu 65816 chrono_trigger_arabic_hooks.s; ld65 at $40:0000
HOOK_CODE = bytes.fromhex(
    "a50f853338e9c09064c22029ff000aaabf000840f055aa9818650d8560e220bf020040c50fd046c2"
    "20a56038ff0000409031df030040b02b4a85600a186560187f0500408560e220bf0700408562a002"
    "00b760f018a8c220a7608531e220988533800a8a18690800aa80b2e220c220a90000e2206ba731c2"
    "20e631e22048a533c9429004c960900d68c9a090045cbe58c25cd058c268c921b0045cfd58c220a9"
    "00c613d0d05ccb58c2c22029ff0038e92100aa856ebf00204029ff0048066e066e066e066ea56e0a"
    "18656e186900218560186918008563e220a940856285656466c220a53429ff00856ea9000138e56e"
    "38e3013005e220203502e22068186534853468e617c220a90000e22060a533c9429008c960b004a5"
    "30d008c220a5355cc85dc2c220a9000048a53520c8011863018301a00000a201008ae220c53ab010"
    "209b01c22020c8011863018301e880e9c220a53429ff00856ea9000138e56e38e30148a53520e501"
    "a00000a201008ae220c53ab00b209b01c22020e501e880eee2208a1865178517a901853ac2206868"
    "e22018653485345c325ec2c220b73729ff00c8e220eba530c902d006eb1869d48010ebc903b00bc9"
    "019007c220a90001c860c22029ff0060c9a0009014c90001b00fda38e9a000aabfe660c2fa29ff00"
    "60a9000060da5a4820c801f03ca3010a0a0a856e0a18656e186960208560a3014a0a0a0a856e0a18"
    "656e186960388563e220a9ff8562a9ff8565a3014aa9006a8566a309203502c2206820c801186307"
    "83077afa608b48a9c248aba3012907856864696829f84a4ac23029ff00aaa514290f00d014bde65f"
    "8570bde85f8576bdea5f8578a9f0008012bd66608570bd68608576bd6a608578a9f001857aa51018"
    "6908008573e220a5128575c220646aa46ae220b760ebb763246610060a0a0a0a800229f0c220646c"
    "a668f0064a666ccad0fa856ee220a470a56f17739773a476a56e17739773a478a56d17739773c220"
    "e673a56a1a856ac90800d009a57318657a8573a56ac91800d0a5e220ab600bc220a900215be220a9"
    "808515a2021ca00229af33027ec942900ac960b006a21d1ca02d29c220da5aaf63017e29ff0048a9"
    "000048a307aa8616a301c303f01da305a88418c884188a18692000aa86169818690f00a88418c884"
    "188016a0fc288418c884188a18692000aa8616c88418c88418a307186940008307a3051869400083"
    "05a3011a8301c90400d0a86868fafac90400e220b0045ccef0c05c85f0c0"
)
HOOK_SYMBOLS = {
    "setup_hook": 0x000,
    "reader_hook": 0x075,
    "glyph_hook": 0x10D,
    "choice_hook": 0x2EE,
}
HOOKS = HookProgram(
    "Chrono Trigger hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="65816"
)
PATCH_NAME = "chrono-trigger-usa-arabic.bps"


def rom_offset(address: int) -> int:
    """A HiROM address of banks $C0-$FF, or one of the added banks $40-$5F, as an
    offset in the expanded ROM."""
    if ROM_BANK <= address < ROM_BANK + ROM_SIZE:
        return address - ROM_BANK
    if EXTENSION <= address < EXPANDED_SIZE:
        return address
    raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"${address:06X} is not in the ROM")


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


# The hooks are in another bank than the engine, so a site calls or jumps long
# (``cpu.m65816``): four bytes, filled with NOP to the site's length.
SITES = (
    Site(
        0xC257F7,
        bytes.fromhex("a50f8533"),
        jsl_long(HOOKS.symbol_address("setup_hook")),
        "a message's start (LDA $0F; STA $33): a translated one is read from its Arabic",
    ),
    Site(
        0xC258B2,
        bytes.fromhex("a731c220"),
        jml_long(HOOKS.symbol_address("reader_hook")),
        "the reading loop (LDA [$31]; REP #$20): an Arabic byte from $21 is a glyph",
    ),
    Site(
        0xC25DC4,
        bytes.fromhex("c220a535"),
        jml_long(HOOKS.symbol_address("glyph_hook")),
        "the glyph routine (REP #$20; LDA $35): a name in Arabic text, drawn whole",
    ),
    Site(
        0xC0F05E,
        bytes.fromhex("0bc220a90021"),
        nop_fill(jml_long(HOOKS.symbol_address("choice_hook")), 6),
        "the choice cursor's routine (PHD; REP #$20; LDA #$2100): the cursor at the right",
    ),
)
# Bytes the hooks rely on without replacing them.
ANCHORS = {
    # The message's start: the engine's direct page ($0200), the string's
    # address from its table (LDA [$0D],Y; STA $31), then its state.
    0xC257E0: bytes.fromhex("c2200ba900025b"),
    0xC257E7: bytes.fromhex("a50c29ff000aa8b70d8531a90000e220"),
    0xC257FB: bytes.fromhex("6430"),
    # Where the reader goes back: a character drawn, the frame's characters
    # done (LDA #$10; STA $15; RTS), the dictionary, the control codes.
    0xC258BE: bytes.fromhex("c2208535e22020c45dc613d0e7a910851560"),
    0xC258D0: bytes.fromhex("c9219029853b38e9210aaac220bf00fade"),
    0xC258FD: bytes.fromhex("a80aaa7c0359"),
    # The glyph routine after its site; the font's left and right pixels
    # ($FF:2060, $FF:3860) and bank, its widths ($C2:60E6) and its end.
    0xC25DC8: bytes.fromhex("0a0a0a856c0a656c186960208576"),
    0xC25DD6: bytes.fromhex("a5354a0a0a0a856c0a656c186960388579"),
    0xC25DFC: bytes.fromhex("a9ff8578857b"),
    0xC25E27: bytes.fromhex("18bfe660c2"),
    0xC25E32: bytes.fromhex("a900eb60"),
    # The tile buffer's layouts: the step to the tile row under, and each
    # column's offset.
    0xC25E5F: bytes.fromhex("a5731869f0008573"),
    0xC25F30: bytes.fromhex("18a57369f0018573"),
    0xC25FE6: bytes.fromhex(
        "0000100020003000400050006000700080009000a000b000c000d000e000f000"
        "0002100220023002400250026002700280029002a002b002c002d002e002f002"
        "00011001"
    ),
    0xC26066: bytes.fromhex(
        "00002000400060008000a000c000e00000012001400160018001a001c001e001"
        "00042004400460048004a004c004e00400052005400560058005a005c005e005"
        "00022002"
    ),
    # The cursor routine after its site (TCD; SEP #$20; LDA #$80; STA $15; LDA
    # $0163), its two ends, and its first slot's cells and tiles (the cursor's
    # $28FC at line 0, the text's $2902).
    0xC0F064: bytes.fromhex("5be220a9808515ad6301"),
    0xC0F085: bytes.fromhex("2ba980856360"),
    0xC0F094: bytes.fromhex("a2021c8616a2fc288618e88618a2221c8616a2fe28"),
    0xC0F0CE: bytes.fromhex("2b60"),
    0xC0F159: bytes.fromhex("a2021c8616a202298618e88618a2221c8616a21229"),
    # The vectors' stubs the console runs through bank $00 (SEI; CLC; XCE; JML
    # $FD:C000), which the added banks mirror.
    0xC0FF00: bytes.fromhex("7818fb5c00c0fd"),
}


@dataclass(frozen=True, slots=True)
class ChronoTriggerArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: CtFont
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _read(rom: bytes, address: int, length: int) -> bytes:
    at = rom_offset(address)
    return bytes(rom[at : at + length])


def verify_rom(rom: bytes) -> None:
    """The ROM's size and header (4 MiB, HiROM), and every byte the overlay replaces
    or relies on."""
    if len(rom) != ROM_SIZE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"The ROM is {len(rom)} bytes, not {ROM_SIZE}"
        )
    if rom[MAP_MODE_BYTE] != MAP_MODES[ROM_SIZE] or rom[ROM_SIZE_BYTE] != ROM_SIZE_CODES[ROM_SIZE]:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The ROM's header is not a 4 MiB HiROM's"
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    verify_bytes(rom, expected, offset=rom_offset, what="the ROM")


def table_address(table: int) -> int:
    """The HiROM address of a string table at file offset ``table``."""
    return ROM_BANK + table


def message_address(rom: bytes, message: ChronoTriggerMessage) -> int:
    """The HiROM address of a message's English string, from its table."""
    table = message.table
    (pointer,) = struct.unpack_from("<H", rom, table + 2 * message.index)
    return ROM_BANK + (table & ~0xFFFF) + pointer


def verify_tables(rom: bytes, messages: Sequence[ChronoTriggerMessage]) -> dict[int, int]:
    """The string tables the messages use, by file offset, each with its count of
    strings, as pinned and as the ROM has it."""
    counts: dict[int, int] = {}
    for message in messages:
        if message.table in counts:
            continue
        pinned = TABLES[message.table_key].count
        found = table_count(rom, message.table)
        if found != pinned:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"The table at {message.table:#x} names {found} strings, not {pinned}",
            )
        counts[message.table] = pinned
    for message in messages:
        if not 0 <= message.index < counts[message.table]:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"{message.key}: the table has no message {message.index}",
            )
    return counts


def _verify_source(rom: bytes, message: ChronoTriggerMessage) -> bytes:
    """The message's English bytes, its zero included, as pinned: its hash and, where
    pinned, its commands."""
    data = string_bytes(rom, rom_offset(message_address(rom, message)))
    if source_digest(data) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.index} differs from the pinned text",
        )
    if message.source_skeleton is not None and command_skeleton(data) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.index} has different commands than pinned",
        )
    return data


def source_skeletons(
    rom: bytes, messages: Sequence[ChronoTriggerMessage]
) -> dict[str, tuple[str, ...]]:
    """Every original's commands (``command_skeleton``), verified, by entry id."""
    return {message.key: command_skeleton(_verify_source(rom, message)) for message in messages}


# ---------------------------------------------------------------------------
# Encoding and fonts


def messages_characters(messages: Sequence[ChronoTriggerMessage]) -> set[str]:
    used: set[str] = set()
    for message in messages:
        used |= message_characters(message.notation)
    return used


def encode_messages(
    messages: Sequence[ChronoTriggerMessage],
    encoder: ChronoTriggerArabicEncoder,
    skeletons: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[str, EncodedMessage]:
    """Every message held against its original's commands, then encoded.

    The commands are the ROM's (``skeletons``, from ``source_skeletons``) or,
    without the ROM, those pinned in the script, where they are.
    """
    encoded: dict[str, EncodedMessage] = {}
    for message in messages:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        skeleton = message.source_skeleton if skeletons is None else skeletons[message.key]
        if skeleton is not None:
            validate_command_skeleton(skeleton, message.notation)
        encoded[message.key] = encoder.encode(message.notation)
        check_choices(message, encoded[message.key])
    places = [(message.table, message.index) for message in messages]
    if len(set(places)) != len(places):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one message")
    return encoded


def check_choices(message: ChronoTriggerMessage, encoded: EncodedMessage) -> None:
    """A decision's ``{choice}`` lines on the lines its event makes choices.

    The event names the first and the last line of the message's last box the
    player chooses between (``message.choices``), and takes the answer by its line:
    a choice the layout puts on another line points the cursor at the wrong answer.
    A message the game asks no choice of has no ``{choice}`` line. Only a laid-out
    message (with the font) has its lines to check."""
    if encoded.boxes is None:
        return
    found = [
        (box, number)
        for box, lines in enumerate(encoded.boxes)
        for number, line in enumerate(lines)
        if line.choice
    ]
    if message.choices is None:
        if found:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"Message {message.key} has a {{choice}} line, but the game asks no choice",
            )
        return
    first, last = message.choices
    final = len(encoded.boxes) - 1
    expected = [(final, number) for number in range(first, last + 1)]
    if found != expected:
        laid = ", ".join(f"box {box + 1} line {number + 1}" for box, number in found) or "none"
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"Message {message.key}: the game's choices are lines {first + 1} to {last + 1} "
            f"of its last box ({final + 1}); the translation's {{choice}} lines are {laid}",
        )


@dataclass(frozen=True, slots=True)
class TextLayout:
    """Where the Arabic messages went: each message's address, and the text in the
    lower halves it fills, a run of bytes each, by address."""

    addresses: dict[str, int]
    segments: tuple[tuple[int, bytes], ...]
    shared: int

    @property
    def size(self) -> int:
        return sum(len(data) for _, data in self.segments)


def lay_out_text(
    messages: Sequence[ChronoTriggerMessage], encoded: Mapping[str, EncodedMessage]
) -> TextLayout:
    """The Arabic messages one after another from ``ARABIC_TEXT``, none across the
    end of a bank's lower half (the upper halves are the mirrors, and the engine
    moves through a message with a 16-bit increment): a message that would cross
    it starts the next bank. A message whose bytes end another's is not stored again
    but named by its place in that one."""
    segments: list[tuple[int, bytes]] = []
    start = ARABIC_TEXT
    run = bytearray()
    addresses: dict[str, int] = {}
    placed: list[tuple[bytes, int]] = []
    shared = 0
    for message in messages:
        data = encoded[message.key].data
        if len(data) > HALF_BANK:
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW,
                f"{message.key}: the message is longer than a half bank",
            )
        for other, other_address in placed:
            if other.endswith(data):
                addresses[message.key] = other_address + len(other) - len(data)
                shared += 1
                break
        else:
            if (start + len(run)) % BANK + len(data) > HALF_BANK:
                segments.append((start, bytes(run)))
                start = (start // BANK + 1) * BANK
                run = bytearray()
            address = start + len(run)
            if address + len(data) > ARABIC_TEXT_END:
                raise ClassicRetroError(
                    ErrorCode.RELOCATION_OVERFLOW, "The Arabic messages do not fit their banks"
                )
            addresses[message.key] = address
            placed.append((data, address))
            run += data
    segments.append((start, bytes(run)))
    return TextLayout(addresses, tuple(segments), shared)


def room_data(
    rom: bytes,
    messages: Sequence[ChronoTriggerMessage],
    encoded: Mapping[str, EncodedMessage],
    font: CtFont,
) -> dict[int, bytes]:
    """What the overlay writes into the added banks, by address."""
    counts = verify_tables(rom, messages)
    layout = lay_out_text(messages, encoded)
    # The entries: a block a table, in the order of the tables' addresses.
    entries = bytearray()
    blocks: dict[int, int] = {}
    for table in sorted(counts):
        blocks[table] = ENTRIES + len(entries)
        entries += bytes(ENTRY * counts[table])
    if ENTRIES + len(entries) > ENTRIES_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The tables' entries do not fit")
    for message in messages:
        at = blocks[message.table] - ENTRIES + ENTRY * message.index
        entries[at : at + ENTRY] = layout.addresses[message.key].to_bytes(ENTRY, "little")
    # The list of tables, by bank then address, and the bank index into it.
    tables = bytearray()
    index = bytearray(2 * BANK_INDEX_COUNT)
    for table in sorted(counts):
        address = table_address(table)
        bank = address >> 16
        if not struct.unpack_from("<H", index, 2 * (bank - 0xC0))[0]:
            struct.pack_into("<H", index, 2 * (bank - 0xC0), (TABLE_LIST + len(tables)) & 0xFFFF)
        tables += struct.pack(
            "<HBHHB",
            address & 0xFFFF,
            bank,
            2 * counts[table],
            blocks[table] & 0xFFFF,
            blocks[table] >> 16,
        )
    tables += bytes(TABLE_ENTRY)
    if TABLE_LIST + len(tables) > TABLE_LIST_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The tables do not fit their list")
    widths = bytearray(len(ARABIC_CODES))
    glyphs = bytearray(len(ARABIC_CODES) * GLYPH_BYTES)
    for code, glyph in font.glyphs.items():
        number = code - ARABIC_CODES[0]
        widths[number] = glyph.width
        glyphs[number * GLYPH_BYTES : (number + 1) * GLYPH_BYTES] = glyph.data()
    return {
        HOOK_ADDRESS: HOOK_CODE,
        BANK_INDEX: bytes(index),
        TABLE_LIST: bytes(tables),
        ARABIC_WIDTHS: bytes(widths),
        ARABIC_FONT: bytes(glyphs),
        ENTRIES: bytes(entries),
        **dict(layout.segments),
    }


def checksum_of(rom: bytes) -> int:
    """The header's checksum of a 6 MiB ROM: the sum of its bytes, the last 2 MiB
    counted twice, as a 48 Mbit cartridge is summed (its last 16 Mbit mirrored to
    64), with the checksum and its complement summed as $FFFF and $0000."""
    return (sum(rom[:ROM_SIZE]) + 2 * sum(rom[ROM_SIZE:])) & 0xFFFF


def set_checksum(rom: bytearray) -> int:
    """The header's checksum and complement, in the header and in its copy, for the
    ROM as it is now: a checksum and its complement leave the sum as it is."""
    for at in (CHECKSUM, HEADER_COPY + 0x1C):
        struct.pack_into("<HH", rom, at, 0xFFFF, 0x0000)
    checksum = checksum_of(rom)
    for at in (CHECKSUM, HEADER_COPY + 0x1C):
        struct.pack_into("<HH", rom, at, checksum ^ 0xFFFF, checksum)
    return checksum


def mirror_ranges() -> list[tuple[int, int]]:
    """The added banks' upper halves, as (offset, length) pairs, each a copy of the
    upper half of the ROM's bank of the same number."""
    return [(EXTENSION + (bank - 0x40) * BANK + HALF_BANK, HALF_BANK) for bank in EXTENSION_BANKS]


def expanded(rom: bytes) -> bytearray:
    """The ROM with its 32 added banks ($40-$5F): the header an ExHiROM's of 6 MiB, the upper
    halves mirrored; nothing else yet."""
    output = bytearray(rom) + bytes((EXPANSION_FILL,)) * (EXPANDED_SIZE - len(rom))
    output[MAP_MODE_BYTE] = MAP_MODES[EXPANDED_SIZE]
    output[ROM_SIZE_BYTE] = ROM_SIZE_CODES[EXPANDED_SIZE]
    for site in SITES:
        at = rom_offset(site.address)
        output[at : at + len(site.patched)] = site.patched
    for at, length in mirror_ranges():
        output[at : at + length] = output[at - EXTENSION : at - EXTENSION + length]
    return output


# ---------------------------------------------------------------------------
# The build


def build_chrono_trigger_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[ChronoTriggerMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> ChronoTriggerArabicBuild:
    """Build the Arabic ROM and its BPS patch from the original.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real build
    always uses the pinned translation against the pinned ROM.
    """
    if verify_identity:
        verify_usa_image(rom)
    verify_rom(rom)
    messages = messages or chrono_trigger_arabic_messages(translations)
    skeletons = source_skeletons(rom, messages)

    used = messages_characters(messages)
    glyph_map = chrono_trigger_glyph_codes(used)
    font = build_chrono_trigger_font(font_path, glyph_map, used)
    encoded = encode_messages(messages, ChronoTriggerArabicEncoder(glyph_map, font), skeletons)

    output = expanded(rom)
    writes = room_data(rom, messages, encoded, font)
    for address, data in writes.items():
        at = rom_offset(address)
        output[at : at + len(data)] = data
    checksum = set_checksum(output)
    result = bytes(output)
    _verify_output(result, rom, writes, messages, encoded)
    patch = create_bps(rom, result)
    layout = lay_out_text(messages, encoded)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, result, patch),
        "messages": {
            message.key: {
                "table": message.table_key,
                "index": message.index,
                "bytes": len(encoded[message.key].data),
                "boxes": [
                    [line.end - line.start for line in box]
                    for box in encoded[message.key].boxes or ()
                ],
                # The original's commands, as the script pins them.
                "source_skeleton": list(skeletons[message.key]),
            }
            for message in messages
        },
        "tables": {
            TABLES[key].key: {"address": f"${table_address(TABLES[key].address):06X}"}
            for key in sorted({message.table_key for message in messages})
        },
        "arabic_glyphs": len(font.glyphs),
        "arabic_codes": _code_range(glyph_map),
        "font_size": font.font_size,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_address": f"${HOOK_ADDRESS:06X}",
        "hook_bytes": len(HOOK_CODE),
        "arabic_message_bytes": layout.size,
        "arabic_text_banks": len(layout.segments),
        "messages_shared": layout.shared,
        "checksum": f"{checksum:04X}",
    }
    return ChronoTriggerArabicBuild(rom=result, patch=patch, font=font, report=report)


def _code_range(glyph_map: GlyphCodes) -> str:
    codes = glyph_map.all_codes()
    return f"{min(codes):02X}..{max(codes):02X}"


def read_redirects(rom: bytes) -> dict[tuple[int, int], int]:
    """The translated messages as the hooks find them: by their table's file offset
    and their number, the address of their Arabic.

    The list of tables is read to its end, each table's entries through it, and
    the bank index is held to the list: a bank's word is the offset of its first
    table, or zero when it has none.
    """
    found: dict[tuple[int, int], int] = {}
    first_of_bank: dict[int, int] = {}
    at = rom_offset(TABLE_LIST)
    end = rom_offset(TABLE_LIST_END)
    previous: tuple[int, int] | None = None
    while at + TABLE_ENTRY <= end:
        low, bank, doubled, entries_low, entries_bank = struct.unpack_from("<HBHHB", rom, at)
        if bank == 0:
            break
        if (bank, low) <= (previous or (0, 0)):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, "The list of tables is not in order"
            )
        previous = (bank, low)
        first_of_bank.setdefault(bank, TABLE_LIST + at - rom_offset(TABLE_LIST))
        try:
            table = rom_offset(bank << 16 | low)
            entries = rom_offset(entries_bank << 16 | entries_low)
        except ClassicRetroError as exc:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The list of tables names {exc}"
            ) from exc
        for number in range(doubled // 2):
            address = int.from_bytes(
                rom[entries + ENTRY * number : entries + ENTRY * (number + 1)], "little"
            )
            if address:
                found[table, number] = address
        at += TABLE_ENTRY
    else:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The list of tables has no end")
    for bank in range(BANK_INDEX_COUNT):
        (word,) = struct.unpack_from("<H", rom, rom_offset(BANK_INDEX) + 2 * bank)
        expected = first_of_bank.get(0xC0 + bank, 0) & 0xFFFF
        if word != expected:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"The bank index of ${0xC0 + bank:02X} does not name its first table",
            )
    return found


def _verify_output(
    output: bytes,
    original: bytes,
    writes: Mapping[int, bytes],
    messages: Sequence[ChronoTriggerMessage],
    encoded: Mapping[str, EncodedMessage],
) -> None:
    """Everything written reads back, only the sites, the header and the added banks
    changed, the added banks hold the mirrors, the writes and nothing else, and the
    checksum holds in the header and its copy."""
    if len(output) != EXPANDED_SIZE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ROM is not 6 MiB")
    if (
        output[MAP_MODE_BYTE] != MAP_MODES[EXPANDED_SIZE]
        or output[ROM_SIZE_BYTE] != ROM_SIZE_CODES[EXPANDED_SIZE]
    ):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The header is not a 6 MiB ExHiROM's"
        )
    if _read(output, HOOK_ADDRESS, len(HOOK_CODE)) != HOOK_CODE:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The hook code does not read back"
        )
    for site in SITES:
        if _read(output, site.address, len(site.patched)) != site.patched:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"The site at ${site.address:06X} does not read back",
            )
    names = {
        HOOK_ADDRESS: "The hook code",
        BANK_INDEX: "The bank index",
        TABLE_LIST: "The list of tables",
        ARABIC_WIDTHS: "The width table",
        ARABIC_FONT: "The font table",
        ENTRIES: "The tables' entries",
    }
    for address, data in writes.items():
        name = names.get(address, "The Arabic text")
        if address % BANK + len(data) > HALF_BANK:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{name} reaches into a mirror"
            )
        if _read(output, address, len(data)) != data:
            raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, f"{name} does not read back")
    # The added banks, whole: the mirrors of the ROM's first banks as they are
    # now (the header's copy among them), the writes, and the fill elsewhere.
    expected = bytearray(bytes((EXPANSION_FILL,)) * (EXPANDED_SIZE - ROM_SIZE))
    for at, length in mirror_ranges():
        expected[at - EXTENSION : at - EXTENSION + length] = output[
            at - EXTENSION : at - EXTENSION + length
        ]
    for address, data in writes.items():
        at = rom_offset(address) - EXTENSION
        expected[at : at + len(data)] = data
    if output[EXTENSION:] != expected:
        first = next(at for at in range(len(expected)) if output[EXTENSION + at] != expected[at])
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            f"The added banks differ from what was written at {EXTENSION + first:#x}",
        )
    redirects = read_redirects(output)
    if sorted(redirects) != sorted((message.table, message.index) for message in messages):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The tables' entries do not read back with the translated messages",
        )
    for message in messages:
        arabic = redirects[message.table, message.index]
        if not ARABIC_TEXT <= arabic < ARABIC_TEXT_END or arabic & 0xFFFF >= HALF_BANK:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: its Arabic is not in the room"
            )
        data = string_bytes(output, rom_offset(arabic))
        if data != encoded[message.key].data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: the Arabic message does not read back through the tables",
            )
        if command_skeleton(data) != notation_skeleton(message.notation):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: the Arabic message read back has other commands",
            )
    allowed = [(at := rom_offset(site.address), at + len(site.patched)) for site in SITES]
    allowed += [(MAP_MODE_BYTE, MAP_MODE_BYTE + 1), (ROM_SIZE_BYTE, ROM_SIZE_BYTE + 1)]
    allowed.append((CHECKSUM, CHECKSUM + 4))
    verify_untouched(original, output[:ROM_SIZE], allowed, what="The ROM")
    checksum = checksum_of(output)
    for at in (CHECKSUM, HEADER_COPY + 0x1C):
        if struct.unpack_from("<HH", output, at) != (checksum ^ 0xFFFF, checksum):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, "The header's checksum is wrong"
            )


# ---------------------------------------------------------------------------
# Without the ROM


def check_chrono_trigger_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, lay out and draw every message."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    messages = chrono_trigger_arabic_messages(translations)
    used = messages_characters(messages)
    glyph_map = chrono_trigger_glyph_codes(used)
    font = build_chrono_trigger_font(font_path, glyph_map, used) if font_path else None
    encoded = encode_messages(messages, ChronoTriggerArabicEncoder(glyph_map, font))
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [(message.key, message_preview(encoded[message.key], font)) for message in messages]
        ).save(text_preview_path)
    layout = lay_out_text(messages, encoded)
    report: dict[str, object] = {
        "messages": len(messages),
        "tables": sorted({message.table_key for message in messages}),
        "keys": [message.key for message in messages],
        "laid_out": font is not None,
        "encoded_bytes": sum(len(result.data) for result in encoded.values()),
        "stored_bytes": layout.size,
        "messages_shared": layout.shared,
        "arabic_glyphs": len(glyph_map.characters),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["boxes"] = {key: len(result.boxes or ()) for key, result in encoded.items()}
    return report


def encode_chrono_trigger_arabic_message(
    text: str, font_path: Path | None = None
) -> dict[str, object]:
    """Encode one message in notation; with a font, each box's lines' widths.

    Its codes are those of its own characters.
    """
    used = message_characters(text)
    glyph_map = chrono_trigger_glyph_codes(used)
    font = build_chrono_trigger_font(font_path, glyph_map, used) if font_path else None
    result = ChronoTriggerArabicEncoder(glyph_map, font).encode(text)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.boxes is not None:
        payload["boxes"] = [[line.end - line.start for line in box] for box in result.boxes]
    return payload


def write_build_outputs(
    build: ChronoTriggerArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with cc65 (ca65, ld65) and read its symbols."""
    return HOOKS.assemble(source)


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[ChronoTriggerMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    words = dictionary(rom)
    messages = messages or chrono_trigger_arabic_messages(translations)
    verify_tables(rom, messages)
    return {
        message.key: string_notation(_verify_source(rom, message), words) for message in messages
    }


def extract_skeletons(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[ChronoTriggerMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Every pinned original's commands, verified, by entry id: what a maintainer pins
    as ``source_skeleton`` in the script, so the translations are checked without the
    ROM. The build's report carries the same."""
    if verify_identity:
        verify_usa_image(rom)
    return source_skeletons(rom, messages or chrono_trigger_arabic_messages(translations))
