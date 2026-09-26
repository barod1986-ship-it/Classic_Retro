from __future__ import annotations

import hashlib
import heapq
import json
import shutil
import struct
from collections import Counter

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fire_emblem import (
    RAW_POINTER_FLAG,
    FireEmblemGlyph,
    FireEmblemHuffmanModel,
    command_skeleton,
    read_message,
)
from classic_retro.engines.fire_emblem_arabic import (
    ARABIC_CODE_BASE,
    CELL_HEIGHT,
    FALLBACK_CODE,
    RTL_MARKER,
    SPACE,
    SPACE_ADVANCE,
    USA_TALK_ADVANCES,
    FireEmblemRtlFont,
    TalkBox,
    build_fire_emblem_arabic_glyph_map,
    fire_emblem_stream,
)
from classic_retro.engines.fire_emblem_legend import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    LegendImage,
    decode_legend_image,
    encode_legend_image,
    legend_budget,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rebuild.lz77 import decompress_lz77
from classic_retro.rom import fire_emblem_arabic as overlay
from classic_retro.rom.fire_emblem_arabic_script import (
    FireEmblemArabicMessage,
    fire_emblem_arabic_legend,
)

BASE = overlay.ROM_BASE
TEXT_DATA = 0x08100000
GLYPH_DATA = 0x08580000
NARRATION = 1
BUBBLE = 2
ENGLISH = {
    NARRATION: b"The continent.\x03\x01Magvel.\x1f\x03\x02\x01\x80\x04Renais.\x03\x01\x80\x04\x00",
    BUBBLE: b"\x09\x10\x51\x01\x09Your Majesty.\x1f\x03\x01Go now!\x03\x00",
}


def _english(index: int) -> bytes:
    return ENGLISH.get(index, b"Line %d\x00" % (index % 7))


def _huffman(messages: list[bytes]) -> tuple[list[int], list[bytes]]:
    """Leaves hold one byte; nodes are laid out so that the root comes last."""
    weights = Counter(byte for message in messages for byte in message)
    heap: list[tuple[int, int, object]] = [(count, byte, byte) for byte, count in weights.items()]
    heapq.heapify(heap)
    order = 256
    while len(heap) > 1:
        a, b = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, (a[0] + b[0], order, (a[2], b[2])))
        order += 1
    nodes: list[int] = []
    codes: dict[int, str] = {}

    def place(tree: object, prefix: str) -> int:
        if isinstance(tree, int):
            codes[tree] = prefix
            nodes.append(0x80000000 | tree)
            return len(nodes) - 1
        left = place(tree[0], prefix + "0")
        right = place(tree[1], prefix + "1")
        nodes.append(left | right << 16)
        return len(nodes) - 1

    place(heap[0][2], "")
    encoded = []
    for message in messages:
        bits = "".join(codes[byte] for byte in message)
        bits += "0" * (-len(bits) % 8)
        encoded.append(bytes(int(bits[i : i + 8][::-1], 2) for i in range(0, len(bits), 8)))
    return nodes, encoded


def _synthetic_rom(messages: list[bytes]) -> bytes:
    rom = bytearray(b"\xff" * overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - BASE : address - BASE + len(data)] = data

    put(overlay.DECODER_ADDRESS, overlay.DECODER_ORIGINAL)
    put(overlay.VENEER_ADDRESS, overlay.VENEER_ORIGINAL)
    for site in overlay.HOOK_SITES:
        put(site.address, site.original)
    put(overlay.TALK_STATE_POINTER, struct.pack("<I", overlay.TALK_STATE_ADDRESS))
    for number, entry in enumerate(overlay.LEGEND_ORIGINAL):
        put(
            overlay.LEGEND_TABLE_ADDRESS + number * overlay.LEGEND_ENTRY_BYTES,
            struct.pack("<III", *entry),
        )

    nodes, encoded = _huffman(messages)
    slots = (overlay.HUFFMAN_ROOT_POINTER - overlay.HUFFMAN_TABLE_ADDRESS) // 4
    shift = slots - len(nodes)
    table = [0] * shift
    for node in nodes:
        table.append(
            node if node & 0x80000000 else (node & 0xFFFF) + shift | (node >> 16) + shift << 16
        )
    put(overlay.HUFFMAN_TABLE_ADDRESS, struct.pack(f"<{slots}I", *table))
    put(overlay.HUFFMAN_ROOT_POINTER, struct.pack("<I", overlay.HUFFMAN_ROOT_POINTER - 4))
    cursor = TEXT_DATA
    for index, data in enumerate(encoded):
        put(overlay.MESSAGE_TABLE_ADDRESS + 4 * index, struct.pack("<I", cursor))
        put(cursor, data)
        cursor += len(data)

    put(overlay.TALK_GLYPHS_ADDRESS, bytes(4 * 256))
    for code in range(0x21, 0x7F):
        # Glyphs outside the pinned table have ink above row 3 and are left out.
        width = USA_TALK_ADVANCES.get(chr(code), 5)
        top = 3 if chr(code) in USA_TALK_ADVANCES else 1
        rows = tuple(0b1011 if top <= row < 14 else 0 for row in range(CELL_HEIGHT))
        glyph = GLYPH_DATA + 72 * code
        put(glyph, FireEmblemGlyph(width, rows).encode())
        put(overlay.TALK_GLYPHS_ADDRESS + 4 * code, struct.pack("<I", glyph))
    return bytes(rom)


def _fake_font(font_path, talk=None, **_kwargs) -> FireEmblemRtlFont:
    glyph_map = build_fire_emblem_arabic_glyph_map()
    ink = (0b0111,) * (CELL_HEIGHT - 1) + (0,)
    glyphs = {
        ARABIC_CODE_BASE + slot: FireEmblemGlyph(5, ink)
        for slot in range(len(glyph_map.characters))
    }
    for character, width in USA_TALK_ADVANCES.items():
        glyphs[ord(character)] = FireEmblemGlyph(width, ink)
    glyphs[SPACE] = FireEmblemGlyph(SPACE_ADVANCE, (0,) * CELL_HEIGHT)
    glyphs[0x1F] = FireEmblemGlyph(0, (0,) * CELL_HEIGHT)
    return FireEmblemRtlFont(
        glyphs=glyphs, font_size=10, arabic_widths=dict.fromkeys(glyph_map.characters, 5)
    )


def _fake_legend(font_path, subtitles=None) -> overlay.BuiltLegend:
    """A checkerboard band per image instead of drawn text (no font needed)."""
    items = []
    for subtitle in fire_emblem_arabic_legend():
        pixels = bytes(
            (x // 8 + y // 8 + subtitle.index) % 13 + 1 if 72 <= y < 88 and 16 <= x < 96 else 0
            for y in range(SCREEN_HEIGHT)
            for x in range(SCREEN_WIDTH)
        )
        image = LegendImage(pixels=pixels, lines=subtitle.lines, widths=(80,))
        encoded = encode_legend_image(image, legend_budget(subtitle.index))
        items.append(overlay.BuiltSubtitle(subtitle=subtitle, image=image, encoded=encoded))
    return overlay.BuiltLegend(font_size=13, items=tuple(items))


def _translations(messages: list[bytes]) -> tuple[FireEmblemArabicMessage, ...]:
    def pinned(index: int, box: TalkBox, notation: str) -> FireEmblemArabicMessage:
        return FireEmblemArabicMessage(
            index=index,
            speakers="test",
            box=box,
            source_sha256=hashlib.sha256(messages[index]).hexdigest(),
            source_skeleton=command_skeleton(messages[index]),
            stream=fire_emblem_stream(notation),
        )

    return (
        pinned(
            NARRATION,
            TalkBox.WORLD_MAP,
            "القارة.[A][LF]ماغفيل.[.][A][CR][LF][BreakTalk]رينيه.[A][LF][BreakTalk][X]",
        ),
        pinned(
            BUBBLE,
            TalkBox.BUBBLE,
            "[OpenMidLeft][LoadFace 51 01][OpenMidLeft]مولاي.[.][A][LF]اذهب الآن![A][X]",
        ),
    )


@pytest.fixture(scope="module")
def english():
    return [_english(index) for index in range(overlay.MESSAGE_COUNT)]


@pytest.fixture(scope="module")
def build(english, tmp_path_factory):
    patcher = pytest.MonkeyPatch()
    patcher.setattr(overlay, "build_fire_emblem_rtl_font", _fake_font)
    patcher.setattr(overlay, "build_legend", _fake_legend)
    font_file = tmp_path_factory.mktemp("font") / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    rom = _synthetic_rom(english)
    try:
        result = overlay.build_fire_emblem_arabic_rom(
            rom, font_file, messages=_translations(english), verify_identity=False
        )
    finally:
        patcher.undo()
    return rom, result


def _read(output: bytes, index: int) -> bytes:
    model = FireEmblemHuffmanModel.parse(
        output,
        overlay.HUFFMAN_TABLE_ADDRESS - BASE,
        overlay.HUFFMAN_ROOT_POINTER - BASE,
    )
    (pointer,) = struct.unpack_from("<I", output, overlay.MESSAGE_TABLE_ADDRESS - BASE + 4 * index)
    return read_message(output, pointer, model)


def test_overlay_places_hooks_veneers_and_the_glyph_table(build):
    rom, result = build
    output = result.rom

    assert len(output) == overlay.USA_SIZE
    code = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[code : code + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    decoder = overlay.DECODER_ADDRESS - BASE
    hook_decomp = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS["hook_decomp"]
    assert output[decoder : decoder + 8] == overlay.decoder_jump(hook_decomp)
    assert output[decoder + 8 : decoder + 20] == overlay.DECODER_ORIGINAL[8:]
    for number, site in enumerate(overlay.HOOK_SITES):
        stub = overlay.VENEER_ADDRESS + number * overlay.VENEER_BYTES
        start = site.address - BASE
        assert overlay.bl_target(site.address, output[start : start + 4]) == stub
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        assert output[stub - BASE : stub - BASE + 16] == overlay.veneer(target)
    # The rest of the unused routine stays as it was.
    used = overlay.VENEER_ADDRESS - BASE + len(overlay.HOOK_SITES) * overlay.VENEER_BYTES
    end = overlay.VENEER_ADDRESS - BASE + len(overlay.VENEER_ORIGINAL)
    assert output[used:end] == rom[used:end]

    table = overlay.RTL_FONT_ADDRESS - BASE
    pointers = struct.unpack_from("<256I", output, table)
    assert pointers[0] == 0 and pointers[0x80] == 0 and pointers[0x81] == 0
    assert pointers[FALLBACK_CODE] and pointers[ARABIC_CODE_BASE]
    glyph = pointers[SPACE] - BASE
    assert output[glyph + 5] == SPACE_ADVANCE


def test_translated_messages_are_raw_and_every_other_message_is_untouched(build, english):
    rom, result = build
    output = result.rom

    for index in (NARRATION, BUBBLE):
        (pointer,) = struct.unpack_from(
            "<I", output, overlay.MESSAGE_TABLE_ADDRESS - BASE + 4 * index
        )
        assert pointer & RAW_POINTER_FLAG
        assert overlay.ARABIC_TEXT_ADDRESS <= pointer & ~RAW_POINTER_FLAG < overlay.REGION_END
        data = _read(output, index)
        assert data[0] == RTL_MARKER and data[-1] == 0
        assert command_skeleton(data[1:]) == command_skeleton(english[index])
        assert any(code >= ARABIC_CODE_BASE for code in data)
    for index in (0, 3, 100, overlay.MESSAGE_COUNT - 1):
        assert _read(output, index) == english[index]
    assert result.report["messages"] == ["0x1", "0x2"]
    assert result.report["message_boxes"] == {"0x1": "world-map", "0x2": "bubble"}
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    # Code pages of the hook sites, the message table, then the new region.
    region = range(overlay.HOOK_CODE_ADDRESS - BASE, overlay.REGION_END - BASE)
    assert {page for page in changed if page not in region} == {
        0x2000, 0x3000, 0x6000, 0x7000, 0x8000, 0x15D000, 0x206000, 0x207000
    }  # fmt: skip
    assert {0xF00000, 0xF01000, 0xF08000, 0xF10000} <= changed


def test_legend_images_are_repointed_and_decompress_back(build):
    rom, result = build
    output = result.rom

    for number, (gfx, _tile_map, frames) in enumerate(overlay.LEGEND_ORIGINAL):
        entry = overlay.LEGEND_TABLE_ADDRESS + number * overlay.LEGEND_ENTRY_BYTES
        new_gfx, new_map, new_frames = struct.unpack_from("<III", output, entry - BASE)
        assert new_frames == frames
        assert overlay.ARABIC_LEGEND_ADDRESS <= new_gfx < new_map < overlay.REGION_END
        tiles = decompress_lz77(output[new_gfx - BASE :])
        arrangement = decompress_lz77(output[new_map - BASE :])
        assert decode_legend_image(tiles, arrangement) == result.legend[number].pixels
        # The game's own images stay where they were.
        assert output[gfx - BASE : gfx - BASE + 64] == rom[gfx - BASE : gfx - BASE + 64]
    assert [item["index"] for item in result.report["legend"]] == list(range(7))
    assert result.report["legend_font_size"] == 13


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, result = build

    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["patch_bytes"] == len(result.patch.data)
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(overlay.USA_SIZE))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize(
    "damage", ["site", "decoder", "veneer", "state", "padding", "glyph", "legend"]
)
def test_changed_anchors_are_refused(english, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_fire_emblem_rtl_font", _fake_font)
    monkeypatch.setattr(overlay, "build_legend", _fake_legend)
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    rom = bytearray(_synthetic_rom(english))
    if damage == "site":
        rom[overlay.HOOK_SITES[2].address - BASE] ^= 0xFF
    elif damage == "decoder":
        rom[overlay.DECODER_ADDRESS - BASE + 17] ^= 0xFF
    elif damage == "veneer":
        rom[overlay.VENEER_ADDRESS - BASE + 90] ^= 0xFF
    elif damage == "state":
        rom[overlay.TALK_STATE_POINTER - BASE] ^= 0x04
    elif damage == "padding":
        rom[overlay.REGION_END - BASE - 1] = 0
    elif damage == "legend":
        rom[overlay.LEGEND_TABLE_ADDRESS - BASE + 8] ^= 0x01
    else:
        rom[GLYPH_DATA - BASE + 72 * ord("!") + 5] += 1

    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_fire_emblem_arabic_rom(
            bytes(rom), font_file, messages=_translations(english), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


def test_changed_script_is_refused(english, tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_fire_emblem_rtl_font", _fake_font)
    monkeypatch.setattr(overlay, "build_legend", _fake_legend)
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    translations = _translations(english)
    edited = list(english)
    edited[BUBBLE] = english[BUBBLE].replace(b"Go now", b"Run now")

    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_fire_emblem_arabic_rom(
            _synthetic_rom(edited), font_file, messages=translations, verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_bl_helpers_round_trip_and_reject_far_targets():
    site = overlay.HOOK_SITES[0].address
    assert overlay.bl_target(site, overlay.bl_instruction(site, overlay.VENEER_ADDRESS)) == (
        overlay.VENEER_ADDRESS
    )
    assert overlay.bl_target(site, overlay.HOOK_SITES[0].original) == 0x08008B44
    with pytest.raises(ClassicRetroError) as caught:
        overlay.bl_instruction(site, overlay.HOOK_CODE_ADDRESS)
    assert caught.value.code is ErrorCode.WRITE_OUT_OF_BOUNDS


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_hook_source_reassembles_to_the_stored_bytes():
    assert overlay.check_hook_code()["match"] is True


def test_cli_checks_the_script_and_encodes_a_line(capsys):
    assert main(["targets", "check-translations", "fire-emblem"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["lines_measured"] is False
    assert report["messages"] == ["0x8db", "0x903", "0x904", "0x905", "0x906"]
    assert report["legend_images"] == 7

    assert main(["fire-emblem", "encode-arabic", "مرحبا![A]", "--box", "world-map"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    assert encoded["bytes"].startswith(f"{RTL_MARKER:02x} ")
    assert encoded["bytes"].endswith("03 00")


def test_cli_refuses_an_unknown_rom(tmp_path, capsys):
    rom = tmp_path / "game.gba"
    rom.write_bytes(bytes(64))
    font = tmp_path / "font.ttf"
    font.write_bytes(b"x")

    code = main(
        [
            "targets",
            "build",
            "fire-emblem",
            str(rom),
            "--font",
            str(font),
            "--out-dir",
            str(tmp_path / "o"),
        ]
    )
    assert code == 2
    assert "UNKNOWN_GAME_REVISION" in capsys.readouterr().err


def test_extract_reads_every_message_in_the_notation(english):
    originals = overlay.extract_originals(
        _synthetic_rom(english), messages=_translations(english), verify_identity=False
    )
    assert originals == {
        f"message.{NARRATION:#x}": (
            "The continent.[A][LF]Magvel.[.][A][CR][LF][BreakTalk]Renais.[A][LF][BreakTalk][X]"
        ),
        f"message.{BUBBLE:#x}": (
            "[OpenMidLeft][LoadFace 51 01][OpenMidLeft]Your Majesty.[.][A][LF]Go now![A][X]"
        ),
    }
