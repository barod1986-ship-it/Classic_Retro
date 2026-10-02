"""Arabic ROM overlay for *Final Fantasy II* (USA, Rev 1): the opening's six messages.

The ROM is the No-Intro dump (SHA-256 below), 1 MiB mapped as LoROM, whose
banks $00 to $1F are its 32 KiB pieces at $8000-$FFFF; the overlay patches the
user's and ships as a BPS patch of it. The overlay:

1. verifies the ROM: every byte of the text engine it replaces or relies on
   (``SITES``, ``ANCHORS``: the engine's code the hooks go back to), that the
   font's free tiles are blank (``PAIR_CODES``: the tiles of the pair codes),
   and each translated message's original (its bank and offset, the SHA-256 of
   its bytes and, where pinned, its commands);
2. adds a second MiB to the ROM (``EXPANDED_SIZE``, ``EXPANSION_FILL``), banks
   $20 to $3F, and says so in the header;
3. draws the translation's glyphs (``engines.ff4_arabic``), holds each
   translation's commands against its original's (``command_skeleton``:
   everything but the layout the encoder writes itself), encodes each message
   and the characters' names, and writes into the added banks the hooks
   (``ff4_arabic_hooks.s``), the first code of a top half (``TOP_FIRST``), the
   list that sends each translated message to its Arabic (``REDIRECTS``), the
   Arabic tiles of the letters' codes (``LETTER_TILES``), the names
   (``NAMES``) and the Arabic messages (``ARABIC_TEXT``, bank $21), and into the
   font's blank tiles the glyphs of the pair codes;
4. puts a long jump to a hook in place of seven places of the engine (``SITES``);
5. sets the header's checksum;
6. reads everything back from the image before accepting it: the hooks, the
   sites, the list, the tiles, the names, and each Arabic message through the
   list as the hooks find it (``read_redirects``, ``read_arabic_message``), with
   the translation's commands; and proves nothing else changed.

The English messages stay where they were, as they were: a translated one is
read from its Arabic instead, and the hooks tell an Arabic message by its bank
and offset.

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
from classic_retro.cpu.m65816 import jml_long, nop_fill
from classic_retro.engines.ff4 import (
    CLOSE,
    END,
    FONT,
    FONT_TILE_BYTES,
    NAME_CELLS,
    byte_length,
    command_skeleton,
    dte_pairs,
    lorom_offset,
    message_at,
    message_notation,
)
from classic_retro.engines.ff4_arabic import (
    LETTER_CODES,
    PAIR_CODES,
    SPACE_TILE,
    TILE_BYTES,
    EncodedMessage,
    Ff4ArabicEncoder,
    TileSet,
    build_ff4_font,
    encode_name,
    ff4_glyph_codes,
    font_preview,
    message_characters,
    message_preview,
    messages_sheet,
    notation_skeleton,
    paint_text,
    tile_set,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.patching.overlay import verify_bytes, verify_empty, verify_untouched
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.ff4_arabic_script import (
    NAME_KEYS,
    Ff4Message,
    ff4_arabic_messages,
    ff4_arabic_names,
)

# No-Intro "Final Fantasy II (USA) (Rev 1)".
ROM_SHA256 = "414bacc05a18a6137c0de060b4094ab6d1b75105342b0bb36a42e45d945a0e4d"
ROM_SIZE = 1024 * 1024
IMAGE = ImageSpec("Final Fantasy II (USA, Rev 1)", ROM_SHA256, ROM_SIZE, base=0)
HEADER = 0x7FC0
ROM_SIZE_BYTE = HEADER + 0x17  # 2 ** n KiB
CHECKSUM = HEADER + 0x1C  # the complement, then the checksum
# The added MiB: banks $20-$3F, 0xFF where the overlay writes nothing.
EXPANDED_SIZE = 2 * ROM_SIZE
EXPANSION_FILL = 0xFF
ROM_SIZE_CODES = {ROM_SIZE: 0x0A, EXPANDED_SIZE: 0x0B}

# The hooks and the data, in the added banks: the hooks first; a byte with the
# first code of a top half; the list of translated messages (5 bytes each: the
# bank, the message's offset, its Arabic's offset; $FF ends it); the Arabic
# tiles of the letters' codes $42-$75, 16 bytes each; the names, NAME_STRIDE
# bytes each; then the Arabic messages, from bank $21, an offset each below
# $8000, which is all the engine's index reaches.
HOOK_ADDRESS = 0x208000
HOOK_SOURCE = Path(__file__).with_name("ff4_arabic_hooks.s")
TOP_FIRST = 0x208400
REDIRECTS = 0x208500
REDIRECT_ENTRY = 5
LETTER_TILES = 0x208800
NAMES = 0x208C00
NAME_STRIDE = 48
NAME_COUNT = 14
ARABIC_TEXT = 0x218000
ARABIC_TEXT_END = 0x220000
# The font's own tiles of the letters' codes, which the hook puts back for English.
LATIN_TILES = FONT + LETTER_CODES[0] * FONT_TILE_BYTES

# ca65 --cpu 65816 ff4_arabic_hooks.s; ld65 at $20:8000
HOOK_CODE = bytes.fromhex(
    "a00000843da9ff8fd0d07ea200009f00d07ee8e06800d0f6a5ddc903f032a20000bf008520c9ff"
    "f027c5ddd01cc220bf018520cd7207d00fbf0385208d7207e220a90385dd8009e220e8e8e8e8e8"
    "80d15c24b200ae7207a5ddc903d008bf0080215cdbb200a5ddd0045cc5b2005cccb20048a5ddc9"
    "03f00a6838e9800aaa5ce1b20068cf00842090088fd0d07e5c88b200997407a5ddc903d00fbbaf"
    "d0d07e9f00d07ea9ff8fd0d07ea43dc8843d5c88b200a5ddc903f009bd0015c9ff5c21b300c220"
    "8a0a0a0aaae220bf008c20c9fff025cf00842090078fd0d07ee880eb997407dabbafd0d07e9f00"
    "d07ea9ff8fd0d07efac8e880d3843d5c88b200a90185eda5ddc903f0045ca8b200c220a98d078f"
    "d2d07ea900008fd4d07ee220a9048fd6d07ec220afd2d07eaae220a00000bd0000995e08bf8cc8"
    "7e994408cac8c01a00d0ec207782c220afd4d07eaae220a00000b95e089f00d17eb944089f80d1"
    "7ee8c8c01a00d0ebc220afd4d07e18691a008fd4d07eafd2d07e18691a008fd2d07ee220afd6d0"
    "7e3a8fd6d07ed0955ca8b200a5edd0045c63b500a5ddc903f00ca220f4a90a2040825c64b500a2"
    "0088a92020408264eda5ba290318692c8513a9038512a2000086149c15219c0b42a9188d0143a9"
    "7e8d04439c0043a9048511c220a514186980d18d0243e220a6128e1621a21a008e0543a9018d0b"
    "42206a829c0b42c220a514186900d18d0243e220a6128e1621a21a008e0543a9018d0b42206a82"
    "a513c930d004a92c8513c220a51418691a008514e220c611d0a35ce7b5009c0b428e02438d0443"
    "a9808d1521a210228e1621a9018d0043a9188d0143a240038e0543a9018d0b4260c220a5121869"
    "20008512e22060a20000e01a00b03dbd5e0820bd8290329bc8c01a00b008b95e0820bd82b0f25a"
    "88988fd1d07e8acfd1d07eb012bd5e0848b95e089d5e0868995e08e88880e2fa80c1e880be60c9"
    "21900ec9429008c9799006c98ab00238601860"
)
HOOK_SYMBOLS = {
    "parse_hook": 0x00,
    "byte_hook": 0x54,
    "dte_hook": 0x71,
    "store_hook": 0x91,
    "name_hook": 0xB2,
    "page_hook": 0xFD,
    "transfer_hook": 0x192,
}
HOOKS = HookProgram(
    "Final Fantasy II hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="65816"
)
PATCH_NAME = "final-fantasy-ii-usa-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


def _jump(address: int, hook: str, length: int) -> bytes:
    return nop_fill(jml_long(HOOKS.symbol_address(hook)), length)


# The hooks are in another bank, so a site jumps with JML, filled with NOPs to
# its length (``cpu.m65816``).
SITES = (
    Site(
        0x00B21F,
        bytes.fromhex("a00000843d"),
        _jump(0x00B21F, "parse_hook", 5),
        "DecodeDlgText's start (LDY #0; STY $3D): a translated message from its Arabic",
    ),
    Site(
        0x00B280,
        bytes.fromhex("997407a43dc8843d"),
        _jump(0x00B280, "store_hook", 8),
        "where a letter is stored (STA $0774,y; LDY $3D; INY; STY $3D): an Arabic glyph's top",
    ),
    Site(
        0x00B2BE,
        bytes.fromhex("ae7207a5ddd007"),
        _jump(0x00B2BE, "byte_hook", 7),
        "GetByte's start (LDX $0772; LDA $DD; BNE): the next byte of an Arabic message",
    ),
    Site(
        0x00B2DC,
        bytes.fromhex("38e9800aaa"),
        _jump(0x00B2DC, "dte_hook", 5),
        "DecodeDTE's start (SEC; SBC #$80; ASL; TAX): a pair code as an Arabic glyph's half",
    ),
    Site(
        0x00B31C,
        bytes.fromhex("bd0015c9ff"),
        _jump(0x00B31C, "name_hook", 5),
        "the name command's letter (LDA $1500,x; CMP #$FF): a name in Arabic",
    ),
    Site(
        0x00B2A4,
        bytes.fromhex("a90185ed"),
        _jump(0x00B2A4, "page_hook", 4),
        "DecodeDlgText, a page decoded (LDA #1; STA $ED): an Arabic page's rows laid out",
    ),
    Site(
        0x00B55F,
        bytes.fromhex("a5edd001"),
        _jump(0x00B55F, "transfer_hook", 4),
        "TfrDlgText's start (LDA $ED; BNE): the letters' tiles and the Arabic rows",
    ),
)
# Bytes the hooks rely on without replacing them.
ANCHORS = {
    # DecodeDlgText's loop (JSR GetByte), and what follows a stored code: the
    # source on, the row check, back to the loop.
    0x00B224: bytes.fromhex("20beb2"),
    0x00B288: bytes.fromhex("ae7207e88e7207a43dc06800f0034c24b2"),
    # DecodeDlgText after a page is decoded: the blank row filled, its RTS.
    0x00B2A8: bytes.fromhex("a20000a9ff9d4408e8e03400d0f760"),
    # GetByte after its site: the English banks, then its RTS.
    0x00B2C5: bytes.fromhex("bf0083114cdbb2c901d007bf0084104cdbb2bf00a71360"),
    # DecodeDTE after its site: the pair's letters from DTETbl.
    0x00B2E1: bytes.fromhex("bf009713997407"),
    # The name command after its site, to its end (STY $3D; JMP _b288).
    0x00B321: bytes.fromhex("f010997407c8e8e607a507c906f0034c1cb3843d4c88b2"),
    # TfrDlgText after its site: its RTS (where the hook goes back to when there
    # is nothing to send), its transfer as the hook repeats it, and its end
    # (INC $BA; RTS).
    0x00B563: bytes.fromhex(
        "6064eda5ba29038513a9038512a51318692c8513a2740786149c1521200c899c0043a9048511"
        "a244088e0243a6128e1621a21a008e0543201889a5121869208512a513690085139c0b42a614"
        "8e0243a6128e1621a21a008e0543201889a5121869208512a5136900c930d002a92c8513a514"
        "18691a8514a51569008515c611f0034c89b5e6ba60"
    ),
}


@dataclass(frozen=True, slots=True)
class Ff4ArabicBuild:
    rom: bytes
    patch: BpsPatch
    tiles: TileSet
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _read(rom: bytes, address: int, length: int) -> bytes:
    at = lorom_offset(address)
    return bytes(rom[at : at + length])


def _tile_slot(code: int) -> int:
    """The ROM offset of a code's tile in the font."""
    return lorom_offset(FONT) + code * FONT_TILE_BYTES


def verify_rom(rom: bytes) -> None:
    """Every byte the overlay replaces or relies on, and the pair codes' tiles blank."""
    if len(rom) != ROM_SIZE or rom[ROM_SIZE_BYTE] != ROM_SIZE_CODES[ROM_SIZE]:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"The ROM is {len(rom)} bytes, not the {ROM_SIZE} of its header",
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    verify_bytes(rom, expected, offset=lorom_offset, what="the ROM")
    for code in PAIR_CODES:
        verify_empty(
            rom,
            _tile_slot(code),
            _tile_slot(code + 1),
            0x00,
            what=f"The font's tile {code:#04x}",
        )


def _verify_source(rom: bytes, message: Ff4Message) -> bytes:
    """The message's English bytes, its end included, as pinned: its hash and, where
    pinned, its commands."""
    try:
        data = message_at(rom, message.bank, message.offset).data
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{message.key}: {exc}"
        ) from exc
    if source_digest(data) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the message at {message.offset:#06x} of bank {message.bank} "
            "differs from the pinned text",
        )
    if message.source_skeleton is not None and command_skeleton(data) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the message at {message.offset:#06x} of bank {message.bank} "
            "has different commands than pinned",
        )
    return data


def source_skeletons(rom: bytes, translated: Sequence[Ff4Message]) -> dict[str, tuple[str, ...]]:
    """Every original's commands (``command_skeleton``), verified, by entry id."""
    return {message.key: command_skeleton(_verify_source(rom, message)) for message in translated}


# ---------------------------------------------------------------------------
# Encoding and fonts


def messages_characters(translated: Sequence[Ff4Message], names: Mapping[str, str]) -> set[str]:
    used: set[str] = set()
    for message in translated:
        used |= message_characters(message.notation)
    for text in names.values():
        used |= set(paint_text(text))
    return used


def encode_messages(
    translated: Sequence[Ff4Message],
    encoder: Ff4ArabicEncoder,
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
    places = [(message.bank, message.offset) for message in translated]
    if len(set(places)) != len(places):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one message")
    return encoded


def encode_names(names: Mapping[str, str], encoder: Ff4ArabicEncoder) -> dict[str, bytes]:
    """Every character's name in the message's codes, held to its cells."""
    return {key: encode_name(encoder, key, names[key]) for key in NAME_KEYS}


@dataclass(frozen=True, slots=True)
class MessageLayout:
    """The list of translated messages, and the Arabic text of their bank."""

    redirects: bytes
    text: bytes


def lay_out_messages(
    translated: Sequence[Ff4Message], encoded: Mapping[str, EncodedMessage]
) -> MessageLayout:
    """The list and the Arabic messages in their bank: one after another from
    ``ARABIC_TEXT``, each by its offset there; refused where the bank or the list
    cannot hold them. It needs only the text, so the check without the ROM refuses
    what the build would."""
    redirects = bytearray()
    text = bytearray()
    for message in translated:
        data = encoded[message.key].data
        offset = len(text)
        if ARABIC_TEXT + offset + len(data) > ARABIC_TEXT_END:
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW, "The Arabic messages do not fit their bank"
            )
        redirects += struct.pack("<BHH", message.bank, message.offset, offset)
        text += data
    redirects.append(0xFF)
    if len(redirects) > LETTER_TILES - REDIRECTS:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW, f"{len(translated)} messages do not fit the list"
        )
    return MessageLayout(bytes(redirects), bytes(text))


def name_table(names: Mapping[str, bytes]) -> bytes:
    """The names in the game's order, ``NAME_STRIDE`` bytes each, filled with $FF;
    refused where a name leaves no room for its end."""
    table = bytearray()
    for key in NAME_KEYS:
        entry = names[key]
        if len(entry) >= NAME_STRIDE:
            raise ClassicRetroError(ErrorCode.TEXT_BOX_OVERFLOW, f"{key}: the name is too long")
        table += entry + b"\xff" * (NAME_STRIDE - len(entry))
    return bytes(table)


def data_writes(
    translated: Sequence[Ff4Message],
    encoded: Mapping[str, EncodedMessage],
    names: Mapping[str, bytes],
    tiles: TileSet,
) -> dict[int, bytes]:
    """What the overlay writes into the added banks and the font, by address."""
    layout = lay_out_messages(translated, encoded)
    letters = b"".join(tiles.tiles.get(code, SPACE_TILE) for code in LETTER_CODES)
    table = name_table(names)
    font = {
        FONT + code * FONT_TILE_BYTES: tile
        for code, tile in sorted(tiles.tiles.items())
        if code in PAIR_CODES
    }
    return {
        TOP_FIRST: bytes((tiles.top_first,)),
        REDIRECTS: layout.redirects,
        LETTER_TILES: letters,
        NAMES: table,
        ARABIC_TEXT: layout.text,
        **font,
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


def build_ff4_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    translated: tuple[Ff4Message, ...] | None = None,
    names: Mapping[str, str] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> Ff4ArabicBuild:
    """Build the Arabic ROM and its BPS patch from the original.

    ``translated``, ``names`` and ``verify_identity`` exist for synthetic tests; a
    real build always uses the pinned translation against the pinned ROM.
    """
    if verify_identity:
        verify_usa_image(rom)
    verify_rom(rom)
    translated = translated or ff4_arabic_messages(translations)
    names = names if names is not None else ff4_arabic_names(translations)
    skeletons = source_skeletons(rom, translated)

    used = messages_characters(translated, names)
    font = build_ff4_font(font_path, used)
    tiles = tile_set(font, used)
    encoder = Ff4ArabicEncoder(tiles.codes, tiles)
    encoded = encode_messages(translated, encoder, skeletons)
    encoded_names = encode_names(names, encoder)

    output = bytearray(rom) + bytes((EXPANSION_FILL,)) * (EXPANDED_SIZE - len(rom))
    writes = {HOOK_ADDRESS: HOOK_CODE, **data_writes(translated, encoded, encoded_names, tiles)}
    for address, data in writes.items():
        at = lorom_offset(address)
        output[at : at + len(data)] = data
    for site in SITES:
        at = lorom_offset(site.address)
        output[at : at + len(site.patched)] = site.patched
    output[ROM_SIZE_BYTE] = ROM_SIZE_CODES[EXPANDED_SIZE]
    checksum = set_checksum(output)
    result = bytes(output)
    _verify_output(result, rom, writes, translated, encoded)
    patch = create_bps(rom, result)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, result, patch),
        "messages": {
            message.key: {
                "bank": message.bank,
                "offset": f"{message.offset:#06x}",
                "bytes": len(encoded[message.key].data),
                "pages": [[row.cells for row in page] for page in encoded[message.key].pages or ()],
                # The original's commands, as the script pins them.
                "source_skeleton": list(skeletons[message.key]),
            }
            for message in translated
        },
        "names": {key: encoder.cells(encoded_names[key]) for key in NAME_KEYS},
        "arabic_tiles": len(tiles.tiles),
        "top_first": f"{tiles.top_first:#04x}",
        "font_size": tiles.font_size,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_address": f"${HOOK_ADDRESS:06X}",
        "hook_bytes": len(HOOK_CODE),
        "arabic_message_bytes": sum(len(encoded[message.key].data) for message in translated),
        "checksum": f"{checksum:04X}",
    }
    return Ff4ArabicBuild(rom=result, patch=patch, tiles=tiles, report=report)


def read_redirects(rom: bytes) -> dict[tuple[int, int], int]:
    """The list of translated messages as the hooks read it: each message's bank and
    offset, and its Arabic's offset, to the $FF that ends it."""
    found: dict[tuple[int, int], int] = {}
    at = lorom_offset(REDIRECTS)
    while at + REDIRECT_ENTRY <= lorom_offset(LETTER_TILES):
        if rom[at] == 0xFF:
            return found
        bank, offset, arabic = struct.unpack_from("<BHH", rom, at)
        found[bank, offset] = arabic
        at += REDIRECT_ENTRY
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED, "The list of translated messages has no end"
    )


def read_arabic_message(rom: bytes, offset: int) -> bytes:
    """An Arabic message's bytes, its end included, as the hooks read them: from its
    offset in the Arabic's bank, a command with its own byte, to its end."""
    start = at = lorom_offset(ARABIC_TEXT + offset)
    end = lorom_offset(ARABIC_TEXT_END - 1) + 1
    while at < end:
        code = rom[at]
        at += byte_length(code)
        if code in (END, CLOSE):
            return bytes(rom[start:at])
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED, f"The Arabic message at {offset:#06x} has no end"
    )


def _verify_output(
    output: bytes,
    original: bytes,
    writes: Mapping[int, bytes],
    translated: Sequence[Ff4Message],
    encoded: Mapping[str, EncodedMessage],
) -> None:
    """Everything written reads back, only the sites, the font's blank tiles, the
    header and the added banks changed, and the checksum holds."""
    if len(output) != EXPANDED_SIZE or output[ROM_SIZE_BYTE] != ROM_SIZE_CODES[EXPANDED_SIZE]:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ROM is not 2 MiB")
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
        TOP_FIRST: "The first top code",
        REDIRECTS: "The list of translated messages",
        LETTER_TILES: "The letters' tiles",
        NAMES: "The names",
        ARABIC_TEXT: "The Arabic text",
    }
    for address, data in writes.items():
        if _read(output, address, len(data)) != data:
            what = names.get(address, f"The font's tile at ${address:06X}")
            raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, f"{what} does not read back")
    redirects = read_redirects(output)
    if list(redirects) != [(message.bank, message.offset) for message in translated]:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The list of translated messages does not read back in order",
        )
    for message in translated:
        data = read_arabic_message(output, redirects[message.bank, message.offset])
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
    # The original's extent is compared; the added banks were read back above.
    places = [(site.address, len(site.patched)) for site in SITES]
    places += [
        (address, len(data))
        for address, data in writes.items()
        if lorom_offset(address) < len(original)
    ]
    allowed = [(at := lorom_offset(address), at + size) for address, size in places]
    allowed += [(ROM_SIZE_BYTE, ROM_SIZE_BYTE + 1), (CHECKSUM, CHECKSUM + 4)]
    verify_untouched(original, output, allowed, what="The ROM")
    (checksum,) = struct.unpack_from("<H", output, CHECKSUM + 2)
    if sum(output) & 0xFFFF != checksum:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header's checksum is wrong")


# ---------------------------------------------------------------------------
# Without the ROM


def check_ff4_translations(
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
    translated = ff4_arabic_messages(translations)
    names = ff4_arabic_names(translations)
    used = messages_characters(translated, names)
    tiles = tile_set(build_ff4_font(font_path, used), used) if font_path else None
    encoder = Ff4ArabicEncoder(tiles.codes if tiles else ff4_glyph_codes(used), tiles)
    encoded = encode_messages(translated, encoder)
    encoded_names = encode_names(names, encoder)
    # The bank, the list and the names as the build fills them: with the tiles, the
    # build's own bytes; without, a code a letter, as the rest of the check reckons.
    lay_out_messages(translated, encoded)
    name_table(encoded_names)
    if tiles is not None and preview_path is not None:
        font_preview(tiles).save(preview_path)
    if tiles is not None and text_preview_path is not None:
        messages_sheet(
            [(message.key, message_preview(encoded[message.key], tiles)) for message in translated]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(translated),
        "keys": [message.key for message in translated],
        "names": {key: encoder.cells(encoded_names[key]) for key in NAME_KEYS},
        "laid_out": tiles is not None,
        "encoded_bytes": sum(len(result.data) for result in encoded.values()),
        "arabic_characters": len(used - {" "}),
    }
    if tiles is not None:
        report["font_size"] = tiles.font_size
        report["arabic_tiles"] = len(tiles.tiles)
        report["pages"] = {key: len(result.pages or ()) for key, result in encoded.items()}
    return report


def encode_ff4_arabic_message(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one message in notation; with a font, each page's rows' cells.

    Its codes are those of its own characters.
    """
    used = message_characters(text)
    tiles = tile_set(build_ff4_font(font_path, used), used) if font_path else None
    encoder = Ff4ArabicEncoder(tiles.codes if tiles else ff4_glyph_codes(used), tiles)
    result = encoder.encode(text)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.pages is not None:
        payload["pages"] = [[row.cells for row in page] for page in result.pages]
    return payload


def write_build_outputs(
    build: Ff4ArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.tiles).save(out_dir / "arabic_font_preview.png")
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
    translated: tuple[Ff4Message, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id; the
    names as the game's own table has them.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    pairs = dte_pairs(rom)
    translated = translated or ff4_arabic_messages(translations)
    return {
        message.key: message_notation(_verify_source(rom, message), pairs) for message in translated
    }


def extract_skeletons(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    translated: tuple[Ff4Message, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Every pinned original's commands, verified, by entry id: what a maintainer pins
    as ``source_skeleton`` in the script, so the translations are checked without the
    ROM. The build's report carries the same."""
    if verify_identity:
        verify_usa_image(rom)
    return source_skeletons(rom, translated or ff4_arabic_messages(translations))


_ = (TILE_BYTES, NAME_CELLS)
