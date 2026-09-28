"""Arabic ROM overlay for *Chrono Trigger* (USA): three messages of the opening.

The ROM is the No-Intro dump (SHA-256 below), 4 MiB mapped as HiROM, whose
banks $C0 to $FF are its bytes in order; the overlay patches the user's and
ships as a BPS patch of it. The overlay:

1. verifies the ROM, every byte of the text engine it replaces or relies on
   (``SITES``, ``ANCHORS``: the engine's code where the hooks go back to, its
   tile tables and steps, the font's widths and addresses), that the room it
   writes (``ROOM_START`` to ``ROOM_END``, zeros at the end of bank $DB) is
   empty, and each translated message's original (its table's pointer, the
   SHA-256 of its bytes and, where pinned, its commands);
2. draws the translation's glyphs (``engines.chrono_trigger_arabic``), holds
   each translation's commands against its original's (``command_skeleton``:
   everything but the layout the encoder writes itself), encodes each message
   and writes into that room the hooks
   (``chrono_trigger_arabic_hooks.s``), the list that sends each translated
   message to its Arabic (``REDIRECTS``), the glyphs' widths and pixels and
   the Arabic messages;
3. puts a long call or jump to a hook in place of three places of the engine
   (``SITES``);
4. sets the header's checksum;
5. reads everything back from the image before accepting it: the hooks, the
   sites, the list, the widths, the font, and each Arabic message through the
   list as the hooks find it (``read_redirects``, the engine's ``string_bytes``),
   with the translation's commands; and proves nothing else changed.

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
from classic_retro.cpu.m65816 import jml_long, jsl_long
from classic_retro.engines.chrono_trigger import (
    command_skeleton,
    dictionary,
    string_bytes,
    string_notation,
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
from classic_retro.patching.overlay import verify_bytes, verify_empty, verify_untouched
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.chrono_trigger_arabic_script import (
    ChronoTriggerMessage,
    chrono_trigger_arabic_messages,
)

# No-Intro "Chrono Trigger (USA)".
ROM_SHA256 = "06d1c2b06b716052c5596aaa0c2e5632a027fee1a9a28439e509f813c30829a9"
ROM_SIZE = 4 * 1024 * 1024
IMAGE = ImageSpec("Chrono Trigger (USA)", ROM_SHA256, ROM_SIZE, base=0)
# HiROM: bank $C0 is the ROM's first 64 KiB.
ROM_BANK = 0xC00000
HEADER = 0xFFC0
CHECKSUM = HEADER + 0x1C  # the complement, then the checksum

# The room the overlay writes: zeros at the end of bank $DB. The hooks, the
# list of translated messages (6 bytes each: the English's address, the
# Arabic's; a zero bank ends it), a width a glyph, 48 bytes a glyph, then the
# Arabic messages. The hooks tell an Arabic message by its bank.
ROOM_START = 0xDB8000
HOOK_ADDRESS = 0xDB8000
REDIRECTS = 0xDB8400
REDIRECT_ENTRY = 6
ARABIC_WIDTHS = 0xDB8800
ARABIC_FONT = 0xDB8900
MESSAGES = 0xDBB400
ROOM_END = 0xDBC000
ARABIC_BANK = 0xDB
HOOK_SOURCE = Path(__file__).with_name("chrono_trigger_arabic_hooks.s")

# ca65 --cpu 65816 chrono_trigger_arabic_hooks.s; ld65 at $DB:8000
HOOK_CODE = bytes.fromhex(
    "a50f8533a20000bf0284dbf028c533d01cc220bf0084dbc531d010bf0384db85"
    "31e220bf0584db8533800ae220e8e8e8e8e8e880d2c220a90000e2206ba731c2"
    "20e631e22048a533c9dbf00d68c9a090045cbe58c25cd058c268c921b0045cfd"
    "58c2206d80c613d0d45ccb58c2c22029ff0038e92100aa856ebf0088db29ff00"
    "48066e066e066e066ea56e0a18656e186900898560186918008563e220a9db85"
    "6285656466c220a53429ff00856ea9000138e56e38e3013005e22020f481e220"
    "68186534853468e617c220a90000e22060a533c9dbd004a530d008c220a5355c"
    "c85dc2c220a9000048a5352087811863018301a00000a201008ae220c53ab010"
    "205b81c2202087811863018301e880e9c220a53429ff00856ea9000138e56e38"
    "e30148a53520a481a00000a201008ae220c53ab00b205b81c22020a481e880ee"
    "e2208a1865178517a901853ac2206868e22018653485345c325ec2c220b73729"
    "ff00c8e220c903b00bc9019007c220a90001c860eba530c902d005eb1869d4eb"
    "ebc22029ff0060c9a0009014c90001b00fda38e9a000aabfe660c2fa29ff0060"
    "a9000060da5a48208781f03ca3010a0a0a856e0a18656e186960208560a3014a"
    "0a0a0a856e0a18656e186960388563e220a9ff8562a9ff8565a3014aa9006a85"
    "66a30920f481c2206820878118630783077afa608b48a9c248aba30129078568"
    "64696829f84a4ac23029ff00aaa514290f00d014bde65f8570bde85f8576bdea"
    "5f8578a9f0008012bd66608570bd68608576bd6a608578a9f001857aa5101869"
    "08008573e220a5128575c220646aa46ae220b760ebb763246610060a0a0a0a80"
    "0229f0c220646ca668f0064a666ccad0fa856ee220a470a56f17739773a476a5"
    "6e17739773a478a56d17739773c220e673a56a1a856ac90800d009a57318657a"
    "8573a56ac91800d0a5e220ab60"
)
HOOK_SYMBOLS = {"setup_hook": 0x00, "reader_hook": 0x3D, "glyph_hook": 0xD1}
HOOKS = HookProgram(
    "Chrono Trigger hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="65816"
)
PATCH_NAME = "chrono-trigger-usa-arabic-opening.bps"


def rom_offset(address: int) -> int:
    """A HiROM address of banks $C0-$FF as an offset in the ROM."""
    if not ROM_BANK <= address < ROM_BANK + ROM_SIZE:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"${address:06X} is not in the ROM")
    return address - ROM_BANK


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


# The hooks are in another bank than the engine, so a site calls or jumps long
# (``cpu.m65816``): four bytes, as long as each site.
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
)
# Bytes the hooks rely on without replacing them.
ANCHORS = {
    # The message's start: the engine's direct page ($0200), the string's
    # address from its table, then its state.
    0xC257E0: bytes.fromhex("c2200ba900025b"),
    0xC257EE: bytes.fromhex("b70d8531a90000e220"),
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
    """Every byte the overlay replaces or relies on, and its room empty."""
    if len(rom) != ROM_SIZE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"The ROM is {len(rom)} bytes, not {ROM_SIZE}"
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    verify_bytes(rom, expected, offset=rom_offset, what="the ROM")
    room = rom_offset(ROOM_START)
    verify_empty(
        rom, room, room + ROOM_END - ROOM_START, 0x00, what="The room of the hooks and their data"
    )


def message_address(rom: bytes, message: ChronoTriggerMessage) -> int:
    """The HiROM address of a message's English string, from its table."""
    table = message.table
    (pointer,) = struct.unpack_from("<H", rom, table + 2 * message.index)
    return ROM_BANK + (table & ~0xFFFF) + pointer


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
    places = [(message.table, message.index) for message in messages]
    if len(set(places)) != len(places):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one message")
    return encoded


def room_data(
    rom: bytes,
    messages: Sequence[ChronoTriggerMessage],
    encoded: Mapping[str, EncodedMessage],
    font: CtFont,
) -> dict[int, bytes]:
    """What the overlay writes into its room, by address."""
    texts = bytearray()
    redirects = bytearray()
    for message in messages:
        english = message_address(rom, message)
        arabic = MESSAGES + len(texts)
        redirects += struct.pack(
            "<HBHB", english & 0xFFFF, english >> 16, arabic & 0xFFFF, arabic >> 16
        )
        texts += encoded[message.key].data
    if len(redirects) + REDIRECT_ENTRY > ARABIC_WIDTHS - REDIRECTS:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW, f"{len(messages)} messages do not fit the list"
        )
    if MESSAGES + len(texts) > ROOM_END:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The Arabic messages need {len(texts)} bytes; the room holds {ROOM_END - MESSAGES}",
        )
    widths = bytearray(len(ARABIC_CODES))
    glyphs = bytearray(len(ARABIC_CODES) * GLYPH_BYTES)
    for code, glyph in font.glyphs.items():
        index = code - ARABIC_CODES[0]
        widths[index] = glyph.width
        glyphs[index * GLYPH_BYTES : (index + 1) * GLYPH_BYTES] = glyph.data()
    return {
        HOOK_ADDRESS: HOOK_CODE,
        REDIRECTS: bytes(redirects + bytes(REDIRECT_ENTRY)),
        ARABIC_WIDTHS: bytes(widths),
        ARABIC_FONT: bytes(glyphs),
        MESSAGES: bytes(texts),
    }


def set_checksum(rom: bytearray) -> int:
    """The header's checksum and complement for the ROM as it is now: the sum of its
    bytes, which a checksum and its complement leave as it is."""
    struct.pack_into("<HH", rom, CHECKSUM, 0xFFFF, 0x0000)
    checksum = sum(rom) & 0xFFFF
    struct.pack_into("<HH", rom, CHECKSUM, checksum ^ 0xFFFF, checksum)
    return checksum


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

    output = bytearray(rom)
    writes = room_data(rom, messages, encoded, font)
    for address, data in writes.items():
        at = rom_offset(address)
        output[at : at + len(data)] = data
    for site in SITES:
        at = rom_offset(site.address)
        output[at : at + len(site.patched)] = site.patched
    checksum = set_checksum(output)
    result = bytes(output)
    _verify_output(result, rom, writes, messages, encoded)
    patch = create_bps(rom, result)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, result, patch),
        "messages": {
            message.key: {
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
        "arabic_glyphs": len(font.glyphs),
        "arabic_codes": _code_range(glyph_map),
        "font_size": font.font_size,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_address": f"${HOOK_ADDRESS:06X}",
        "hook_bytes": len(HOOK_CODE),
        "arabic_message_bytes": len(writes[MESSAGES]),
        "checksum": f"{checksum:04X}",
    }
    return ChronoTriggerArabicBuild(rom=result, patch=patch, font=font, report=report)


def _code_range(glyph_map: GlyphCodes) -> str:
    codes = glyph_map.all_codes()
    return f"{min(codes):02X}..{max(codes):02X}"


def read_redirects(rom: bytes) -> dict[int, int]:
    """The list of translated messages as the hooks read it: each English string's
    address and its Arabic's, to the entry whose English bank is zero."""
    found: dict[int, int] = {}
    at = rom_offset(REDIRECTS)
    while at + REDIRECT_ENTRY <= rom_offset(ARABIC_WIDTHS):
        english, english_bank, arabic, arabic_bank = struct.unpack_from("<HBHB", rom, at)
        if english_bank == 0:
            return found
        found[english_bank << 16 | english] = arabic_bank << 16 | arabic
        at += REDIRECT_ENTRY
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED, "The list of translated messages has no end"
    )


def _verify_output(
    output: bytes,
    original: bytes,
    writes: Mapping[int, bytes],
    messages: Sequence[ChronoTriggerMessage],
    encoded: Mapping[str, EncodedMessage],
) -> None:
    """Everything written reads back, only the sites, the room and the checksum
    changed, and the checksum holds."""
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
        REDIRECTS: "The list of translated messages",
        ARABIC_WIDTHS: "The width table",
        ARABIC_FONT: "The font table",
        MESSAGES: "The Arabic text",
    }
    for address, data in writes.items():
        if _read(output, address, len(data)) != data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{names[address]} does not read back"
            )
    redirects = read_redirects(output)
    if list(redirects) != [message_address(original, message) for message in messages]:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The list of translated messages does not read back in order",
        )
    for message in messages:
        arabic = redirects[message_address(original, message)]
        if not MESSAGES <= arabic < ROOM_END:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: its Arabic is not in the room"
            )
        data = string_bytes(output, rom_offset(arabic))
        if data != encoded[message.key].data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: the Arabic message does not read back through the list",
            )
        if command_skeleton(data) != notation_skeleton(message.notation):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: the Arabic message read back has other commands",
            )
    places = [(site.address, len(site.patched)) for site in SITES]
    places += [(address, len(data)) for address, data in writes.items()]
    allowed = [(at := rom_offset(address), at + size) for address, size in places]
    allowed.append((CHECKSUM, CHECKSUM + 4))
    verify_untouched(original, output, allowed, what="The ROM")
    (checksum,) = struct.unpack_from("<H", output, CHECKSUM + 2)
    if sum(output) & 0xFFFF != checksum:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header's checksum is wrong")


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
    report: dict[str, object] = {
        "messages": len(messages),
        "keys": [message.key for message in messages],
        "laid_out": font is not None,
        "encoded_bytes": sum(len(result.data) for result in encoded.values()),
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
