"""Arabic ROM overlay for *Tactics Ogre: The Knight of Lodis* (USA).

The jiangzhengwenjz/totkol disassembly gives the code's addresses, but it
takes its data from the original and cannot be shifted, so the overlay patches
the user's image (``ATOE``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced or relied on are
   verified, and so are the scene's block, every translated message's original
   (its pinned hash and commands) and the names they use;
2. the Thumb hooks (``tactics_ogre_arabic_hooks.s``), the right-to-left glyph
   widths and glyphs (``engines.tactics_ogre_arabic``) and the texts go into
   the zeros after the end of the image's data; the image stays 8 MiB;
3. the width measure and the dialogue's glyph call reach their hooks through
   veneers written over sub_0801C498, which nothing calls, since the padding is
   out of a BL's reach;
4. the scene's block is copied: its table and the messages left in English go
   to the block area, each translated message to the Arabic bank, and every
   scene entry of the block is repointed to the copy. A message of the Arabic
   bank is what the hooks turn right to left.

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
from classic_retro.cpu.thumb import NOP, arm_veneer, bl_instruction, literal_jump
from classic_retro.engines.tactics_ogre import (
    END,
    FONT_WIDTHS,
    GLYPH_CODES,
    NAME_LIST,
    ROM_BASE,
    SCENE_TEXTS,
    SCENES,
    TABLE_END,
    command_skeleton,
    parse_notation,
    read_block,
    read_message,
    read_name,
    text_notation,
)
from classic_retro.engines.tactics_ogre_arabic import (
    BASELINE,
    LINE_WIDTH,
    RTL_GLYPH_BYTES,
    ToArabicEncoder,
    ToRtlFont,
    build_tactics_ogre_rtl_font,
    font_preview,
    message_preview,
    messages_sheet,
    painted_characters,
    tactics_ogre_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.tactics_ogre_arabic_script import (
    BLOCK_ADDRESS,
    BLOCK_MESSAGES,
    SCENE,
    ToArabicMessage,
    ToArabicName,
    tactics_ogre_arabic_messages,
    tactics_ogre_arabic_names,
)

USA_SHA256 = "c5b439c2530331f38e7a6e16857f58c554f270019641f825ac060f4e7866bae4"
USA_SIZE = 0x800000
IMAGE_END = ROM_BASE + USA_SIZE

# The zeros after the end of the image's data (0x087D6A30, where the
# disassembly's rom_end is) up to the end of the image.
DATA_END = 0x087D6A30
PADDING = 0x00
HOOK_CODE_ADDRESS = 0x087D7000
RTL_WIDTHS_ADDRESS = 0x087D7400
RTL_GLYPHS_ADDRESS = 0x087D8000
RTL_GLYPHS_END = RTL_GLYPHS_ADDRESS + GLYPH_CODES * RTL_GLYPH_BYTES
# The copied blocks' tables and their English messages, then the Arabic bank:
# every message the hooks turn right to left, up to the end of the image.
BLOCK_AREA = RTL_GLYPHS_END
ARABIC_TEXT_ADDRESS = 0x087E0000
ARABIC_TEXT_END = IMAGE_END
HOOK_SOURCE = Path(__file__).with_name("tactics_ogre_arabic_hooks.s")

# The game's code the hooks call or rely on (addresses from the disassembly).
MEASURE_WIDTH = 0x08014560
DRAW_CALL = 0x080158F0
DRAW_GLYPH = 0x0801B0C8
TEXT_WINDOW = 0x0200283C
LINE_COLUMNS = 0x1BA0
LINE_START = 0x1BC0
PEN = 0x030008C0
# sub_0801C498: a glyph routine nothing calls or points to, near the text
# routines (the SHA-256 of the bytes the veneers overwrite).
VENEER_AREA = 0x0801C498
VENEER_AREA_SIZE = 32
VENEER_AREA_SHA256 = "5c531274128a805141811aa9a8305e3006c9e31759feb524ec96d9c30027097f"
# The scene's block as the image holds it: its table and 35 messages.
BLOCK_END = 0x08784C9A
BLOCK_SHA256 = "a716b6a4d403864d6aaa297192eac3077b28ffe48a9d679f93e2db19d080056b"
# The scene entries that read the block (a new game reads SCENE).
SCENE_ENTRIES = (0, 1)

# arm-none-eabi-as -mcpu=arm7tdmi tactics_ogre_arabic_hooks.s; ld -Ttext 0x087D7000; objcopy
HOOK_CODE = bytes.fromhex(
    "20782f49611a2f4a91422f4900d22f49085c70472a48201a2a4a904205d30020"
    "01222b4b9c4600236047f0b52748475c2848c9014618284800682849425c2849"
    "435cdb00274d2c89d008c00000191b1adb1b00d50023e4192c81e408a4012968"
    "0c196c60d2089201891ada0892018d18072003409b002024e41a402030188446"
    "3068316c043602009a4002d02f6817432f60e0400a009a40024304d040352f68"
    "17432f60403de14004d080352f680f432f60803d04356645e2d1f0bc01bc0047"
    "00007e08000002006cde150800747d08c9b0010800807d083c280002c01b0000"
    "a01b0000c0080003"
)
HOOK_SYMBOLS = {"hook_draw": 0x14, "hook_width": 0x00}
IMAGE = ImageSpec("Tactics Ogre: The Knight of Lodis (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("Tactics Ogre hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "tactics-ogre-usa-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class Veneer:
    """A jump to a hook, in the veneer area: through ip (an ARM veneer) or a low register."""

    address: int
    hook: str
    register: int | None = None

    def code(self) -> bytes:
        target = HOOKS.symbol_address(self.hook)
        if self.register is None:
            return arm_veneer(target)
        return literal_jump(self.address, self.register, target)


VENEERS = {
    veneer.hook: veneer
    for veneer in (
        # At the glyph call: ip, which the called routine may clobber.
        Veneer(0x0801C498, "hook_draw"),
        # In the measure, r1 is set again before it is read.
        Veneer(0x0801C4A8, "hook_width", 1),
    )
}


@dataclass(frozen=True, slots=True)
class Site:
    """Game code replaced by a BL to a hook's veneer (and ``nop`` for the rest)."""

    address: int
    original: bytes
    hook: str

    def patch(self) -> bytes:
        call = bl_instruction(self.address, VENEERS[self.hook].address)
        return call + NOP * ((len(self.original) - len(call)) // 2)


SITES = (
    # The measure (0x080143E0): `ldr r0, =widths; ldrb r1, [r4]; adds r1, r1, r0;
    # ldrb r0, [r1]`; the hook returns the width in r0.
    Site(MEASURE_WIDTH, bytes.fromhex("0a48217809180878"), "hook_width"),
    # The dialogue (0x08015188): `bl 0x0801B0C8`, for a glyph or a space.
    Site(DRAW_CALL, bl_instruction(DRAW_CALL, DRAW_GLYPH), "hook_draw"),
)

# Bytes the hooks rely on without replacing them:
ANCHORS = {
    # the measure's table of widths, and what it does with the width;
    0x0801458C: struct.pack("<I", FONT_WIDTHS),
    0x08014568: bytes.fromhex("2d180134"),
    # the dialogue's glyph: the byte at r4, drawn with r0 = 0, r1, r2 = 1, r3 = 0
    # when it is below 0x80 or 0x89;
    0x080158D4: bytes.fromhex("257800202056002802db0020291c03e0892d06d10020892101220023"),
    # the window's data, where its lines start ([window + 0x1BC0]), their width
    # in columns ([window + 0x1BA0] * 8) and a new line at its first column;
    0x08015328: struct.pack("<I", TEXT_WINDOW),
    0x0801537A: bytes.fromhex("3c4c2068de21490140180270"),
    0x080157DE: bytes.fromhex("2968dd22520189180978c9000006000e"),
    0x0801581E: bytes.fromhex(
        "3868de235b01c018017039680d4c081902780c4d4819008850434000089e3018c918097806f0b1fb"
    ),
    # the page cleared before it is drawn (rows x columns x 64 bytes);
    0x08015260: bytes.fromhex(
        "0024049404a82968394bca1812780b33c918097809014a43802149040a43089943f138fe"
    ),
    # the pen: a line starts at its first column (sub_0801BFA8), and the game's
    # routine moves it by a glyph's width and its column with it;
    0x0801BFA8: bytes.fromhex(
        "30b581b00906090e114cf8220a40d20080182060606007200840002520816581e581a581"
    ),
    0x0801BFF8: struct.pack("<I", PEN),
    0x0801B5C8: bytes.fromhex(
        "134d1449009f79182889097840182881114820400204510b686840186860072020400028"
    ),
    0x0801B618: struct.pack("<II", PEN, FONT_WIDTHS),
    # the scene entries that read the block.
    SCENE_TEXTS + 4 * SCENE_ENTRIES[0]: struct.pack(
        f"<{len(SCENE_ENTRIES)}I", *(BLOCK_ADDRESS - SCENE_TEXTS for _ in SCENE_ENTRIES)
    ),
}


@dataclass(frozen=True, slots=True)
class ToArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: ToRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset
_word = IMAGE.word


def source_digest(data: bytes) -> str:
    """SHA-256 of an original message's bytes, up to its final ``FF``."""
    return hashlib.sha256(data).hexdigest()


def stored_message(header: int, data: bytes) -> bytes:
    """A message as a block holds it: its header, its bytes and ``FF``, then a zero to a halfword."""
    stored = struct.pack("<H", header) + data + bytes((END,))
    return stored + bytes(len(stored) % 2)


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> None:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 8 MiB")
    expected = {**{site.address: site.original for site in SITES}, **ANCHORS}
    for address, original in expected.items():
        if IMAGE.read(rom, address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x}"
            )
    veneer_area = IMAGE.read(rom, VENEER_AREA, VENEER_AREA_SIZE)
    if hashlib.sha256(veneer_area).hexdigest() != VENEER_AREA_SHA256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected code at {VENEER_AREA:#x}"
        )
    if not IMAGE.filled(rom, DATA_END, IMAGE_END, PADDING):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{DATA_END:#x}..{IMAGE_END:#x} is not empty padding",
        )
    # The hooks' literals: the bank and its size, the widths, the glyphs, the
    # game's widths, the window, the pen and the game's glyph routine.
    for value in (
        ARABIC_TEXT_ADDRESS,
        ARABIC_TEXT_END - ARABIC_TEXT_ADDRESS,
        RTL_WIDTHS_ADDRESS,
        RTL_GLYPHS_ADDRESS,
        FONT_WIDTHS,
        TEXT_WINDOW,
        LINE_COLUMNS,
        LINE_START,
        PEN,
        DRAW_GLYPH | 1,
    ):
        if struct.pack("<I", value) not in HOOK_CODE:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The hooks do not use {value:#x}"
            )


def _verify_block(rom: bytes) -> tuple[int, ...]:
    """The scene's block, byte for byte, and the entries that read it; its offsets."""
    block = IMAGE.read(rom, BLOCK_ADDRESS, BLOCK_END - BLOCK_ADDRESS)
    if hashlib.sha256(block).hexdigest() != BLOCK_SHA256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"The block at {BLOCK_ADDRESS:#x} differs from the pinned USA script",
        )
    entries = tuple(
        scene
        for scene in range(SCENES)
        if _word(rom, SCENE_TEXTS + 4 * scene) == BLOCK_ADDRESS - SCENE_TEXTS
    )
    if entries != SCENE_ENTRIES or SCENE not in entries:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"The block is read by scene entries {entries}, not {SCENE_ENTRIES}",
        )
    offsets = read_block(rom, BLOCK_ADDRESS).offsets
    if len(offsets) != BLOCK_MESSAGES:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"The block holds {len(offsets)} messages"
        )
    return offsets


def _verify_source(rom: bytes, message: ToArabicMessage, offsets: Sequence[int]) -> bytes:
    if not 0 <= message.index < len(offsets):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{message.key}: no message {message.index}"
        )
    if BLOCK_ADDRESS + offsets[message.index] != message.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: message {message.index} is not at {message.source_address:#x}",
        )
    try:
        header, original = read_message(rom, message.source_address)
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: no message at {message.source_address:#x}",
        ) from exc
    if header != message.header or source_digest(original) != message.source_sha256:
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


def _verify_name(rom: bytes, name: ToArabicName) -> bytes:
    if _word(rom, NAME_LIST + 4 * name.index) != name.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{name.key}: name {name.index} is not at {name.source_address:#x}",
        )
    original = read_name(rom, name.index)
    if source_digest(original) != name.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{name.key}: the original at {name.source_address:#x} differs from the pinned "
            "USA name",
        )
    return original


def name_texts(names: Sequence[ToArabicName]) -> dict[int, str]:
    """Each name's Arabic by its index in the list; a name has no commands or line ends."""
    texts: dict[int, str] = {}
    for name in names:
        if name.index in texts:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Name {name.index} twice")
        if any(not isinstance(piece, str) for piece in parse_notation(name.text)):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{name.key}: a name is text only"
            )
        texts[name.index] = name.text
    return texts


def script_glyph_codes(messages: Sequence[ToArabicMessage], names: Mapping[int, str]) -> GlyphCodes:
    """The codes of every character the translated messages paint."""
    characters: set[str] = set()
    for message in messages:
        characters |= painted_characters(message.pieces, names)
    return tactics_ogre_glyph_codes(characters)


@dataclass(frozen=True, slots=True)
class ToEncodedMessage:
    """A translated message as the bank stores it, its bytes and, with a font, its lines."""

    stored: bytes
    data: bytes
    line_widths: tuple[int, ...]


def encode_messages(
    encoder: ToArabicEncoder,
    messages: Sequence[ToArabicMessage],
    names: Mapping[int, str],
) -> dict[str, ToEncodedMessage]:
    """Validate every translation against its original's commands and encode it."""
    encoded: dict[str, ToEncodedMessage] = {}
    indexes: set[int] = set()
    for message in messages:
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.key} twice")
        if message.index in indexes:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{message.key} shares message {message.index}"
            )
        indexes.add(message.index)
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces, names, message.lines_per_page)
        encoded[message.key] = ToEncodedMessage(
            stored_message(message.header, result.data), result.data, result.line_widths or ()
        )
    return encoded


@dataclass(frozen=True, slots=True)
class ArabicBlock:
    """The copied block: its table and English messages at ``address``, its Arabic in the bank."""

    address: int
    head: bytes
    arabic: bytes
    offsets: tuple[int, ...]
    addresses: dict[str, int]


def arabic_block(
    rom: bytes,
    offsets: Sequence[int],
    messages: Sequence[ToArabicMessage],
    encoded: Mapping[str, ToEncodedMessage],
) -> ArabicBlock:
    """The block with every translated message in the bank and the others copied as they are."""
    translated = {message.index: message for message in messages}
    address = BLOCK_AREA
    head = bytearray(struct.pack(f"<{len(offsets) + 1}H", *([0] * len(offsets)), TABLE_END))
    arabic = bytearray()
    new_offsets: list[int] = []
    addresses: dict[str, int] = {}
    for index, offset in enumerate(offsets):
        message = translated.get(index)
        if message is None:
            header, original = read_message(rom, BLOCK_ADDRESS + offset)
            where = address + len(head)
            head += stored_message(header, original)
        else:
            where = ARABIC_TEXT_ADDRESS + len(arabic)
            arabic += encoded[message.key].stored
            addresses[message.key] = where
        if not 0 <= where - address < TABLE_END:
            raise ClassicRetroError(
                ErrorCode.RELOCATION_OVERFLOW,
                f"Message {index} is out of the block's 16-bit reach",
            )
        new_offsets.append(where - address)
    head[: 2 * len(new_offsets)] = struct.pack(f"<{len(new_offsets)}H", *new_offsets)
    if address + len(head) > ARABIC_TEXT_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The block exceeds its area")
    if ARABIC_TEXT_ADDRESS + len(arabic) > ARABIC_TEXT_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic texts exceed the bank")
    return ArabicBlock(address, bytes(head), bytes(arabic), tuple(new_offsets), addresses)


def build_tactics_ogre_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[ToArabicMessage, ...] | None = None,
    names: tuple[ToArabicName, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> ToArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages``, ``names`` and ``verify_identity`` exist for synthetic tests; a
    real build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    _verify_anchors(rom)
    offsets = _verify_block(rom)
    messages = messages or tactics_ogre_arabic_messages(translations)
    names = names or tactics_ogre_arabic_names(translations)
    for message in messages:
        _verify_source(rom, message, offsets)
    for name in names:
        _verify_name(rom, name)
    arabic_names = name_texts(names)
    glyph_map = script_glyph_codes(messages, arabic_names)
    font = build_tactics_ogre_rtl_font(font_path, glyph_map)
    widths = font.width_table()
    glyphs = font.glyph_table()
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > RTL_WIDTHS_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")
    if RTL_GLYPHS_ADDRESS + len(glyphs) > RTL_GLYPHS_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The glyphs exceed their region")

    encoded = encode_messages(ToArabicEncoder(glyph_map, font), messages, arabic_names)
    block = arabic_block(rom, offsets, messages, encoded)

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(RTL_WIDTHS_ADDRESS, widths)
    write(RTL_GLYPHS_ADDRESS, glyphs)
    write(block.address, block.head)
    write(ARABIC_TEXT_ADDRESS, block.arabic)
    for veneer in VENEERS.values():
        write(veneer.address, veneer.code())
    for site in SITES:
        write(site.address, site.patch())
    for scene in SCENE_ENTRIES:
        write(SCENE_TEXTS + 4 * scene, struct.pack("<I", block.address - SCENE_TEXTS))

    output = bytes(target)
    _verify_output(output, rom, widths, glyphs, messages, encoded, block)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "names": len(names),
        "message_lines": {
            message.key: list(encoded[message.key].line_widths) for message in messages
        },
        "line_width_limit": LINE_WIDTH,
        "rtl_glyphs": len(font.glyphs),
        "rtl_codes": f"{min(font.glyphs):02X}..{max(font.glyphs):02X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_sites": len(SITES),
        "veneers": len(VENEERS),
        "scene_entries": len(SCENE_ENTRIES),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "glyphs_address": f"{RTL_GLYPHS_ADDRESS:#x}",
        "block_address": f"{block.address:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(block.arabic),
    }
    return ToArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    rom: bytes,
    widths: bytes,
    glyphs: bytes,
    messages: Sequence[ToArabicMessage],
    encoded: Mapping[str, ToEncodedMessage],
    block: ArabicBlock,
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    written = [
        (VENEER_AREA, VENEER_AREA_SIZE),
        *((site.address, len(site.original)) for site in SITES),
        (SCENE_TEXTS + 4 * SCENE_ENTRIES[0], 4 * len(SCENE_ENTRIES)),
    ]
    allowed = {
        _offset(address + delta) & ~0xFFF
        for address, length in written
        for delta in (0, length - 1)
    }
    allowed |= set(range(_offset(DATA_END) & ~0xFFF, _offset(IMAGE_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    expected = {
        HOOK_CODE_ADDRESS: HOOK_CODE,
        RTL_WIDTHS_ADDRESS: widths,
        RTL_GLYPHS_ADDRESS: glyphs,
        block.address: block.head,
        ARABIC_TEXT_ADDRESS: block.arabic,
        **{veneer.address: veneer.code() for veneer in VENEERS.values()},
        **{site.address: site.patch() for site in SITES},
    }
    for address, data in expected.items():
        if IMAGE.read(output, address, len(data)) != data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{address:#x} does not read back"
            )
    for scene in SCENE_ENTRIES:
        if SCENE_TEXTS + _word(output, SCENE_TEXTS + 4 * scene) != block.address:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Scene entry {scene} not repointed"
            )
    copied = read_block(output, block.address)
    if copied.offsets != block.offsets:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The block does not read back")
    for message in messages:
        address = copied.message_address(message.index)
        header, data = read_message(output, address)
        if (
            address != block.addresses[message.key]
            or stored_message(header, data) != encoded[message.key].stored
        ):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key} does not read back"
            )


def check_tactics_ogre_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every message."""
    if font_path is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    messages = tactics_ogre_arabic_messages(translations)
    arabic_names = name_texts(tactics_ogre_arabic_names(translations))
    glyph_map = script_glyph_codes(messages, arabic_names)
    font = build_tactics_ogre_rtl_font(font_path, glyph_map) if font_path is not None else None
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    encoded = encode_messages(ToArabicEncoder(glyph_map, font), messages, arabic_names)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (
                    message.key,
                    message_preview(font, encoded[message.key].data, message.lines_per_page),
                )
                for message in messages
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "names": len(arabic_names),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(message.data) for message in encoded.values()),
        "rtl_glyphs": len(glyph_map.characters),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["widest_line"] = max(max(message.line_widths) for message in encoded.values())
    return report


def encode_tactics_ogre_arabic_message(
    text: str, font_path: Path | None = None, *, lines_per_page: int = 3
) -> dict[str, object]:
    """Encode one message in notation (its names written out as the script's); with a font,
    the width of each line. Its codes are those of its own characters."""
    pieces = parse_notation(text)
    arabic_names = name_texts(tactics_ogre_arabic_names())
    glyph_map = tactics_ogre_glyph_codes(painted_characters(pieces, arabic_names))
    font = build_tactics_ogre_rtl_font(font_path, glyph_map) if font_path is not None else None
    result = ToArabicEncoder(glyph_map, font).encode(pieces, arabic_names, lines_per_page)
    payload: dict[str, object] = {"bytes": result.data.hex(" ").upper(), "count": len(result.data)}
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = LINE_WIDTH
    return payload


def write_build_outputs(
    build: ToArabicBuild, out_dir: Path, *, rom_name: str | None
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
    messages: tuple[ToArabicMessage, ...] | None = None,
    names: tuple[ToArabicName, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    _verify_anchors(rom)
    offsets = _verify_block(rom)
    messages = messages or tactics_ogre_arabic_messages(translations)
    names = names or tactics_ogre_arabic_names(translations)
    originals = {
        message.key: text_notation(_verify_source(rom, message, offsets)) for message in messages
    }
    originals |= {name.key: text_notation(_verify_name(rom, name)) for name in names}
    return originals


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
