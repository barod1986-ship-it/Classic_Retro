"""Arabic ROM overlay for *The Legend of Zelda: A Link to the Past* (USA): three messages.

The ROM is the No-Intro dump (SHA-256 below), 1 MiB mapped as LoROM, whose banks
$00 to $1F are its 32 KiB pieces at $8000-$FFFF; the overlay patches the user's
and ships as a BPS patch of it. The overlay:

1. verifies the ROM, every byte of the text engine it replaces or relies on
   (``SITES``, ``ANCHORS``: the engine's code where the hooks go back to or call,
   its tables of widths, lines and settings, its font's address), that the
   room of the hooks (``HOOK_ROOM_START`` to ``HOOK_ROOM_END``, free bytes of
   bank $0E) is empty, and each translated message's original (its number and
   the SHA-256 of its bytes);
2. adds a second MiB to the ROM (``EXPANDED_SIZE``, ``EXPANSION_FILL``), banks
   $20 to $3F, and says so in the header;
3. draws the translation's glyphs (``engines.alttp_arabic``), encodes each
   message and writes the hooks (``alttp_arabic_hooks.s``) into their room, and
   into the added banks the list that sends each translated message to its
   Arabic (``REDIRECTS``), the glyphs' widths and pixels and the Arabic messages;
4. puts a jump or call to a hook in place of four places of the engine
   (``SITES``);
5. sets the header's checksum.

The English messages stay where they were, as they were: a translated one is
parsed from its Arabic instead, and the hooks tell an Arabic message by its
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

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.alttp import (
    dictionary,
    lorom_address,
    lorom_offset,
    message_notation,
    messages,
)
from classic_retro.engines.alttp_arabic import (
    GLYPH_BYTES,
    SPACE_CODE,
    AlttpArabicEncoder,
    AlttpFont,
    EncodedMessage,
    alttp_glyph_codes,
    build_alttp_font,
    font_preview,
    message_characters,
    message_preview,
    messages_sheet,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.alttp_arabic_script import AlttpMessage, alttp_arabic_messages

# No-Intro "Legend of Zelda, The - A Link to the Past (USA)".
ROM_SHA256 = "66871d66be19ad2c34c927d6b14cd8eb6fc3181965b6e517cb361f7316009cfb"
ROM_SIZE = 1024 * 1024
IMAGE = ImageSpec("The Legend of Zelda: A Link to the Past (USA)", ROM_SHA256, ROM_SIZE, base=0)
HEADER = 0x7FC0
ROM_SIZE_BYTE = HEADER + 0x17  # 2 ** n KiB
CHECKSUM = HEADER + 0x1C  # the complement, then the checksum
# The added MiB: banks $20-$3F, 0xFF where the overlay writes nothing.
EXPANDED_SIZE = 2 * ROM_SIZE
EXPANSION_FILL = 0xFF
ROM_SIZE_CODES = {ROM_SIZE: 0x0A, EXPANDED_SIZE: 0x0B}

# The hooks: free bytes (0xFF) of bank $0E, the text engine's bank.
HOOK_ROOM_START = 0x0EEE21
HOOK_ROOM_END = 0x0EF400
HOOK_ADDRESS = 0x0EEE30
HOOK_SOURCE = Path(__file__).with_name("alttp_arabic_hooks.s")
# The data, in the added banks: the list of translated messages (5 bytes each:
# the message's number, its Arabic's address; $FFFF ends it), a width a code,
# 64 bytes a code, then the Arabic messages, from bank $21, none across a bank.
REDIRECTS = 0x208000
REDIRECT_ENTRY = 5
ARABIC_WIDTHS = 0x208800
ARABIC_FONT = 0x208900
CODES = 0x100
MESSAGES = 0x218000
MESSAGES_END = 0x400000

# ca65 --cpu 65816 alttp_arabic_hooks.s; ld65 at $0E:EE30
HOOK_CODE = bytes.fromhex(
    "c230a20000bf008020c9fffff00dcdf01cf0158a18690500aa80eae2209ce41c"
    "c220adf01c4ce7c4bf0280208504bf0380208505e220a9018de41cc220a97f7f"
    "8f00127fa00000bb8cd91c8cdd1ce220b704c967901bc980b017c97ff052c96a"
    "f01dc96cf0192047c5aed91cacdd1c80df9f00127fc88cdd1ce88ed91c80d148"
    "e00000f00bbfff117fc96bd003ca8007a96a9f00127fe88ed91c682047c5aed9"
    "1ca96b9f00127fe88ed91cacdd1c80a09f00127fe23060ade41cd0034c5ecb20"
    "bfefc230aed91cbf00127f29ff0048aabf00882029ff0020dbef2002f0680a0a"
    "0a0a0a0a186900898500e220a9208502c2202017f0eed91ce2306020bfefc230"
    "aed91ce86408bf00127f29ff00c96b00f00fa8b9dfca29ff001865088508e880"
    "e5daa50820dbef48aed91ce8bf00127f29ff00c96b00f03cda48a3052002f0a3"
    "0129f0000a8500a301290f0005000a0a0a0a186900808500e220a90e8502c220"
    "203cf068a8b9dfca29ff001863038303fae880b868fae88ed91ce23060ade41c"
    "29ff0018692100186dd01c8dd01c60c220ad2007f012ac2207b94acb8d2607b9"
    "50cb8d24079c2007e220608506ae2407bf30c27e29ff00186506e2209f31c27e"
    "c220e88e240729ff008506a9a80038e5066048290700850e684a4a4a0a0a0a0a"
    "186d2607850460a00000b7008506c8c8b7008508c8c8206cf0c02000d008a504"
    "186940018504c04000d0df60a00000b700482900ff850868eb2900ff8506c8c8"
    "206cf0c01000d00e981869f000a8a504186940018504c01001d0d460640a640c"
    "a60ef00b4606660a4608660ccad0f5a604e220a5071f00007f9f00007fa5091f"
    "01007f9f01007fa5061f10007f9f10007fa5081f11007f9f11007fa50b1f2000"
    "7f9f20007fa50d1f21007f9f21007fc220e8e8860460"
)
HOOK_SYMBOLS = {
    "parse_hook": 0x00,
    "draw_hook": 0xB7,
    "island_hook": 0xFB,
    "tilemap_hook": 0x17D,
}
HOOKS = HookProgram(
    "A Link to the Past hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="65816"
)
PATCH_NAME = "link-to-the-past-usa-arabic-opening.bps"

JMP = 0x4C
JSR = 0x20
NOP = 0xEA


def _short(opcode: int, target: int, length: int) -> bytes:
    """A jump or call within the bank, then NOPs to ``length`` bytes."""
    return bytes((opcode, target & 0xFF, target >> 8 & 0xFF)) + bytes((NOP,) * (length - 3))


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


SITES = (
    Site(
        0x0EC4E2,
        bytes.fromhex("c230adf01c"),
        _short(JMP, HOOKS.symbol_address("parse_hook"), 5),
        "RenderText_ParseMessage (REP #$30; LDA $1CF0): a translated message, from its Arabic",
    ),
    Site(
        0x0ECA09,
        bytes.fromhex("6bce"),
        struct.pack("<H", HOOKS.symbol_address("island_hook") & 0xFFFF),
        "the draw table's entry for $6A (RenderText_IgnoreThis): a name in an Arabic line",
    ),
    Site(
        0x0ECAD5,
        bytes.fromhex("205ecb"),
        _short(JSR, HOOKS.symbol_address("draw_hook"), 3),
        "RenderText_DrawSingleCharacter's JSR RenderText_PerformVWFing: an Arabic glyph",
    ),
    Site(
        0x0ED313,
        bytes.fromhex("add01c186921008dd01c"),
        _short(JSR, HOOKS.symbol_address("tilemap_hook"), 10),
        "RenderText_DrawACharacter's first row ($1CD0 + $21): a tile further right in Arabic",
    ),
)
# Bytes the hooks rely on without replacing them.
ANCHORS = {
    # RenderText_ParseMessage after its start, where an English message goes
    # on; RenderText_ExecuteCommand, and its entries for the name and a number.
    0x0EC4E7: bytes.fromhex("0a6df01caabfc0717f8504bfc2717f8506"),
    0x0EC547: bytes.fromhex("e231e96722818700"),
    0x0EC555: bytes.fromhex("b3c5"),
    0x0EC559: bytes.fromhex("67c6"),
    # The engine's settings for each message ($1CD0-$1CEF): $1CE4 starts at 0.
    0x0EC493: bytes.fromhex("bd5ad39dd01ce8e02090f5"),
    0x0ED36E: bytes.fromhex("00"),
    # The draw: a byte of the buffer, its bit 7 dropped, is a character below
    # $66; the table from $66; the character's draw and what follows it.
    0x0EC9DD: bytes.fromhex("aed91cbf00127f297f0038e96600"),
    0x0ECA01: bytes.fromhex("6cca"),
    0x0ECAB8: bytes.fromhex("c210aed91cbf00127fc959f007e230a90c8d2f01c230addd1c0aaae230"),
    0x0ECAD8: bytes.fromhex("add61c8dd51c60"),
    # RenderText_PerformVWFing: its widths, each line's first tile and pen, its
    # line change, pens, font, buffer and the lines' lower tiles.
    0x0ECADF: bytes.fromhex(
        "0606060606060606030606060706060606060607060707070706060606060606"
        "0606030506030706060606050606060707070706060406060606060606060307"
        "0604040608060606060608080807070707040808080808080804080808080808"
        "080804"
    ),
    0x0ECB4A: bytes.fromhex("0000a0024005000040008000"),
    0x0ECB5E: bytes.fromhex("e2308b4babc220ad2007f012ac2207b94acb8d2607b950cb8d24079c2007"),
    0x0ECB91: bytes.fromhex("ae2407187f30c27e9f31c27ee88e2407"),
    0x0ECBB2: bytes.fromhex("a90080850da00e840f"),
    0x0ECBF6: bytes.fromhex("bf00007f5942cb9f00007f"),
    0x0ECC50: bytes.fromhex("ad2607186950018508"),
    # RenderText_DrawACharacter after its site: 21 tiles a row.
    0x0ED31D: bytes.fromhex("add01ceb9d0210eb186920008dd01ce8e8a900299d0210e8e8a91500850c"),
}


@dataclass(frozen=True, slots=True)
class AlttpArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: AlttpFont
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _read(rom: bytes, address: int, length: int) -> bytes:
    at = lorom_offset(address)
    return bytes(rom[at : at + length])


def verify_rom(rom: bytes) -> None:
    """Every byte the overlay replaces or relies on, and the hooks' room empty."""
    if len(rom) != ROM_SIZE or rom[ROM_SIZE_BYTE] != ROM_SIZE_CODES[ROM_SIZE]:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"The ROM is {len(rom)} bytes, not the {ROM_SIZE} of its header",
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    for address, original in expected.items():
        if _read(rom, address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at ${address:06X}"
            )
    room = _read(rom, HOOK_ROOM_START, HOOK_ROOM_END - HOOK_ROOM_START)
    if room != bytes((0xFF,)) * len(room):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "The room of the hooks is not free"
        )


def _verify_source(rom: bytes, message: AlttpMessage) -> bytes:
    """The message's English bytes, its end included, as pinned."""
    stored = messages(rom)
    if message.index >= len(stored):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{message.key}: no message {message.index}"
        )
    data = stored[message.index].data
    if source_digest(data) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.index:#x} differs from the pinned text",
        )
    return data


# ---------------------------------------------------------------------------
# Encoding and fonts


def messages_characters(translated: Sequence[AlttpMessage]) -> set[str]:
    used: set[str] = set()
    for message in translated:
        used |= message_characters(message.notation)
    return used


def encode_messages(
    translated: Sequence[AlttpMessage], encoder: AlttpArabicEncoder
) -> dict[str, EncodedMessage]:
    encoded: dict[str, EncodedMessage] = {}
    for message in translated:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        encoded[message.key] = encoder.encode(message.notation)
    numbers = [message.index for message in translated]
    if len(set(numbers)) != len(numbers):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one message")
    return encoded


def data_writes(
    translated: Sequence[AlttpMessage], encoded: Mapping[str, EncodedMessage], font: AlttpFont
) -> dict[int, bytes]:
    """What the overlay writes into the added banks, by address."""
    texts: dict[int, bytes] = {}
    redirects = bytearray()
    address = MESSAGES
    for message in translated:
        data = encoded[message.key].data
        if (address & 0xFFFF) + len(data) > 0x10000:
            address = (address & ~0xFFFF) + 0x10000 + 0x8000
        if address + len(data) > MESSAGES_END:
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW, "The Arabic messages do not fit the added banks"
            )
        redirects += struct.pack("<HHB", message.index, address & 0xFFFF, address >> 16)
        texts[address] = data
        address += len(data)
    redirects += b"\xff\xff"
    if len(redirects) > ARABIC_WIDTHS - REDIRECTS:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW, f"{len(translated)} messages do not fit the list"
        )
    widths = bytearray(CODES)
    glyphs = bytearray(CODES * GLYPH_BYTES)
    for code, glyph in font.glyphs.items():
        widths[code] = glyph.width
        glyphs[code * GLYPH_BYTES : (code + 1) * GLYPH_BYTES] = glyph.data()
    return {
        REDIRECTS: bytes(redirects),
        ARABIC_WIDTHS: bytes(widths),
        ARABIC_FONT: bytes(glyphs),
        **texts,
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


def build_alttp_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    translated: tuple[AlttpMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> AlttpArabicBuild:
    """Build the Arabic ROM and its BPS patch from the original.

    ``translated`` and ``verify_identity`` exist for synthetic tests; a real build
    always uses the pinned translation against the pinned ROM.
    """
    if verify_identity:
        verify_usa_image(rom)
    verify_rom(rom)
    translated = translated or alttp_arabic_messages(translations)
    for message in translated:
        _verify_source(rom, message)

    used = messages_characters(translated)
    glyph_map = alttp_glyph_codes(used)
    font = build_alttp_font(font_path, glyph_map, used)
    encoded = encode_messages(translated, AlttpArabicEncoder(glyph_map, font))

    output = bytearray(rom) + bytes((EXPANSION_FILL,)) * (EXPANDED_SIZE - len(rom))
    writes = {HOOK_ADDRESS: HOOK_CODE, **data_writes(translated, encoded, font)}
    for address, data in writes.items():
        at = lorom_offset(address)
        output[at : at + len(data)] = data
    for site in SITES:
        at = lorom_offset(site.address)
        output[at : at + len(site.patched)] = site.patched
    output[ROM_SIZE_BYTE] = ROM_SIZE_CODES[EXPANDED_SIZE]
    checksum = set_checksum(output)
    result = bytes(output)
    _verify_output(result, rom, writes)
    patch = create_bps(rom, result)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, result, patch),
        "messages": {
            message.key: {
                "index": message.index,
                "bytes": len(encoded[message.key].data),
                "pages": [
                    [line.width for line in page] for page in encoded[message.key].pages or ()
                ],
            }
            for message in translated
        },
        "arabic_glyphs": sum(code != SPACE_CODE for code in font.glyphs),
        "arabic_codes": _code_range(glyph_map),
        "font_size": font.font_size,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_address": f"${HOOK_ADDRESS:06X}",
        "hook_bytes": len(HOOK_CODE),
        "arabic_message_bytes": sum(len(encoded[message.key].data) for message in translated),
        "checksum": f"{checksum:04X}",
    }
    return AlttpArabicBuild(rom=result, patch=patch, font=font, report=report)


def _code_range(glyph_map: GlyphCodes) -> str:
    codes = [code for code in glyph_map.all_codes() if code != SPACE_CODE]
    return f"{min(codes):02X}..{max(codes):02X}"


def _verify_output(output: bytes, original: bytes, writes: Mapping[int, bytes]) -> None:
    """Only the sites, the hooks, the header and the added banks changed, and the
    checksum holds."""
    if len(output) != EXPANDED_SIZE or output[ROM_SIZE_BYTE] != ROM_SIZE_CODES[EXPANDED_SIZE]:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ROM is not 2 MiB")
    allowed = [(lorom_offset(site.address), len(site.patched)) for site in SITES]
    allowed += [
        (lorom_offset(address), len(data))
        for address, data in writes.items()
        if lorom_offset(address) < len(original)
    ]
    allowed += [(ROM_SIZE_BYTE, 1), (CHECKSUM, 4)]
    changed = [
        at
        for at in range(0, len(original), 0x1000)
        if output[at : at + 0x1000] != original[at : at + 0x1000]
    ]
    for block in changed:
        for at in range(block, block + 0x1000):
            if output[at] != original[at] and not any(
                start <= at < start + size for start, size in allowed
            ):
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED,
                    f"The overlay changed the ROM at {at:#x}, outside its places",
                )
    (checksum,) = struct.unpack_from("<H", output, CHECKSUM + 2)
    if sum(output) & 0xFFFF != checksum:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header's checksum is wrong")


# ---------------------------------------------------------------------------
# Without the ROM


def check_alttp_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, lay out and draw every message."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    translated = alttp_arabic_messages(translations)
    used = messages_characters(translated)
    glyph_map = alttp_glyph_codes(used)
    font = build_alttp_font(font_path, glyph_map, used) if font_path else None
    encoded = encode_messages(translated, AlttpArabicEncoder(glyph_map, font))
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [(message.key, message_preview(encoded[message.key], font)) for message in translated]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(translated),
        "keys": [message.key for message in translated],
        "laid_out": font is not None,
        "encoded_bytes": sum(len(result.data) for result in encoded.values()),
        "arabic_glyphs": len(glyph_map.characters) - 1,
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["pages"] = {key: len(result.pages or ()) for key, result in encoded.items()}
    return report


def encode_alttp_arabic_message(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one message in notation; with a font, each page's lines' widths.

    Its codes are those of its own characters.
    """
    used = message_characters(text)
    glyph_map = alttp_glyph_codes(used)
    font = build_alttp_font(font_path, glyph_map, used) if font_path else None
    result = AlttpArabicEncoder(glyph_map, font).encode(text)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.pages is not None:
        payload["pages"] = [[line.width for line in page] for page in result.pages]
    return payload


def write_build_outputs(
    build: AlttpArabicBuild, out_dir: Path, *, rom_name: str | None
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
    translated: tuple[AlttpMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    words = dictionary(rom)
    translated = translated or alttp_arabic_messages(translations)
    return {
        message.key: message_notation(_verify_source(rom, message), words) for message in translated
    }


def message_address(rom: bytes, index: int) -> int:
    """The LoROM address of a message's English, by its number."""
    return lorom_address(messages(rom)[index].offset)
