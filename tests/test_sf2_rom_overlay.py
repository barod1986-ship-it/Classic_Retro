from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import struct
from functools import cache

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines import sf2
from classic_retro.engines import sf2_arabic as engine
from classic_retro.engines.sf2 import (
    CHARACTERS,
    END,
    TAGS,
    TAGS_WITH_ARGUMENT,
    TEXT_BANKS,
    TEXT_BANKS_POINTER,
    TREE_DATA,
    TREE_OFFSETS,
    string_bytes,
)
from classic_retro.engines.sf2_arabic import (
    GLYPH_BYTES,
    ROWS,
    SPACE_CODE,
    SPACE_WIDTH,
    WIDEST,
    Sf2Font,
    Sf2Glyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import sf2_arabic as overlay
from classic_retro.rom import sf2_arabic_script as script
from classic_retro.rom.sf2_arabic_script import Sf2String

# Invented English for the three strings; every other string is empty.
ENGLISH = {
    0xD8: "{CLEAR}Hello.{N}Go on!{W2}",
    0xD9: "So.{N}Who?{W2}",
    0xDF: "{NAME;0}...{N}Good.{W2}",
}
ARABIC = {
    "witch.greeting": "{CLEAR}هيه…{N}وصلت!{W2}",
    "witch.confused": "آه.{N}لماذا؟{W2}",
    "witch.nice_name": "{NAME;0}…{N}اسم جميل.{W2}",
}
BANKS = 0x030000


def _symbols(text: str) -> list[int]:
    symbols = []
    for match in re.finditer(r"\{([^}]*)\}|(.)", text):
        tag, letter = match.groups()
        if letter is not None:
            symbols.append(CHARACTERS.index(letter) + 1)
        elif ";" in tag:
            name, argument = tag.split(";")
            symbols += [TAGS_WITH_ARGUMENT[name], int(argument)]
        else:
            symbols.append(TAGS[tag])
    return [*symbols, END]


# One tree for every symbol before: the symbols the English uses, halved a branch at a time.
Tree = int | tuple["Tree", "Tree"]


def _tree(leaves: list[int]) -> Tree:
    if len(leaves) == 1:
        return leaves[0]
    half = len(leaves) // 2
    return (_tree(leaves[:half]), _tree(leaves[half:]))


def _tree_bits(tree: Tree) -> list[int]:
    if isinstance(tree, int):
        return [1]
    return [0, *_tree_bits(tree[0]), *_tree_bits(tree[1])]


def _leaves(tree: Tree) -> list[int]:
    if isinstance(tree, int):
        return [tree]
    return [*_leaves(tree[0]), *_leaves(tree[1])]


def _paths(tree: Tree, path: tuple[int, ...] = ()) -> dict[int, tuple[int, ...]]:
    if isinstance(tree, int):
        return {tree: path}
    return {**_paths(tree[0], (*path, 0)), **_paths(tree[1], (*path, 1))}


def _pack(bits: list[int]) -> bytes:
    bits = bits + [0] * (-len(bits) % 8)
    return bytes(int("".join(map(str, bits[at : at + 8])), 2) for at in range(0, len(bits), 8))


TREE = _tree(sorted({symbol for text in ENGLISH.values() for symbol in _symbols(text)}))
PATHS = _paths(TREE)


def _stored(text: str) -> bytes:
    """A string as the game stores it: its length byte, then its Huffman code."""
    code = _pack([bit for symbol in _symbols(text) for bit in PATHS[symbol]])
    return bytes((len(code),)) + code


@cache
def _rom(change: tuple[tuple[int, bytes], ...] = ()) -> bytes:
    """2 MiB of zeros but the engine's bytes the overlay checks, its free room, a tree and
    a bank of 0xE0 strings (the three translated among them)."""
    rom = bytearray(overlay.ROM_SIZE)
    for site in overlay.SITES:
        rom[site.address : site.address + len(site.original)] = site.original
    for address, data in overlay.ANCHORS.items():
        rom[address : address + len(data)] = data
    rom[overlay.ROOM_START : overlay.ROOM_END] = b"\xff" * (overlay.ROOM_END - overlay.ROOM_START)
    leaves = _leaves(TREE)
    trees = bytes(leaves[::-1]) + _pack(_tree_bits(TREE))
    struct.pack_into(">255H", rom, TREE_OFFSETS, *[len(leaves)] * 255)
    rom[TREE_DATA : TREE_DATA + len(trees)] = trees
    struct.pack_into(">I", rom, TEXT_BANKS_POINTER, BANKS)
    struct.pack_into(f">{TEXT_BANKS}I", rom, BANKS, *[BANKS + 0x100] * TEXT_BANKS)
    bank = b"".join(
        _stored(ENGLISH[index]) if index in ENGLISH else b"\x01\x00" for index in range(0xE0)
    )
    rom[BANKS + 0x100 : BANKS + 0x100 + len(bank)] = bank
    for address, data in change:
        rom[address : address + len(data)] = data
    overlay.set_checksum(rom)
    return bytes(rom)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strings(rom: bytes | None = None) -> tuple[Sf2String, ...]:
    return tuple(
        Sf2String(key, index, _digest(string_bytes(rom or _rom(), index)), ARABIC[key])
        for key, (index, _, _) in script._SOURCES.items()
    )


def _fake_font(font_path=None, glyph_map=None, used=(), **_kwargs) -> Sf2Font:
    """Every glyph a bar 6 pixels wide; the space the real one."""
    assert glyph_map is not None
    bar = Sf2Glyph(6, tuple(tuple(x < 6 for x in range(WIDEST)) for _ in range(ROWS)))
    space = Sf2Glyph(SPACE_WIDTH, ((False,) * WIDEST,) * ROWS)
    return Sf2Font({glyph_map.code(c): space if c == " " else bar for c in used}, 10)


def _build(rom: bytes, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_sf2_font", _fake_font)
        return overlay.build_sf2_arabic_rom(
            rom,
            font_path,
            translated=options.pop("translated", _strings(rom)),
            verify_identity=options.pop("verify_identity", False),
        )


@pytest.fixture(scope="module")
def font_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("font") / "font.ttf"
    path.write_bytes(b"not read by the fake font")
    return path


@pytest.fixture(scope="module")
def built(font_path):
    rom = _rom()
    return rom, _build(rom, font_path)


def test_the_build_changes_only_its_places_and_sets_the_checksum(built):
    rom, result = built
    assert len(result.rom) == overlay.ROM_SIZE and result.rom != rom
    assert apply_bps(result.patch.data, rom) == result.rom
    (checksum,) = struct.unpack_from(">H", result.rom, overlay.CHECKSUM)
    words = struct.unpack_from(f">{(overlay.ROM_SIZE - 0x200) // 2}H", result.rom, 0x200)
    assert sum(words) & 0xFFFF == checksum and result.report["checksum"] == f"{checksum:04X}"
    for site in overlay.SITES:
        assert result.rom[site.address : site.address + len(site.patched)] == site.patched
    changed = {
        at // 0x10000
        for at in range(0, len(rom), 0x1000)
        if rom[at : at + 0x1000] != result.rom[at : at + 0x1000]
    }
    assert changed == {0x00, 0x04}  # the header and the engine's code, the room
    assert result.report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert set(result.report["strings"]) == set(ARABIC)
    # The English stays where it was, as it was.
    assert result.rom[BANKS : BANKS + 0x1000] == rom[BANKS : BANKS + 0x1000]


def test_the_room_holds_the_hooks_the_list_the_font_and_the_arabic(built):
    _, result = built
    out = result.rom
    at = overlay.HOOK_ADDRESS
    assert out[at : at + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    glyph_map = engine.sf2_glyph_codes(overlay.strings_characters(_strings()))
    encoder = engine.Sf2ArabicEncoder(glyph_map, result.font)
    codes = max(result.font.glyphs) + 1
    arabic = overlay.ARABIC_FONT + codes * GLYPH_BYTES
    for number, string in enumerate(_strings()):
        entry = overlay.REDIRECTS + overlay.REDIRECT_ENTRY * number
        index, address = struct.unpack_from(">HI", out, entry)
        assert (index, address) == (string.index, arabic)
        data = encoder.encode(string.notation).data
        assert out[address : address + 1 + len(data)] == bytes((len(data),)) + data
        arabic += 1 + len(data) + (1 + len(data)) % 2  # each starts on a word
    assert out[overlay.REDIRECTS + 18 : overlay.REDIRECTS + 20] == b"\xff\xff"
    assert set(out[arabic : overlay.ROOM_END]) == {0xFF}
    for code, glyph in result.font.glyphs.items():
        start = overlay.ARABIC_FONT + GLYPH_BYTES * code
        assert out[start : start + GLYPH_BYTES] == glyph.data()
    assert out[overlay.ARABIC_FONT : overlay.ARABIC_FONT + GLYPH_BYTES] == bytes(GLYPH_BYTES)


def test_originals_are_extracted_and_verified():
    rom = _rom()
    originals = overlay.extract_originals(rom, translated=_strings(), verify_identity=False)
    assert originals == {
        "witch.greeting": ENGLISH[0xD8],
        "witch.confused": ENGLISH[0xD9],
        "witch.nice_name": ENGLISH[0xDF],
    }
    changed = dataclasses.replace(_strings()[0], source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(changed,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    elsewhere = dataclasses.replace(_strings()[0], index=0xD7)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(elsewhere,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_a_different_rom_is_refused(font_path):
    rom = _rom()
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(rom[:-0x8000])
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        ((0x006273, b"\x00"),),  # a site: where DisplayText looks a string up
        ((0x0064DB, b"\x00"),),  # a site: the arrow's X
        ((0x00629C, b"\x00"),),  # where an Arabic string goes on
        ((0x00697B, b"\x00"),),  # the routine that sends a line to VRAM
        ((0x02800D, b"\x03"),),  # the font's pointer
    ],
)
def test_engine_code_that_differs_where_the_overlay_works_is_refused(change):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(change))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_a_room_that_is_not_free_is_refused():
    rom = _rom(((overlay.ROOM_END - 1, b"\x00"),))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(rom)
    assert caught.value.code is ErrorCode.SAFE_REGION_CONTENT_MISMATCH
    assert str(caught.value) == (
        f"The overlay's room holds data at {overlay.ROOM_END - 1:#x}, where 0xff was expected"
    )


def test_the_arabic_keeps_to_the_room(font_path, monkeypatch):
    rom = _rom()
    with monkeypatch.context() as patch:
        patch.setattr(overlay, "ROOM_END", overlay.ARABIC_FONT + 0x40)
        with pytest.raises(ClassicRetroError) as caught:
            _build(rom, font_path)
        assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    with monkeypatch.context() as patch:
        patch.setattr(overlay, "ARABIC_FONT", overlay.REDIRECTS + 8)
        with pytest.raises(ClassicRetroError) as caught:
            _build(rom, font_path)
        assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    glyph_map = engine.sf2_glyph_codes(overlay.strings_characters(_strings()))
    encoder = engine.Sf2ArabicEncoder(glyph_map)
    for twice in (
        _strings() + (_strings()[0],),
        _strings() + (dataclasses.replace(_strings()[0], key="witch.again"),),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            overlay.encode_strings(twice, encoder)
        assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID


def test_the_sites_and_anchors_lie_apart_and_the_room_in_order():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    hooks = {overlay.HOOKS.symbol_address(name) for name in overlay.HOOK_SYMBOLS}
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched)
        assert site.patched[:2] in (b"\x4e\xf9", b"\x4e\xb9")  # JMP or JSR, absolute
        assert int.from_bytes(site.patched[2:6], "big") in hooks
        assert set(site.patched[6:]) <= {0x4E, 0x71}  # NOPs
    assert overlay.ROOM_START == overlay.HOOK_ADDRESS
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.REDIRECTS
    assert overlay.REDIRECTS < overlay.ARABIC_FONT < overlay.ROOM_END
    assert overlay.ROOM_END <= 0x044000  # the free bytes end with the section


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    return {
        name: int(value, 0)
        for name, value in re.findall(r"^\s+\.set\s+(\w+),\s*(\w+)", source, re.MULTILINE)
    }


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    for name in ("ROOM_START", "ROOM_END", "REDIRECTS", "ARABIC_FONT"):
        assert equates[name] == getattr(overlay, name), name
    for name in ("RIGHT", "LINE_START", "LINE_END"):
        assert equates[name] == getattr(engine, name), name
    assert (equates["END"], equates["FONT_POINTER"]) == (END, sf2.FONT_POINTER)
    assert equates["ASCII_TO_SYMBOL"] == sf2.ASCII_TO_SYMBOL
    # Each hook goes back where its site ends.
    sites = {site.address: site for site in overlay.SITES}
    for site, back in (
        (0x006272, "FIND_ENGLISH"),
        (0x00634E, "HUFFMAN_BRANCH"),
        (0x006B70, "DRAW_ENGLISH"),
    ):
        assert site + len(sites[site].original) == equates[back], back
    # The engine's code the hooks go to or call: bytes the overlay pins.
    for name in (
        "FIND_ENGLISH",
        "FOUND_STRING",
        "HUFFMAN_BRANCH",
        "ASCII_BRANCH",
        "DRAW_ENGLISH",
        "GLYPH_PLACE",
        "NEW_LINE_CHECK",
        "SEND_LINE",
        "FONT_POINTER",
    ):
        assert equates[name] in overlay.ANCHORS, name
    # The work RAM the hooks read, as DisplayText uses it where an Arabic string goes
    # on: CLR.L $B77A, CLR.B $B6D8, MOVE.B #1,$B6D6, and MOVE.L a0,$B77E.
    found = overlay.ANCHORS[equates["FOUND_STRING"]].hex()
    assert found.startswith(
        f"42b8{equates['ASCII'] & 0xFFFF:04x}4238{equates['FIRST_DRAWN'] & 0xFFFF:04x}"
    )
    assert f"11fc0001{equates['INK'] & 0xFFFF:04x}" in found
    assert found.endswith(f"21c8{equates['CODE_POINTER'] & 0xFFFF:04x}")
    # ApplyAutomaticNewline: the pen, and the line it breaks after.
    assert (
        overlay.ANCHORS[equates["NEW_LINE_CHECK"]][:6].hex()
        == f"0c3800{engine.LAST_START:02x}{equates['PEN_X'] & 0xFFFF:04x}"
    )
    # The arrow: its X in the English, the site's value.
    assert sites[0x0064DA].original[2:4] == struct.pack(">H", equates["CURSOR_ENGLISH"])
    assert equates["CURSOR_ARABIC"] < equates["CURSOR_ENGLISH"]


@pytest.mark.skipif(shutil.which("m68k-linux-gnu-as") is None, reason="needs GNU m68k binutils")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "shining-force-2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["strings"] == 3 and report["laid_out"] is False
    assert report["keys"] == ["witch.greeting", "witch.confused", "witch.nice_name"]
    assert main(["shining-force-2", "encode-arabic", "بب {NAME;0}"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Initial and final beh, the space, the name and its number, the end.
    assert encoded["count"] == 6 and encoded["bytes"].split()[-4:] == ["01", "FC", "00", "FE"]
    assert "lines" not in encoded


def test_the_output_is_read_back_before_it_is_accepted(built):
    rom, result = built
    translated = _strings()
    glyph_map = engine.sf2_glyph_codes(overlay.strings_characters(translated))
    encoded = overlay.encode_strings(translated, engine.Sf2ArabicEncoder(glyph_map, result.font))
    writes = overlay.room_data(translated, encoded, result.font)
    overlay._verify_output(result.rom, rom, writes, translated, encoded)
    redirects = overlay.read_redirects(result.rom)
    assert list(redirects) == [string.index for string in translated]
    for string in translated:
        data = overlay.read_arabic_string(result.rom, redirects[string.index])
        assert data == encoded[string.key].data
    a_glyph = next(code for code in result.font.glyphs if code != SPACE_CODE)
    texts = max(writes)
    for address, what in (
        (overlay.HOOK_ADDRESS + 3, "hook code"),
        (overlay.SITES[3].address + 1, "site at $0064DA"),
        (overlay.REDIRECTS + 2, "list of translated strings"),
        (overlay.ARABIC_FONT + GLYPH_BYTES * a_glyph + 2, "font table"),
        (texts + 1, "Arabic text"),
        (BANKS + 0x100 + 3, f"at {BANKS + 0x100 + 3:#x}, outside the overlay's places"),
    ):
        tampered = bytearray(result.rom)
        tampered[address] ^= 0x01
        with pytest.raises(ClassicRetroError) as caught:
            overlay._verify_output(bytes(tampered), rom, writes, translated, encoded)
        assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED, what
        assert what in str(caught.value), what
    # A list that sends a string elsewhere than its Arabic is caught through the reader.
    elsewhere = bytearray(result.rom)
    struct.pack_into(">I", elsewhere, overlay.REDIRECTS + 2, texts + 2)
    with pytest.raises(ClassicRetroError) as caught:
        overlay._verify_output(bytes(elsewhere), rom, writes, translated, encoded)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_arabic_string(result.rom, overlay.ROOM_END - 4)  # 0xFF fill, no end
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_a_translation_keeps_the_originals_tags(font_path):
    """The witch's word on the name writes it, and waits. The build holds each translation
    against the ROM's tags, the check against the pinned ones."""
    rom = _rom()
    greeting, _, nice_name = _strings()
    for notation in (
        "…{N}اسم جميل.{W2}",  # the name dropped
        "{W2}…{N}اسم جميل.{NAME;0}",  # the tags swapped
        "{NAME;1}…{N}اسم جميل.{W2}",  # another argument
        "{NAME;0}…{N}اسم جميل.{W1}",  # another wait
    ):
        with pytest.raises(ClassicRetroError) as caught:
            _build(rom, font_path, translated=(dataclasses.replace(nice_name, notation=notation),))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION, notation
    kept = _build(rom, font_path, translated=(greeting, nice_name))
    assert kept.report["strings"]["witch.nice_name"]["source_skeleton"] == ["{NAME;0}", "{W2}"]
    assert kept.report["strings"]["witch.greeting"]["source_skeleton"] == ["{CLEAR}", "{W2}"]
    # New lines are the encoder's own: more or fewer of them change nothing.
    lines = dataclasses.replace(nice_name, notation="{NAME;0}{N}…{N}اسم{N}جميل.{W2}")
    assert _build(rom, font_path, translated=(lines,)).rom
    # A pinned skeleton is held against the ROM's, at the build and at the extraction.
    pinned = dataclasses.replace(nice_name, source_skeleton=("{NAME;0}", "{W2}"))
    assert _build(rom, font_path, translated=(pinned,)).rom
    wrong = dataclasses.replace(nice_name, source_skeleton=("{NAME;0}", "{W1}"))
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, translated=(wrong,))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(wrong,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    # Without the ROM, the pinned skeleton is what the translation is held against.
    glyph_map = engine.sf2_glyph_codes(overlay.strings_characters(_strings()))
    encoder = engine.Sf2ArabicEncoder(glyph_map)
    assert overlay.encode_strings((pinned,), encoder)["witch.nice_name"].data.endswith(b"\xfe")
    dropped = dataclasses.replace(pinned, notation="…{N}اسم جميل.{W2}")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_strings((dropped,), encoder)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    assert overlay.extract_skeletons(rom, translated=_strings(), verify_identity=False) == {
        "witch.greeting": ("{CLEAR}", "{W2}"),
        "witch.confused": ("{W2}",),
        "witch.nice_name": ("{NAME;0}", "{W2}"),
    }
