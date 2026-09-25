"""Arabic ROM overlay for *Advance Wars* (USA, Rev 1).

No decompilation of this game is known, so the overlay patches the user's
image (``AWRE`` revision 1, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced or relied on are
   verified, and every translated message's original is checked against its
   pinned hash and control codes, and against the script command that shows
   it;
2. the Thumb hooks (``advance_wars_arabic_hooks.s``), the right-to-left font
   (``engines.advance_wars_arabic``) and the translated messages go into the
   0xFF padding at the end of the image; the image stays 4 MiB;
3. thirteen sites in the dialogue printer, its control codes and the Yes/No
   task call the hooks through a BL each;
4. the script pointer of every translated message is repointed to the Arabic
   message. A message of the Arabic bank is what the hooks turn right to left.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import NOP, bl_instruction, branch_instruction
from classic_retro.engines.advance_wars import (
    FONT_POINTERS,
    FONT_WIDTHS,
    ROM_BASE,
    AwFont,
    command_skeleton,
    parse_notation,
    read_message,
    text_notation,
)
from classic_retro.engines.advance_wars_arabic import (
    BASELINE,
    LINE_WIDTH,
    AwArabicEncoder,
    AwRtlFont,
    build_advance_wars_rtl_font,
    font_preview,
    latin_rtl_glyphs,
    message_preview,
    messages_sheet,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.advance_wars_arabic_script import (
    MESSAGE_COMMAND,
    AwArabicMessage,
    advance_wars_arabic_messages,
)

USA_SHA256 = "4dd4bd22441f29b22ca5af554f30bf0eb7d2b1a5daff0e2cd071a43e11383305"
USA_SIZE = 0x400000

# The 0xFF padding at the end of the image (from 0x083F7D74).
HOOK_CODE_ADDRESS = 0x083F8000
FONT_ADDRESS = 0x083F8800
ARABIC_TEXT_ADDRESS = 0x083FC000
REGION_END = 0x08400000
PADDING = 0xFF
HOOK_SOURCE = Path(__file__).with_name("advance_wars_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi advance_wars_arabic_hooks.s; ld -Ttext 0x083F8000; objcopy
HOOK_CODE = bytes.fromhex(
    "00b500f0d2f808bc9e46002a01d1a84a10477047f0b5051c0e1c171c9c46201c"
    "00f0c3f8002a07d1281c311c3a1c6346a04c00f03bf924e0206a9f49401a9f49"
    "884209d29e4b5b5d9e48a9004058311c3a1c00f0def814e090b09b4a525d072a"
    "00d907229948a9004058694604b400f0fdf808bc01336846311c3a1c00f0c9f8"
    "10b0f0bc02bc084703b500f08ef803bc08bc9e46002a01d18d4a104710b500f0"
    "94f8828e838d8b4c2343141c1c430c8001321a4340310a8010bc08bc184714b5"
    "281c00f072f8b11c002a01d000f07df8814a0a80814a40310a8014bc08bc1847"
    "7f492962744a801a744a904201d2081c7ce070472862002169626f4a801a6f4a"
    "904201d2764871e0704700b5281c00f04cf8b01c002a0ad0a86a3321695c8901"
    "40183021695c1431490040180130a06108bc1847d00703d16a48844600206047"
    "70478169ca0701d1674a104710b50139614a0b1c1a8040331a80483b1a804033"
    "1a801e23c35edb00c91a604a0a80013240310a80c06a5e4c00f098f810bc01bc"
    "0047202000e012208989a369db070bd005b4302008408143420912011143c006"
    "c00f4001014305bc7047026a424bd21a424b9a4207d3426a3f4bd21a3f4b9a42"
    "01d3002270470122704710b4826a8b1a9c06e40e1b1b1b1bd2183023c35c5b00"
    "15331b1b5b00d11810bc7047011c08230a78002a02d00131013bf9d101398842"
    "06d202780b7803700a7001300139f6e77047f0b45207520f002a04d100244025"
    "043d4c51fcd1d418082c05d900248025043d4c51402dfbd108b4002b13d09400"
    "20252d1b002687593a1ca2408b5913438b51ef4004d0321c40328b583b438b50"
    "0436402eefd301bcf0bc7047f0b4541c640810270023002595420fd26e08865d"
    "3607360f1b0133430135954206d26e08865d36091b0133430135ede71b010b60"
    "04310019013fe5d1f0bc7047204700007d2c01083122050800c03f0800400000"
    "008c3f0800883f08f09b3008f0973008652001080004000074010000c9a10000"
    "6c220102692a01082d860108caa500004db40708"
)
HOOK_SYMBOLS = {
    "hook_arrow": 0xBE,
    "hook_choice": 0x10A,
    "hook_column": 0x88,
    "hook_cursor": 0x142,
    "hook_draw": 0x14,
    "hook_gap": 0x00,
    "hook_keys_back": 0x182,
    "hook_keys_next": 0x186,
    "hook_labels": 0x134,
    "hook_name": 0xE0,
    "hook_name_end": 0xF4,
}
IMAGE = ImageSpec("Advance Wars (USA, Rev 1)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("Advance Wars hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "advance-wars-usa-rev1-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class Site:
    """Game code replaced by a BL to a hook, then (when the hook returns past the
    rest of the replaced code) a branch to ``resume``, and NOPs."""

    address: int
    original: bytes
    hook: str
    resume: int | None = None

    def patch(self) -> bytes:
        code = bl_instruction(self.address, HOOKS.symbol_address(self.hook))
        if self.resume is not None:
            code += branch_instruction(self.address + 4, self.resume)
        if len(code) > len(self.original) or (len(self.original) - len(code)) % 2:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Site {self.address:#x} does not fit"
            )
        return code + NOP * ((len(self.original) - len(code)) // 2)


def _bl_site(address: int, target: int, hook: str) -> Site:
    """A BL of the game's, sent to a hook instead."""
    return Site(address, bl_instruction(address, target), hook)


SITES = (
    # The printer: the gap before a glyph, the glyph, and its tile column.
    _bl_site(0x080121AA, 0x08012C7C, "hook_gap"),
    _bl_site(0x080121CC, 0x08052230, "hook_draw"),
    _bl_site(0x080121E2, 0x08012064, "hook_column"),
    _bl_site(0x080121FE, 0x08012064, "hook_column"),
    # Code 0F: `movs r1, #0xba ... strh r0, [r1]`, the key arrow's two tiles.
    Site(
        0x08011E30, bytes.fromhex("ba214900081c7080311c4231124b181c0880"), "hook_arrow", 0x08011E42
    ),
    # Code 15: `ldr r0, =0x0201226C; str r0, [r5, #32]`, the name.
    Site(0x08011DAE, bytes.fromhex("04482862"), "hook_name"),
    # Code 00 after a name: `str r0, [r5, #32]; movs r0, #0; str r0, [r5, #36]`.
    Site(0x08011DA2, bytes.fromhex("286200206862"), "hook_name_end"),
    # Codes 14/16/17: `adds r0, r6, #2; str r0, [r4, #24]`, the cursor's place.
    Site(0x08011DCE, bytes.fromhex("b01ca061"), "hook_choice"),
    # The Yes/No task: its answers, its cursor, and the keys that move it.
    _bl_site(0x08018692, 0x08012A68, "hook_labels"),
    _bl_site(0x08018698, 0x0801862C, "hook_cursor"),
    _bl_site(0x080186E8, 0x0801862C, "hook_cursor"),
    Site(0x080186C0, bytes.fromhex("20208989"), "hook_keys_back"),
    Site(0x080186D8, bytes.fromhex("12208989"), "hook_keys_next"),
)

# Bytes the hooks rely on without replacing them:
ANCHORS = {
    # the font's pointer and width tables, read by the glyph routine;
    0x08052360: struct.pack("<II", FONT_WIDTHS, FONT_POINTERS),
    # the name's RAM string, which code 15 inserts;
    0x08011DC0: struct.pack("<I", 0x0201226C),
    # the message command's dialogue box: text from column 7, row 1 of the
    # map at 0x02014B40 (`movs r0, #7; movs r1, #1`), which the hooks mirror;
    0x0801796E: bytes.fromhex("07200121"),
    0x080179A4: struct.pack("<I", 0x02014B40),
    # the Yes/No task: r2 = the cursor's place, then r0 = r1 = 0 for the answers.
    0x0801867E: bytes.fromhex("a269"),
    0x0801868C: bytes.fromhex("002001900021"),
}


@dataclass(frozen=True, slots=True)
class AwArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: AwRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset
_word = IMAGE.word


def source_digest(body: bytes) -> str:
    """SHA-256 of an original message, up to its final 0x00."""
    return hashlib.sha256(body).hexdigest()


def stored_message(body: bytes) -> bytes:
    """A message as the bank holds it: its bytes, then at least two zeros up to a word.

    The message command scans a message two bytes a character (``0x08011C80``);
    two zeros stop it whichever byte it reaches first.
    """
    return body + bytes(2 + (-(len(body) + 2) % 4))


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> AwFont:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 4 MiB")
    for site in SITES:
        if IMAGE.read(rom, site.address, len(site.original)) != site.original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected code at {site.address:#x} (for {site.hook})",
            )
    for address, expected in ANCHORS.items():
        if IMAGE.read(rom, address, len(expected)) != expected:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x}"
            )
    if not IMAGE.filled(rom, HOOK_CODE_ADDRESS, REGION_END, PADDING):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{HOOK_CODE_ADDRESS:#x}..{REGION_END:#x} is not empty padding",
        )
    # The hooks' literals: the font's two tables, the bank and its size.
    for value in (
        FONT_ADDRESS,
        FONT_ADDRESS + 4 * 256,
        ARABIC_TEXT_ADDRESS,
        REGION_END - ARABIC_TEXT_ADDRESS,
    ):
        if struct.pack("<I", value) not in HOOK_CODE:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The hooks do not use {value:#x}"
            )
    return AwFont.read(rom)


def _verify_source(rom: bytes, message: AwArabicMessage) -> bytes:
    if _word(rom, message.pointer - 4) != MESSAGE_COMMAND:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: {message.pointer - 4:#x} is not a message command",
        )
    if _word(rom, message.pointer) != message.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the script at {message.pointer:#x} does not show "
            f"{message.source_address:#x}",
        )
    try:
        original = read_message(rom, message.source_address)
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: no message at {message.source_address:#x}",
        ) from exc
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original at {message.source_address:#x} differs from the "
            "pinned USA script",
        )
    if command_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different control codes than pinned",
        )
    return original


def encode_messages(
    encoder: AwArabicEncoder, messages: tuple[AwArabicMessage, ...] | None = None
) -> dict[str, tuple[bytes, tuple[int, ...]]]:
    """Validate every translation against its original's control codes and encode it.

    The result is each stored message and, with a font, its line widths.
    """
    encoded: dict[str, tuple[bytes, tuple[int, ...]]] = {}
    pointers: set[int] = set()
    for message in messages or advance_wars_arabic_messages():
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        if message.pointer in pointers:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{message.key} shares a script pointer"
            )
        pointers.add(message.pointer)
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces)
        encoded[message.key] = (stored_message(result.body), result.line_widths or ())
    return encoded


def build_advance_wars_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[AwArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> AwArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    game_font = _verify_anchors(rom)
    messages = messages or advance_wars_arabic_messages(translations)
    for message in messages:
        _verify_source(rom, message)
    font = build_advance_wars_rtl_font(font_path, latin_rtl_glyphs(game_font))
    font_data = font.tables(FONT_ADDRESS)
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > FONT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")
    if FONT_ADDRESS + len(font_data) > ARABIC_TEXT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The font exceeds its region")

    encoded = encode_messages(AwArabicEncoder(font), messages)
    texts = bytearray()
    addresses: dict[str, int] = {}
    for message in messages:
        addresses[message.key] = ARABIC_TEXT_ADDRESS + len(texts)
        texts += encoded[message.key][0]
    if ARABIC_TEXT_ADDRESS + len(texts) > REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic messages exceed the region")

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(FONT_ADDRESS, font_data)
    write(ARABIC_TEXT_ADDRESS, bytes(texts))
    for site in SITES:
        write(site.address, site.patch())
    for message in messages:
        write(message.pointer, struct.pack("<I", addresses[message.key]))

    output = bytes(target)
    _verify_output(output, rom, font_data, messages, encoded, addresses)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "message_lines": {message.key: list(encoded[message.key][1]) for message in messages},
        "line_width_limit": LINE_WIDTH,
        "rtl_glyphs": len(font.glyphs),
        "rtl_codes": f"{min(font.glyphs):02X}..{max(font.glyphs):02X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_sites": len(SITES),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "font_address": f"{FONT_ADDRESS:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(texts),
    }
    return AwArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    rom: bytes,
    font_data: bytes,
    messages: tuple[AwArabicMessage, ...],
    encoded: dict[str, tuple[bytes, tuple[int, ...]]],
    addresses: dict[str, int],
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {_offset(site.address) & ~0xFFF for site in SITES}
    allowed |= {_offset(site.address + len(site.original) - 1) & ~0xFFF for site in SITES}
    allowed |= {_offset(message.pointer) & ~0xFFF for message in messages}
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS) & ~0xFFF, _offset(REGION_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    if IMAGE.read(output, HOOK_CODE_ADDRESS, len(HOOK_CODE)) != HOOK_CODE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook code was not written")
    for site in SITES:
        if IMAGE.read(output, site.address, len(site.original)) != site.patch():
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Site {site.address:#x} was not patched"
            )
    if IMAGE.read(output, FONT_ADDRESS, len(font_data)) != font_data:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The font does not read back")
    for message in messages:
        address = _word(output, message.pointer)
        if address != addresses[message.key]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: pointer not repointed"
            )
        stored = encoded[message.key][0]
        if IMAGE.read(output, address, len(stored)) != stored or read_message(
            output, address
        ) != stored.rstrip(b"\x00"):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key} does not read back"
            )
        if _word(output, message.pointer - 4) != MESSAGE_COMMAND:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: its script command moved"
            )


def check_advance_wars_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every message."""
    font = build_advance_wars_rtl_font(font_path) if font_path is not None else None
    if font is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    messages = advance_wars_arabic_messages(translations)
    encoded = encode_messages(AwArabicEncoder(font), messages)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [(message.key, stored_preview(font, encoded[message.key][0])) for message in messages]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(data) for data, _ in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["rtl_glyphs"] = len(font.glyphs)
        report["widest_line"] = max(max(widths) for _, widths in encoded.values())
    return report


def stored_preview(font: AwRtlFont, stored: bytes) -> Image.Image:
    """``message_preview`` of a stored message (its zeros left out)."""
    return message_preview(font, stored.rstrip(b"\x00"))


def encode_advance_wars_arabic_message(
    text: str, font_path: Path | None = None
) -> dict[str, object]:
    """Encode one message text in notation; with a font, the width of each line."""
    font = build_advance_wars_rtl_font(font_path) if font_path is not None else None
    result = AwArabicEncoder(font).encode(parse_notation(text))
    payload: dict[str, object] = {"bytes": result.body.hex(" "), "count": len(result.body)}
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = LINE_WIDTH
    return payload


def write_build_outputs(
    build: AwArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[AwArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    messages = messages or advance_wars_arabic_messages(translations)
    _verify_anchors(rom)
    return {message.key: text_notation(_verify_source(rom, message)) for message in messages}


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
