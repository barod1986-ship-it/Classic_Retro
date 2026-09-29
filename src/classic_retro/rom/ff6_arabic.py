"""Arabic ROM overlay for *Final Fantasy III* (USA): the whole dialogue.

The ROM is the No-Intro dump (SHA-256 below, pinned from the user's own ROM),
3 MiB mapped as HiROM, whose banks $C0 to $EF are its 64 KiB pieces; the
overlay patches the user's and ships as a BPS patch of it. The overlay:

1. verifies the ROM: its header, every byte of the text engine it replaces or
   relies on (``SITES``, ``ANCHORS``: the engine's code the hooks go back
   to), and each translated message's original (its number, the SHA-256 of
   its bytes and, where pinned, its commands);
2. adds a fourth MiB to the ROM (``EXPANDED_SIZE``, ``EXPANSION_FILL``),
   banks $F0 to $FF, which the header's size already allows;
3. draws the translation's glyphs (``engines.ff6_arabic``), holds each
   translation's commands against its original's (``command_skeleton``:
   everything but the layout the encoder writes itself), encodes the
   characters' names and each message, and writes into the added banks the
   hooks (``ff6_arabic_hooks.s``), the glyphs' widths (``WIDTHS``) and
   addresses (``GLYPH_ADDRESSES``), the names (``NAMES``), the table that
   sends each message by its number to its Arabic, or to the English
   (``MESSAGES``), the glyphs (``GLYPHS``, banks $F1 and $F2) and the Arabic
   messages (``ARABIC_TEXT``, banks $F3 to $FF, none across a bank);
4. puts a long call to a hook in place of eight places of the engine
   (``SITES``);
5. sets the header's checksum;
6. reads everything back from the image before accepting it: the hooks, the
   sites, the tables and each Arabic message through the table as the hooks
   find it (``read_message_table``, ``read_arabic_message``), with the
   translation's commands; and proves nothing else changed.

The English messages stay where they were, as they were: a translated one is
read from its Arabic instead, and the hooks tell an Arabic message by its
number.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with cc65 so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.m65816 import jsl_long, nop_fill
from classic_retro.engines.ff6 import (
    DLG_COUNT,
    END,
    NAME_FIRST,
    byte_length,
    command_skeleton,
    dte_pairs,
    hirom_offset,
    message_at,
    message_notation,
)
from classic_retro.engines.ff6_arabic import (
    NAME_END,
    NAME_STRIDE,
    EncodedMessage,
    Ff6ArabicEncoder,
    Ff6Font,
    build_ff6_font,
    encode_name,
    ff6_glyph_codes,
    font_preview,
    glyph_table,
    message_characters,
    message_preview,
    messages_sheet,
    notation_skeleton,
    paint_text,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.patching.overlay import verify_bytes, verify_untouched
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.ff6_arabic_script import (
    NAME_KEYS,
    Ff6Message,
    ff6_arabic_messages,
    ff6_arabic_names,
)

# No-Intro "Final Fantasy III (USA)" (version 1.0, CRC32 A27F1C7A).
ROM_SHA256 = "0f51b4fca41b7fd509e4b8f9d543151f68efa5e97b08493e4b2a0c06f5d8d5e2"
ROM_SIZE = 3 * 1024 * 1024
IMAGE = ImageSpec("Final Fantasy III (USA)", ROM_SHA256, ROM_SIZE, base=0)
HEADER = 0xFFC0
MAP_MODE_BYTE = HEADER + 0x15  # $31: HiROM, fast
MAP_MODE = 0x31
ROM_SIZE_BYTE = HEADER + 0x17  # 2 ** n KiB: $0C, 4 MiB, for 3 MiB and for 4
ROM_SIZE_CODE = 0x0C
CHECKSUM = HEADER + 0x1C  # the complement, then the checksum
# The added MiB: banks $F0-$FF, 0xFF where the overlay writes nothing.
EXPANDED_SIZE = 4 * 1024 * 1024
EXPANSION_FILL = 0xFF

# The hooks and the data, in the added banks: the hooks first; the widths, a
# byte a code from $20; the offsets, a word a code; the names, NAME_STRIDE bytes
# each; the list of translated messages (4 bytes each: the number, its Arabic's
# offset; $FFFF ends it); the glyphs in bank $F1; the Arabic messages in bank $F2.
HOOK_ADDRESS = 0xF00000
HOOK_SOURCE = Path(__file__).with_name("ff6_arabic_hooks.s")
WIDTHS = 0xF01000
GLYPH_ADDRESSES = 0xF01100  # 3 bytes a code: the glyph's address
GLYPH_ADDRESS_ENTRY = 3
NAMES = 0xF01400
NAME_COUNT = 14
MESSAGES = 0xF02000  # 3 bytes a message number: its Arabic's address, or ENGLISH
MESSAGE_ENTRY = 3
MESSAGES_END = MESSAGES + DLG_COUNT * MESSAGE_ENTRY
ENGLISH = 0xFFFFFF
GLYPHS = 0xF10000  # two banks; a glyph never crosses one
GLYPHS_END = 0xF30000
ARABIC_TEXT = 0xF30000  # to the ROM's end; a message never crosses a bank
ARABIC_TEXT_END = 0x1000000
BANK = 0x10000

# ca65 --cpu 65816 ff6_arabic_hooks.s; ld65 at $F0:0000
HOOK_CODE = bytes.fromhex(
    "a9008f009d7e8f019d7e8f029d7ec220a5d08f0e9d7e0a186f0e9d7eaabf0020f0c9fffff01285"
    "c9e220bf0220f085cba9018f009d7e8002e220eba900eba9018d68056baf009d7ec901d011af01"
    "9d7ed007209a01eba900eba5bf186ba5bf1865c06baf009d7ed00da5bd1009686868a5bd5c6684"
    "c0a5bd6baf009d7ec901d0076868685c1985c0a6cdbfc08fc46baf009d7ec901d035686868a904"
    "85bfa9008f019d7ec220a5c185c32900061869000229ff0785c1e220eba900eba6c1d008a90985"
    "cca90285d35c5385c0a9ff85cd6baf009d7ec901d02a686868a90485bfa9008f019d7ea6c186c3"
    "a2000086c1a90985cca90285d3a5bdd0048f009d7e5c7d85c0a9ff85cd6baf009d7e29ff00c901"
    "00d029daaf109d7ecf129d7eb013aa1a1a8f109d7ebf149d7efa1865c19970056bfaa5c11869a0"
    "019970056ba5c19970056baf029d7ec901d041a9008f029d7e9c0b42a9808d1521c220af049d7e"
    "186900388d1621e220eba900eba9018d0043a9188d0143a200988e0243a97e8d0443a280038e05"
    "43a9018d0b42a5c5d0076868685c4186c064c56b8bc220a900008f109d7e8f129d7ea200009f00"
    "987ee8e8e00004d0f5a9e0008f069d7ee220a00000b7c9f00ac901f006c913f00280034c8002c9"
    "20b07ac9029018c910907bc914f019c915f034c911f00cc916f008c91cb004c84cc201c8c84cc2"
    "01c8b7c9c22029ff008f0a9d7eaf069d7e38ef0a9d7e8f069d7ee220c84cc201c220af069d7e29"
    "f0ff38e91000b003a900008f069d7e48af129d7ec90800b00faa1a1a8f129d7e680a9f149d7e80"
    "0168e220c84cc2015a2096027ac84cc20138e902c22029ff000a0a0a0a0aaae2205abf0014f0c9"
    "fff008da209602fae880f07ac84cc201c220a5c18f049d7ee220a9018f019d7e8f029d7eab60c2"
    "2029ff0038e920008f089d7eaae220bf0010f0f05bc22029ff008f0a9d7eaf069d7e38ef0a9d7e"
    "9047c9040090428f069d7e2907000aaabfe906f08f0c9d7eaf089d7e8f0e9d7e0a186f0e9d7eaa"
    "bf0011f0186f0c9d7ea8e220bf0211f048abc220af069d7e29f8ff0a0aaae2208003e22060b900"
    "001f00987e9f00987eb901001f20987e9f20987eb902001f40987e9f40987eb92d001f01987e9f"
    "01987eb92e001f21987e9f21987eb92f001f41987e9f41987eb903001f02987e9f02987eb90400"
    "1f22987e9f22987eb905001f42987e9f42987eb930001f03987e9f03987eb931001f23987e9f23"
    "987eb932001f43987e9f43987eb906001f04987e9f04987eb907001f24987e9f24987eb908001f"
    "44987e9f44987eb933001f05987e9f05987eb934001f25987e9f25987eb935001f45987e9f4598"
    "7eb909001f06987e9f06987eb90a001f26987e9f26987eb90b001f46987e9f46987eb936001f07"
    "987e9f07987eb937001f27987e9f27987eb938001f47987e9f47987eb90c001f08987e9f08987e"
    "b90d001f28987e9f28987eb90e001f48987e9f48987eb939001f09987e9f09987eb93a001f2998"
    "7e9f29987eb93b001f49987e9f49987eb90f001f0a987e9f0a987eb910001f2a987e9f2a987eb9"
    "11001f4a987e9f4a987eb93c001f0b987e9f0b987eb93d001f2b987e9f2b987eb93e001f4b987e"
    "9f4b987eb912001f0c987e9f0c987eb913001f2c987e9f2c987eb914001f4c987e9f4c987eb93f"
    "001f0d987e9f0d987eb940001f2d987e9f2d987eb941001f4d987e9f4d987eb915001f0e987e9f"
    "0e987eb916001f2e987e9f2e987eb917001f4e987e9f4e987eb942001f0f987e9f0f987eb94300"
    "1f2f987e9f2f987eb944001f4f987e9f4f987eb918001f10987e9f10987eb919001f30987e9f30"
    "987eb91a001f50987e9f50987eb945001f11987e9f11987eb946001f31987e9f31987eb947001f"
    "51987e9f51987eb91b001f12987e9f12987eb91c001f32987e9f32987eb91d001f52987e9f5298"
    "7eb948001f13987e9f13987eb949001f33987e9f33987eb94a001f53987e9f53987eb91e001f14"
    "987e9f14987eb91f001f34987e9f34987eb920001f54987e9f54987eb94b001f15987e9f15987e"
    "b94c001f35987e9f35987eb94d001f55987e9f55987eb921001f16987e9f16987eb922001f3698"
    "7e9f36987eb923001f56987e9f56987eb94e001f17987e9f17987eb94f001f37987e9f37987eb9"
    "50001f57987e9f57987eb924001f18987e9f18987eb925001f38987e9f38987eb926001f58987e"
    "9f58987eb951001f19987e9f19987eb952001f39987e9f39987eb953001f59987e9f59987eb927"
    "001f1a987e9f1a987eb928001f3a987e9f3a987eb929001f5a987e9f5a987eb954001f1b987e9f"
    "1b987eb955001f3b987e9f3b987eb956001f5b987e9f5b987eb92a001f1c987e9f1c987eb92b00"
    "1f3c987e9f3c987eb92c001f5c987e9f5c987eb957001f1d987e9f1d987eb958001f3d987e9f3d"
    "987eb959001f5d987e9f5d987e6000002d005a008700b400e1000e013b01"
)
HOOK_SYMBOLS = {
    "redirect_hook": 0x00,
    "width_hook": 0x44,
    "dte_hook": 0x63,
    "draw_hook": 0x79,
    "line_hook": 0x8F,
    "page_hook": 0xD1,
    "transfer_hook": 0x143,
    "choice_hook": 0x108,
}
HOOKS = HookProgram(
    "Final Fantasy III hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="65816"
)
PATCH_NAME = "final-fantasy-iii-usa-arabic.bps"


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


def _call(hook: str, length: int) -> bytes:
    return nop_fill(jsl_long(HOOKS.symbol_address(hook)), length)


# The hooks are in another bank, so a site calls with JSL, filled with NOPs to
# its length (``cpu.m65816``); a hook returns with RTL to the site's end.
SITES = (
    Site(
        0xC07FDF,
        bytes.fromhex("a9018d6805"),
        _call("redirect_hook", 5),
        "GetDlgPtr's end (LDA #1; STA $0568): a translated message from its Arabic",
    ),
    Site(
        0xC08250,
        bytes.fromhex("a5bf1865c0"),
        _call("width_hook", 5),
        "UpdateDlgTextOneLine's word width (LDA $BF; CLC; ADC $C0): an Arabic line laid out",
    ),
    Site(
        0xC0828F,
        bytes.fromhex("a5bd3007"),
        _call("dte_hook", 4),
        "where a letter from $80 is a pair (LDA $BD; BMI): an Arabic glyph",
    ),
    Site(
        0xC084D0,
        bytes.fromhex("a6cdbfc08fc4"),
        _call("draw_hook", 6),
        "DrawDlgText's start (LDX $CD; LDA f:FontWidth,x): nothing drawn in an Arabic message",
    ),
    Site(
        0xC0851A,
        bytes.fromhex("a9ff85cd"),
        _call("line_hook", 4),
        "NewLine's start (LDA #$FF; STA $CD): an Arabic line's end",
    ),
    Site(
        0xC08554,
        bytes.fromhex("a9ff85cd"),
        _call("page_hook", 4),
        "NewPage's start (LDA #$FF; STA $CD): an Arabic page's end",
    ),
    Site(
        0xC08603,
        bytes.fromhex("a5c5f03a64c5"),
        _call("transfer_hook", 6),
        "TfrDlgTextGfx's start (LDA $C5; BEQ; STZ $C5): an Arabic line sent",
    ),
    Site(
        0xC0836D,
        bytes.fromhex("a5c1997005"),
        _call("choice_hook", 5),
        "a choice's mark (LDA $C1; STA $0570,y): its cursor at the line's right in Arabic",
    ),
)
# Bytes the hooks rely on without replacing them.
ANCHORS = {
    # GetDlgPtr's RTS after its site.
    0xC07FE4: bytes.fromhex("60"),
    # UpdateDlgTextOneLine after the width: the overflow check, NewLine, the buffer.
    0xC08255: bytes.fromhex("b004c5c89004201a8560a5cf3021"),
    # After the pair check: the command check, a letter, then the pair's letters
    # (JMP _8466), and _8466 itself (AND #$7F; ASL; TAY).
    0xC08293: bytes.fromhex("c920901e4c5a844c6684"),
    0xC08466: bytes.fromhex("297f0aa8"),
    # DrawDlgText after its site (CLC; ADC $BF; CMP $C8; BCC; JSR NewLine; RTS)
    # and its RTS.
    0xC084D6: bytes.fromhex("1865bfc5c89004201a8560"),
    0xC08519: bytes.fromhex("60"),
    # NewLine after its site (STZ $CE; JSR LoadLetterGfx; JSR DrawLetter; JSR
    # CopyDlgTextToBuf; LDA #4; STA a:$00BF) and its RTS.
    0xC0851E: bytes.fromhex("64ce208a8920d3882042 86a9048dbf00".replace(" ", "")),
    0xC08553: bytes.fromhex("60"),
    # NewPage the same, and its RTS.
    0xC08558: bytes.fromhex("64ce208a8920d38820428 6a9048dbf00".replace(" ", "")),
    0xC0857D: bytes.fromhex("60"),
    # The choice's mark after its site (SEP #$20; LDA #$FF; STA $BD; INC $056F;
    # JMP _845a).
    0xC08372: bytes.fromhex("7be220a9ff85bdee6f054c5a84"),
    # TfrDlgTextGfx after its site: the engine's cell sent (STZ $420B; LDA #$80;
    # STA $2115; REP #$21; LDA $C3; ADC #$3800; STA $2116), and its RTS.
    0xC08609: bytes.fromhex("9c0b42a9808d1521c221a5c36900388d1621"),
    0xC08641: bytes.fromhex("60"),
}


@dataclass(frozen=True, slots=True)
class Ff6ArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: Ff6Font
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _read(rom: bytes, address: int, length: int) -> bytes:
    at = hirom_offset(address)
    return bytes(rom[at : at + length])


def verify_rom(rom: bytes) -> None:
    """The header (3 MiB, HiROM, a size of 4 MiB) and every byte the overlay replaces
    or relies on."""
    if len(rom) != ROM_SIZE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"The ROM is {len(rom)} bytes, not {ROM_SIZE}"
        )
    if rom[MAP_MODE_BYTE] != MAP_MODE or rom[ROM_SIZE_BYTE] != ROM_SIZE_CODE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The ROM's header is not a 4 MiB HiROM's"
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    verify_bytes(rom, expected, offset=hirom_offset, what="the ROM")


def _verify_source(rom: bytes, message: Ff6Message) -> bytes:
    """The message's English bytes, its end included, as pinned: its hash and, where
    pinned, its commands."""
    try:
        data = message_at(rom, message.number).data
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{message.key}: {exc}"
        ) from exc
    if source_digest(data) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.number} differs from the pinned text",
        )
    if message.source_skeleton is not None and command_skeleton(data) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.number} has different commands than pinned",
        )
    return data


def source_skeletons(rom: bytes, translated: Sequence[Ff6Message]) -> dict[str, tuple[str, ...]]:
    """Every original's commands (``command_skeleton``), verified, by entry id."""
    return {message.key: command_skeleton(_verify_source(rom, message)) for message in translated}


# ---------------------------------------------------------------------------
# Encoding and fonts


def messages_characters(translated: Sequence[Ff6Message], names: Mapping[str, str]) -> set[str]:
    used: set[str] = set()
    for message in translated:
        used |= message_characters(message.notation)
    for text in names.values():
        used |= set(paint_text(text))
    return used


def encode_names(
    names: Mapping[str, str], encoder: Ff6ArabicEncoder
) -> dict[str, tuple[bytes, int]]:
    """Every character's name in the message's codes with its width, by entry."""
    return {key: encode_name(encoder, key, names[key]) for key in NAME_KEYS}


def name_widths(encoded_names: Mapping[str, tuple[bytes, int]]) -> dict[int, int]:
    """The names' widths by the name's code, for the encoder's layout."""
    return {NAME_FIRST + number: encoded_names[key][1] for number, key in enumerate(NAME_KEYS)}


def names_by_code(encoded_names: Mapping[str, tuple[bytes, int]]) -> dict[int, bytes]:
    return {NAME_FIRST + number: encoded_names[key][0] for number, key in enumerate(NAME_KEYS)}


def encode_messages(
    translated: Sequence[Ff6Message],
    encoder: Ff6ArabicEncoder,
    skeletons: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[str, EncodedMessage]:
    """Every message held against its original's commands, then encoded.

    The commands are the ROM's (``skeletons``, from ``source_skeletons``) or,
    without the ROM, those pinned in the script, where they are.
    """
    encoded: dict[str, EncodedMessage] = {}
    for message in translated:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        skeleton = message.source_skeleton if skeletons is None else skeletons[message.key]
        if skeleton is not None:
            validate_command_skeleton(skeleton, message.notation)
        encoded[message.key] = encoder.encode(message.notation)
    numbers = [message.number for message in translated]
    if len(set(numbers)) != len(numbers):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one message")
    return encoded


def data_writes(
    translated: Sequence[Ff6Message],
    encoded: Mapping[str, EncodedMessage],
    names: Mapping[str, tuple[bytes, int]],
    font: Ff6Font,
) -> dict[int, bytes]:
    """What the overlay writes into the added banks, by address.

    The Arabic messages follow each other from ``ARABIC_TEXT``; one that would
    cross a bank, or end on a bank's last byte (so that no message's address has
    ``ENGLISH``'s low word), starts the next bank. The table has an entry a
    message number: the Arabic's address, or ``ENGLISH``.
    """
    entries = bytearray(ENGLISH.to_bytes(MESSAGE_ENTRY, "little") * DLG_COUNT)
    text = bytearray()
    for message in translated:
        data = encoded[message.key].data
        if len(text) % BANK + len(data) >= BANK:
            text += bytes((EXPANSION_FILL,)) * (BANK - len(text) % BANK)
        address = ARABIC_TEXT + len(text)
        if address + len(data) > ARABIC_TEXT_END:
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW, "The Arabic messages do not fit their banks"
            )
        at = message.number * MESSAGE_ENTRY
        entries[at : at + MESSAGE_ENTRY] = address.to_bytes(MESSAGE_ENTRY, "little")
        text += data
    table = bytearray()
    for key in NAME_KEYS:
        entry, _ = names[key]
        if len(entry) >= NAME_STRIDE:
            raise ClassicRetroError(ErrorCode.TEXT_BOX_OVERFLOW, f"{key}: the name is too long")
        table += entry + bytes((NAME_END,)) * (NAME_STRIDE - len(entry))
    widths, addresses, glyphs = glyph_table(font, GLYPHS, GLYPHS_END - GLYPHS)
    return {
        WIDTHS: widths,
        GLYPH_ADDRESSES: addresses,
        NAMES: bytes(table),
        MESSAGES: bytes(entries),
        GLYPHS: glyphs,
        ARABIC_TEXT: bytes(text),
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


def _encoders(
    font_path: Path, translated: Sequence[Ff6Message], names: Mapping[str, str]
) -> tuple[Ff6Font, Ff6ArabicEncoder, dict[str, tuple[bytes, int]]]:
    """The font of the used characters, the names encoded, and the encoder that
    knows their widths."""
    used = messages_characters(translated, names)
    glyph_map = ff6_glyph_codes(used)
    font = build_ff6_font(font_path, glyph_map, used)
    encoded_names = encode_names(names, Ff6ArabicEncoder(glyph_map, font))
    return font, Ff6ArabicEncoder(glyph_map, font, name_widths(encoded_names)), encoded_names


def build_ff6_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    translated: tuple[Ff6Message, ...] | None = None,
    names: Mapping[str, str] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> Ff6ArabicBuild:
    """Build the Arabic ROM and its BPS patch from the original.

    ``translated``, ``names`` and ``verify_identity`` exist for synthetic tests; a
    real build always uses the pinned translation against the pinned ROM.
    """
    if verify_identity:
        verify_usa_image(rom)
    verify_rom(rom)
    translated = translated or ff6_arabic_messages(translations)
    names = names if names is not None else ff6_arabic_names(translations)
    skeletons = source_skeletons(rom, translated)

    font, encoder, encoded_names = _encoders(font_path, translated, names)
    encoded = encode_messages(translated, encoder, skeletons)

    output = bytearray(rom) + bytes((EXPANSION_FILL,)) * (EXPANDED_SIZE - len(rom))
    writes = {HOOK_ADDRESS: HOOK_CODE, **data_writes(translated, encoded, encoded_names, font)}
    for address, data in writes.items():
        at = hirom_offset(address)
        output[at : at + len(data)] = data
    for site in SITES:
        at = hirom_offset(site.address)
        output[at : at + len(site.patched)] = site.patched
    checksum = set_checksum(output)
    result = bytes(output)
    _verify_output(result, rom, writes, translated, encoded)
    patch = create_bps(rom, result)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, result, patch),
        "messages": {
            message.key: {
                "number": message.number,
                "bytes": len(encoded[message.key].data),
                "pages": [
                    [line.width for line in page] for page in encoded[message.key].pages or ()
                ],
                # The original's commands, as the script pins them.
                "source_skeleton": list(skeletons[message.key]),
            }
            for message in translated
        },
        "names": {key: encoded_names[key][1] for key in NAME_KEYS},
        "arabic_glyphs": len(font.glyphs),
        "font_size": font.font_size,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_address": f"${HOOK_ADDRESS:06X}",
        "hook_bytes": len(HOOK_CODE),
        "glyph_bytes": len(writes[GLYPHS]),
        "arabic_message_bytes": sum(len(encoded[message.key].data) for message in translated),
        "checksum": f"{checksum:04X}",
    }
    return Ff6ArabicBuild(rom=result, patch=patch, font=font, report=report)


def read_message_table(rom: bytes) -> dict[int, int]:
    """The translated messages as the hooks find them: by number, the address of the
    Arabic of every message whose entry is not ``ENGLISH``."""
    found: dict[int, int] = {}
    at = hirom_offset(MESSAGES)
    for number in range(DLG_COUNT):
        address = int.from_bytes(rom[at : at + MESSAGE_ENTRY], "little")
        if address & 0xFFFF != ENGLISH & 0xFFFF:
            found[number] = address
        at += MESSAGE_ENTRY
    return found


def read_arabic_message(rom: bytes, address: int) -> bytes:
    """An Arabic message's bytes, its end included, as the hooks read them: from its
    address, a command with its own byte, to its end within its bank."""
    if not ARABIC_TEXT <= address < ARABIC_TEXT_END:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, f"${address:06X} is not in the Arabic's banks"
        )
    start = at = hirom_offset(address)
    end = hirom_offset(address | 0xFFFF) + 1
    while at < end:
        code = rom[at]
        at += byte_length(code)
        if code == END:
            return bytes(rom[start:at])
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED, f"The Arabic message at ${address:06X} has no end"
    )


def _verify_output(
    output: bytes,
    original: bytes,
    writes: Mapping[int, bytes],
    translated: Sequence[Ff6Message],
    encoded: Mapping[str, EncodedMessage],
) -> None:
    """Everything written reads back, only the sites, the header and the added banks
    changed, and the checksum holds."""
    if len(output) != EXPANDED_SIZE or output[ROM_SIZE_BYTE] != ROM_SIZE_CODE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ROM is not 4 MiB")
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
        WIDTHS: "The widths",
        GLYPH_ADDRESSES: "The glyphs' addresses",
        NAMES: "The names",
        MESSAGES: "The table of messages",
        GLYPHS: "The glyphs",
        ARABIC_TEXT: "The Arabic text",
    }
    for address, data in writes.items():
        if _read(output, address, len(data)) != data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{names[address]} does not read back"
            )
    table = read_message_table(output)
    if sorted(table) != sorted(message.number for message in translated):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The table of messages does not read back with the translated ones",
        )
    for message in translated:
        data = read_arabic_message(output, table[message.number])
        if data != encoded[message.key].data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: the Arabic message does not read back through the table",
            )
        if command_skeleton(data) != notation_skeleton(message.notation):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: the Arabic message read back has other commands",
            )
    # The original's extent is compared; the added bank was read back above.
    allowed = [(at := hirom_offset(site.address), at + len(site.patched)) for site in SITES]
    allowed += [(CHECKSUM, CHECKSUM + 4)]
    verify_untouched(original, output, allowed, what="The ROM")
    (checksum,) = struct.unpack_from("<H", output, CHECKSUM + 2)
    if sum(output) & 0xFFFF != checksum:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header's checksum is wrong")


# ---------------------------------------------------------------------------
# Without the ROM


def check_ff6_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, draw and lay out every
    message and name."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    translated = ff6_arabic_messages(translations)
    names = ff6_arabic_names(translations)
    if font_path is not None:
        font, encoder, encoded_names = _encoders(font_path, translated, names)
    else:
        font = None
        encoder = Ff6ArabicEncoder(ff6_glyph_codes(messages_characters(translated, names)))
        encoded_names = encode_names(names, encoder)
    encoded = encode_messages(translated, encoder)
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    if font is not None and text_preview_path is not None:
        by_code = names_by_code(encoded_names)
        messages_sheet(
            [
                (message.key, message_preview(encoded[message.key], font, by_code))
                for message in translated
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(translated),
        "keys": [message.key for message in translated],
        "names": {key: len(encoded_names[key][0]) for key in NAME_KEYS},
        "laid_out": font is not None,
        "encoded_bytes": sum(len(result.data) for result in encoded.values()),
        "arabic_characters": len(messages_characters(translated, names) - {" "}),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["arabic_glyphs"] = len(font.glyphs)
        report["name_widths"] = {key: encoded_names[key][1] for key in NAME_KEYS}
        report["pages"] = {key: len(result.pages or ()) for key, result in encoded.items()}
    return report


def encode_ff6_arabic_message(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one message in notation; with a font, each page's lines' widths.

    Its codes are those of its own characters; a name is reckoned as wide as
    the translation's.
    """
    names = ff6_arabic_names()
    used = message_characters(text) | {c for name in names.values() for c in paint_text(name)}
    glyph_map = ff6_glyph_codes(used)
    if font_path is not None:
        font = build_ff6_font(font_path, glyph_map, used)
        encoded_names = encode_names(names, Ff6ArabicEncoder(glyph_map, font))
        encoder = Ff6ArabicEncoder(glyph_map, font, name_widths(encoded_names))
    else:
        encoder = Ff6ArabicEncoder(glyph_map)
    result = encoder.encode(text)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.pages is not None:
        payload["pages"] = [[line.width for line in page] for page in result.pages]
    return payload


def write_build_outputs(
    build: Ff6ArabicBuild, out_dir: Path, *, rom_name: str | None
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
    translated: tuple[Ff6Message, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    pairs = dte_pairs(rom)
    translated = translated or ff6_arabic_messages(translations)
    return {
        message.key: message_notation(_verify_source(rom, message), pairs) for message in translated
    }


def extract_skeletons(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    translated: tuple[Ff6Message, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Every pinned original's commands, verified, by entry id: what a maintainer pins
    as ``source_skeleton`` in the script, so the translations are checked without the
    ROM. The build's report carries the same."""
    if verify_identity:
        verify_usa_image(rom)
    return source_skeletons(rom, translated or ff6_arabic_messages(translations))


_ = NAME_COUNT
