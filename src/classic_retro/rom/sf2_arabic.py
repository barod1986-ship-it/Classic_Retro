"""Arabic ROM overlay for *Shining Force II* (USA): three strings of a new game.

The ROM is the No-Intro dump (SHA-256 below), 2 MiB, the 68000's addresses
$000000-$1FFFFF; the overlay patches the user's and ships as a BPS patch of
it. The overlay:

1. verifies the ROM, every byte of the text engine it replaces or relies on
   (``SITES``, ``ANCHORS``: the engine's code where the hooks go back to or
   call, the font's pointer), that its room (``ROOM_START`` to ``ROOM_END``,
   free bytes at the end of the section that holds the text) is free, and each
   translated string's original (its number, the SHA-256 of its bytes and,
   where pinned, its commands);
2. draws the translation's glyphs (``engines.sf2_arabic``), holds each
   translation's tags against its original's (``command_skeleton``: everything
   but the new lines the encoder writes itself), encodes each string and
   writes into that room the hooks (``sf2_arabic_hooks.s``), the
   list that sends each translated string to its Arabic (``REDIRECTS``), the
   glyphs in the game's font format and the Arabic strings;
3. puts a jump or a call to a hook in place of four places of the engine
   (``SITES``);
4. sets the header's checksum;
5. reads everything back from the image before accepting it: the hooks, the
   sites, the list, the font, and each Arabic string through the list as the
   hooks find it (``read_redirects``, ``read_arabic_string``), with the
   translation's tags; and proves nothing else changed.

The English strings stay where they were, as they were: a translated one is
read from its Arabic instead, and the hooks tell an Arabic string by its
pointer, which lies in the room.

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
from classic_retro.cpu.m68k import jmp_long, jsr_long, nop_fill
from classic_retro.engines.sf2 import (
    END,
    TAGS_WITH_ARGUMENT,
    HuffmanTrees,
    command_skeleton,
    decode_string,
    notation,
    string_bytes,
)
from classic_retro.engines.sf2_arabic import (
    GLYPH_BYTES,
    SPACE_CODE,
    EncodedString,
    Sf2ArabicEncoder,
    Sf2Font,
    build_sf2_font,
    font_preview,
    message_characters,
    message_preview,
    messages_sheet,
    notation_skeleton,
    sf2_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.patching.overlay import verify_bytes, verify_empty, verify_untouched
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.sf2_arabic_script import Sf2String, sf2_arabic_strings

# No-Intro "Shining Force II (USA)".
ROM_SHA256 = "9adf662d09881f58ec37d174ab01e87a7fcfb24700b5f84b26c0cd4f351509e9"
ROM_SIZE = 2 * 1024 * 1024
IMAGE = ImageSpec("Shining Force II (USA)", ROM_SHA256, ROM_SIZE, base=0)
CHECKSUM = 0x18E  # the header's: the sum of the words from $200
CHECKSUM_FROM = 0x200

# The room: free bytes (0xFF) at the end of the section that holds the text.
# The hooks, the list of translated strings (6 bytes each: the string's number,
# its Arabic's address; $FFFF ends it), 32 bytes a code, then the Arabic
# strings, each stored as the game stores one (a length byte, then its symbols)
# but not compressed. The hooks tell an Arabic string by its pointer, in the room.
ROOM_START = 0x042600
ROOM_END = 0x044000
HOOK_ADDRESS = 0x042600
REDIRECTS = 0x042A00
REDIRECT_ENTRY = 6
ARABIC_FONT = 0x042B00
HOOK_SOURCE = Path(__file__).with_name("sf2_arabic_hooks.s")

# m68k-linux-gnu-as -m68000 sf2_arabic_hooks.s; ld at $042600
HOOK_CODE = bytes.fromhex(
    "48e7404043f900042a0032190c41ffff6708b2406712588960f04cdf020248a7"
    "8000ec484ef8627820514cdf02024ef8629c2f08207900ffb77eb1fc00042600"
    "6534b1fc00044000642c588f4ab900ffb77a670a6100008e42b900ffb77a4240"
    "101823c800ffb77e0c0000fe660642b900ffb77e4e75205f4ab900ffb77a6600"
    "00064ef863564ef863662f08207900ffb77eb1fc00042600653cb1fc00044000"
    "6434205f48e7fff0024000ff47f900042b00610001027800183900ffb6d4303c"
    "00d89044904161000102d33900ffb6d44cdf0fff4e75205f48a7e000024000ff"
    "4ef86b7848e7fffe45f8666e26790002800c227900ffb77a760070001019670e"
    "103200005340610000aed64160ec08f9000000ffb6d866120c39000200ffb6d4"
    "670813fc00ff00ffb6d47800183900ffb6d4d8430c4400d6630813fc00ff00ff"
    "b6d448e710304eb863084cdf0c087800183900ffb6d43a3c00d89a449a432279"
    "00ffb77a70001019671410320000534061000044300561000052da4160e6d739"
    "00ffb6d44eb8697a4cdf7fff4e750cb90004260000ffb77e65140cb900044000"
    "00ffb77e6408317c009800064e75317c016800064e753200eb4941f310003218"
    "0241000f670252414e7548e7ffe01f3900ffb6d413c000ffb6d4380072001239"
    "00ffb6d64eb86bde13df00ffb6d4024400077c0e3e183604e34f64283003e648"
    "eb48224ad2c0300302400007e248d2c00803000066080211000f851160060211"
    "00f0831152434a4766ce588a52450c45000865064245d4fc03e051ceffb84cdf"
    "07ff4e75"
)
HOOK_SYMBOLS = {
    "redirect_hook": 0x00,
    "symbol_hook": 0x32,
    "draw_hook": 0x8A,
    "cursor_hook": 0x18E,
}
HOOKS = HookProgram(
    "Shining Force II hooks", HOOK_SOURCE, HOOK_ADDRESS, HOOK_CODE, HOOK_SYMBOLS, cpu="68000"
)
PATCH_NAME = "shining-force-2-usa-arabic-new-game.bps"


@dataclass(frozen=True, slots=True)
class Site:
    """Game code the overlay replaces: its address, original and new bytes, and why."""

    address: int
    original: bytes
    patched: bytes
    what: str


# A site jumps or calls with a long address (``cpu.m68k``), filled with NOPs to
# its length.
SITES = (
    Site(
        0x006272,
        bytes.fromhex("48a78000ec48"),
        jmp_long(HOOKS.symbol_address("redirect_hook")),
        "DisplayText's lookup (MOVEM.W d0,-(sp); LSR.W #6,d0): a translated string, its Arabic",
    ),
    Site(
        0x00634E,
        bytes.fromhex("4ab8b77a66000012"),
        nop_fill(jmp_long(HOOKS.symbol_address("symbol_hook")), 8),
        "GetNextTextSymbol (TST.L $FFB77A; BNE.W): an Arabic string's next symbol, a name whole",
    ),
    Site(
        0x006B70,
        bytes.fromhex("48a7e000024000ff"),
        nop_fill(jmp_long(HOOKS.symbol_address("draw_hook")), 8),
        "SymbolsToGraphics (MOVEM.W d0-d2,-(sp); ANDI.W #$FF,d0): an Arabic glyph, mirrored",
    ),
    Site(
        0x0064DA,
        bytes.fromhex("317c01680006"),
        jsr_long(HOOKS.symbol_address("cursor_hook")),
        "sub_64A8 (MOVE.W #$168,6(a0)): the waiting arrow at the left in an Arabic string",
    ),
)
# Bytes the hooks rely on without replacing them.
ANCHORS = {
    # DisplayText: the lookup after its site, where an English string goes on;
    # after the bank's strings, where an Arabic one does (its length byte kept,
    # 1 the empty string, the pointer stored).
    0x006278: bytes.fromhex(
        "020000fc207900028000207000004c9f0001024000ff7e0060061e10d1c7528851c8fff8"
    ),
    0x00629C: bytes.fromhex(
        "42b8b77a4238b6d811d8b6d721fc00ffb6e8b78211fc0001b6d60c380001b6d7670000404eb90002800421c8b77e"
    ),
    # ApplyAutomaticNewline, which the hooks call before a name drawn whole.
    0x006308: bytes.fromhex(
        "0c3800ccb6d4633c6100076e11fc0002b6d406380010b6d50c79c77c00ffdc8467080c380020b6d56006"
        "0c380030b6d5651248e78000610007924cdf000104380010b6d54e75"
    ),
    # GetNextTextSymbol's two ways on: the Huffman decoding, and the ASCII of a
    # name (LEA table_AsciiToTextSymbolMap(pc), which the hooks read).
    0x006356: bytes.fromhex("2078b77e4eb90002800821c8b77e4e75"),
    0x006366: bytes.fromhex("2278b77a42401019121121c9b77a43fa02f8103100004a01660442b8b77a4e75"),
    # sub_64A8 about its site: the arrow's sprite in a0, shown when d2 >= 7.
    0x0064C8: bytes.fromhex("0c4200076c0c30bc0001317c00010006600a"),
    0x0064E0: bytes.fromhex("30bc0148"),
    # HandleBlinkingDialogueCursor, which the hooks call to send a name's line
    # to VRAM: the pen's line in the window.
    0x00697A: bytes.fromhex(
        "3038af6ee748d038b6d50c79c77c00ffdc84660c0c0000306d0404000030600a0c0000206d0404000020"
        "0c0000106c00002e"
    ),
    # SymbolsToGraphics after its site, and the pen's place in the pixels
    # (sub_6BDE), which the hooks call.
    0x006B78: bytes.fromhex("3e001238b6d60c010001671a"),
    0x006BDE: bytes.fromhex(
        "1401e90a1038b6d53638af6ee74bd0030c79c77c00ffdc84660c0c0000306d0404000030600a0c0000206d"
        "0404000020024000f8ef481638b6d5024300073a03e54bd0431638b6d4024300f8e54bd04345f900ff6802"
        "d4c07c0e4e75"
    ),
    # p_font_VariableWidth.
    0x02800C: bytes.fromhex("00029002"),
}


@dataclass(frozen=True, slots=True)
class Sf2ArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: Sf2Font
    report: dict[str, object] = field(default_factory=dict)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def verify_rom(rom: bytes) -> None:
    """Every byte the overlay replaces or relies on, and its room free."""
    if len(rom) != ROM_SIZE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"The ROM is {len(rom)} bytes, not {ROM_SIZE}"
        )
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    verify_bytes(rom, expected, what="the ROM")
    verify_empty(rom, ROOM_START, ROOM_END, 0xFF, what="The overlay's room")


def _verify_source(rom: bytes, string: Sf2String, trees: HuffmanTrees | None = None) -> bytes:
    """The string's bytes as stored (its length byte and code), as pinned: its hash
    and, where pinned, its commands (decoded with ``trees``, the ROM's unless given)."""
    data = string_bytes(rom, string.index)
    if source_digest(data) != string.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: string {string.index:#x} differs from the pinned text",
        )
    if (
        string.source_skeleton is not None
        and _skeleton(rom, string, trees) != string.source_skeleton
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: string {string.index:#x} has different commands than pinned",
        )
    return data


def _skeleton(rom: bytes, string: Sf2String, trees: HuffmanTrees | None) -> tuple[str, ...]:
    return command_skeleton(decode_string(rom, string.index, trees))


def source_skeletons(rom: bytes, translated: Sequence[Sf2String]) -> dict[str, tuple[str, ...]]:
    """Every original's commands (``command_skeleton``), verified, by entry id."""
    trees = HuffmanTrees.read(rom)
    skeletons: dict[str, tuple[str, ...]] = {}
    for string in translated:
        _verify_source(rom, string, trees)
        skeletons[string.key] = _skeleton(rom, string, trees)
    return skeletons


# ---------------------------------------------------------------------------
# Encoding and fonts


def strings_characters(translated: Sequence[Sf2String]) -> set[str]:
    used: set[str] = set()
    for string in translated:
        used |= message_characters(string.notation)
    return used


def encode_strings(
    translated: Sequence[Sf2String],
    encoder: Sf2ArabicEncoder,
    skeletons: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[str, EncodedString]:
    """Every string held against its original's commands, then encoded.

    The commands are the ROM's (``skeletons``, from ``source_skeletons``) or,
    without the ROM, those pinned in the script, where they are.
    """
    encoded: dict[str, EncodedString] = {}
    for string in translated:
        if string.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"String {string.key} twice")
        skeleton = string.source_skeleton if skeletons is None else skeletons[string.key]
        if skeleton is not None:
            validate_command_skeleton(skeleton, string.notation)
        encoded[string.key] = encoder.encode(string.notation)
    numbers = [string.index for string in translated]
    if len(set(numbers)) != len(numbers):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two entries translate one string")
    return encoded


def font_codes(glyph_map: GlyphCodes) -> int:
    """How many codes the font table holds: to the highest the translation uses (the
    font draws a glyph for each code of its map)."""
    return max(glyph_map.all_codes()) + 1


@dataclass(frozen=True, slots=True)
class RoomLayout:
    """The list of translated strings, and the Arabic strings from ``start``."""

    redirects: bytes
    start: int
    texts: bytes


def lay_out_room(
    translated: Sequence[Sf2String], encoded: Mapping[str, EncodedString], codes: int
) -> RoomLayout:
    """The list and the Arabic strings in the room, after a font table of ``codes``
    glyphs: each string a length byte then its symbols, from a word; refused where
    the list or the room cannot hold them. It needs only the text, so the check
    without the ROM refuses what the build would."""
    texts = bytearray()
    start = ARABIC_FONT + codes * GLYPH_BYTES
    redirects = bytearray()
    for string in translated:
        symbols = encoded[string.key].data
        redirects += struct.pack(">HI", string.index, start + len(texts))
        texts += bytes((min(len(symbols), 0xFF),)) + symbols
        if len(texts) % 2:
            texts.append(0xFF)
    redirects += b"\xff\xff"
    if len(redirects) > ARABIC_FONT - REDIRECTS:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW, f"{len(translated)} strings do not fit the list"
        )
    if start + len(texts) > ROOM_END:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"The font and the Arabic need {start + len(texts) - ARABIC_FONT} bytes; the room "
            f"holds {ROOM_END - ARABIC_FONT}",
        )
    return RoomLayout(bytes(redirects), start, bytes(texts))


def room_data(
    translated: Sequence[Sf2String], encoded: Mapping[str, EncodedString], font: Sf2Font
) -> dict[int, bytes]:
    """What the overlay writes into its room, by address."""
    codes = max(font.glyphs) + 1
    glyphs = bytearray(codes * GLYPH_BYTES)
    for code, glyph in font.glyphs.items():
        glyphs[code * GLYPH_BYTES : (code + 1) * GLYPH_BYTES] = glyph.data()
    layout = lay_out_room(translated, encoded, codes)
    return {
        HOOK_ADDRESS: HOOK_CODE,
        REDIRECTS: layout.redirects,
        ARABIC_FONT: bytes(glyphs),
        layout.start: layout.texts,
    }


def set_checksum(rom: bytearray) -> int:
    """The header's checksum: the sum of the big-endian words from $200."""
    words = struct.unpack_from(f">{(len(rom) - CHECKSUM_FROM) // 2}H", rom, CHECKSUM_FROM)
    checksum = sum(words) & 0xFFFF
    struct.pack_into(">H", rom, CHECKSUM, checksum)
    return checksum


# ---------------------------------------------------------------------------
# The build


def build_sf2_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    translated: tuple[Sf2String, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> Sf2ArabicBuild:
    """Build the Arabic ROM and its BPS patch from the original.

    ``translated`` and ``verify_identity`` exist for synthetic tests; a real build
    always uses the pinned translation against the pinned ROM.
    """
    if verify_identity:
        verify_usa_image(rom)
    verify_rom(rom)
    translated = translated or sf2_arabic_strings(translations)
    skeletons = source_skeletons(rom, translated)

    used = strings_characters(translated)
    glyph_map = sf2_glyph_codes(used)
    font = build_sf2_font(font_path, glyph_map, used)
    encoded = encode_strings(translated, Sf2ArabicEncoder(glyph_map, font), skeletons)

    output = bytearray(rom)
    writes = room_data(translated, encoded, font)
    for address, data in writes.items():
        output[address : address + len(data)] = data
    for site in SITES:
        output[site.address : site.address + len(site.patched)] = site.patched
    checksum = set_checksum(output)
    result = bytes(output)
    _verify_output(result, rom, writes, translated, encoded)
    patch = create_bps(rom, result)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, result, patch),
        "strings": {
            string.key: {
                "index": string.index,
                "bytes": len(encoded[string.key].data),
                "lines": [line.end for line in encoded[string.key].lines or ()],
                # The original's commands, as the script pins them.
                "source_skeleton": list(skeletons[string.key]),
            }
            for string in translated
        },
        "arabic_glyphs": sum(code != SPACE_CODE for code in font.glyphs),
        "arabic_codes": _code_range(glyph_map),
        "font_size": font.font_size,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_address": f"${HOOK_ADDRESS:06X}",
        "hook_bytes": len(HOOK_CODE),
        "room_used": max(address + len(data) for address, data in writes.items()) - ROOM_START,
        "checksum": f"{checksum:04X}",
    }
    return Sf2ArabicBuild(rom=result, patch=patch, font=font, report=report)


def _code_range(glyph_map: GlyphCodes) -> str:
    codes = [code for code in glyph_map.all_codes() if code != SPACE_CODE]
    return f"{min(codes):02X}..{max(codes):02X}"


def read_redirects(rom: bytes) -> dict[int, int]:
    """The list of translated strings as the hooks read it: each string's number and
    the address of its Arabic's length byte, to the $FFFF that ends it."""
    found: dict[int, int] = {}
    at = REDIRECTS
    while at + REDIRECT_ENTRY <= ARABIC_FONT:
        index, address = struct.unpack_from(">HI", rom, at)
        if index == 0xFFFF:
            return found
        found[index] = address
        at += REDIRECT_ENTRY
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED, "The list of translated strings has no end"
    )


def read_arabic_string(rom: bytes, address: int) -> bytes:
    """An Arabic string's symbols, its end included, as the hooks read them after its
    length byte at ``address``: a symbol a byte, a command's argument with it, within
    the room."""
    start = at = address + 1
    arguments = set(TAGS_WITH_ARGUMENT.values())
    while at < ROOM_END:
        symbol = rom[at]
        at += 2 if symbol in arguments else 1
        if symbol == END:
            return bytes(rom[start:at])
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED, f"The Arabic string at ${address:06X} has no end"
    )


def _verify_output(
    output: bytes,
    original: bytes,
    writes: Mapping[int, bytes],
    translated: Sequence[Sf2String],
    encoded: Mapping[str, EncodedString],
) -> None:
    """Everything written reads back, only the sites, the room and the checksum
    changed, and the checksum holds."""
    if len(output) != len(original):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The ROM's size changed")
    if output[HOOK_ADDRESS : HOOK_ADDRESS + len(HOOK_CODE)] != HOOK_CODE:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The hook code does not read back"
        )
    for site in SITES:
        if output[site.address : site.address + len(site.patched)] != site.patched:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"The site at ${site.address:06X} does not read back",
            )
    names = {
        HOOK_ADDRESS: "The hook code",
        REDIRECTS: "The list of translated strings",
        ARABIC_FONT: "The font table",
    }
    for address, data in writes.items():
        if output[address : address + len(data)] != data:
            what = names.get(address, "The Arabic text")
            raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, f"{what} does not read back")
    redirects = read_redirects(output)
    if list(redirects) != [string.index for string in translated]:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "The list of translated strings does not read back in order",
        )
    for string in translated:
        address = redirects[string.index]
        if not ARABIC_FONT <= address < ROOM_END:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key}: its Arabic is not in the room"
            )
        data = read_arabic_string(output, address)
        if data != encoded[string.key].data or output[address] != min(len(data), 0xFF):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{string.key}: the Arabic string does not read back through the list",
            )
        if command_skeleton(data) != notation_skeleton(string.notation):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{string.key}: the Arabic string read back has other commands",
            )
    allowed = [(site.address, site.address + len(site.patched)) for site in SITES]
    allowed += [(address, address + len(data)) for address, data in writes.items()]
    allowed.append((CHECKSUM, CHECKSUM + 2))
    verify_untouched(original, output, allowed, what="The ROM")
    (checksum,) = struct.unpack_from(">H", output, CHECKSUM)
    words = struct.unpack_from(f">{(len(output) - CHECKSUM_FROM) // 2}H", output, CHECKSUM_FROM)
    if sum(words) & 0xFFFF != checksum:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The header's checksum is wrong")


# ---------------------------------------------------------------------------
# Without the ROM


def check_sf2_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, lay out and draw every string."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    translated = sf2_arabic_strings(translations)
    used = strings_characters(translated)
    glyph_map = sf2_glyph_codes(used)
    font = build_sf2_font(font_path, glyph_map, used) if font_path else None
    encoded = encode_strings(translated, Sf2ArabicEncoder(glyph_map, font))
    # The room as the build fills it: a new line the layout writes takes a space's byte,
    # so the strings are as long without the font.
    lay_out_room(translated, encoded, font_codes(glyph_map))
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [(string.key, message_preview(encoded[string.key], font)) for string in translated]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "strings": len(translated),
        "keys": [string.key for string in translated],
        "laid_out": font is not None,
        "encoded_bytes": sum(len(result.data) for result in encoded.values()),
        "arabic_glyphs": len(glyph_map.characters) - 1,
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["lines"] = {key: len(result.lines or ()) for key, result in encoded.items()}
    return report


def encode_sf2_arabic_string(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one string in notation; with a font, where each line's pen ends.

    Its codes are those of its own characters.
    """
    used = message_characters(text)
    glyph_map = sf2_glyph_codes(used)
    font = build_sf2_font(font_path, glyph_map, used) if font_path else None
    result = Sf2ArabicEncoder(glyph_map, font).encode(text)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.lines is not None:
        payload["lines"] = [line.end for line in result.lines]
    return payload


def write_build_outputs(
    build: Sf2ArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (m68k) and read its symbols."""
    return HOOKS.assemble(source)


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    translated: tuple[Sf2String, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    translated = translated or sf2_arabic_strings(translations)
    trees = HuffmanTrees.read(rom)
    originals = {}
    for string in translated:
        _verify_source(rom, string, trees)
        originals[string.key] = notation(decode_string(rom, string.index, trees))
    return originals


def extract_skeletons(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    translated: tuple[Sf2String, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Every pinned original's commands, verified, by entry id: what a maintainer pins
    as ``source_skeleton`` in the script, so the translations are checked without the
    ROM. The build's report carries the same."""
    if verify_identity:
        verify_usa_image(rom)
    return source_skeletons(rom, translated or sf2_arabic_strings(translations))
