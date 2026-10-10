"""The Polished Crystal source overlay: engine patch, manifest, encoder, injection, text codes,
short jumps, the Pokédex's tilemaps, the shipped translation, and prepare on a tiny tree.

Everything here is synthetic (invented asm, blank images, invented words); the shipped data
is checked for its form and for holding no text of the game."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen2_arabic import huffman
from classic_retro.engines.pokemon_gen2_arabic.forms import CODES, glyph_code, shape
from classic_retro.localization.translations import (
    Translation,
    TranslationSet,
    builtin_translation_set,
)
from classic_retro.source import polished_crystal_arabic as overlay
from classic_retro.source.polished_crystal import dex, encode, inject, jumps, textcodes
from classic_retro.source.polished_crystal import manifest as manifest_module
from classic_retro.source.polished_crystal import patch as patch_module
from classic_retro.source.polished_crystal.units import Charmap

SYMBOLS = {
    " ": 0x7F,
    "!": 0x9F,
    "%": 0xDD,
    "&": 0xD8,
    "+": 0xDE,
    "-": 0xBC,
    ".": 0x9C,
    ",": 0x9D,
    "?": 0x9E,
    "/": 0xDC,
    **{str(digit): 0xE0 + digit for digit in range(10)},
    ":": 0xBD,
    "<MN>": 0xD3,
    "<PK>": 0xD2,
    "<SHARP>": 0xDF,
    "¥": 0xEA,
    "×": 0xDB,
    "“": 0xBA,
    "…": 0xEB,
    "№": 0xD5,
    "↑": 0xF2,
    "↓": 0xF3,
    "★": 0xEC,
    "♀": 0xBF,
    "♂": 0xBE,
    "♥": 0xDA,
    "♪": 0xD9,
}
SPECIALS = {
    0x52: "<DONE>",
    0x53: "@",
    0x54: "<PROMPT>",
    0x55: "<LNBRK>",
    0x56: "<NEXT>",
    0x57: "<LINE>",
    0x58: "<CONT>",
    0x59: "<PARA>",
    0x5A: "<TARGET>",
    0x5B: "<USER>",
    0x5C: "<ENEMY>",
}


def _sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --- a synthetic charmap and n-gram table with the anchors of the real ones ------------------


def _charmap() -> str:
    inverse = {code: char for char, code in SYMBOLS.items()}
    lines = [
        "; characters $4d-$5c correspond to leaf nodes $ec-$fb",
        "DEF FIRST_SHIFTED_LEAF_CHAR_ID EQU $4d",
        "\tnewcharmap no_ngrams",
    ]
    lines += [
        textcodes._charmap_line("ctxtmap", name, code, "0") for code, name in SPECIALS.items()
    ]
    for code in range(0x7F, 0xEC):
        lines.append(
            textcodes._charmap_line("ctxtmap", inverse.get(code, f"<C{code:02X}>"), code, "0")
        )
    lines += [
        textcodes._charmap_line("charmap", char, code)
        for char, code in SYMBOLS.items()
        if code >= 0xEC
    ]
    lines += ["", "DEF NGRAMS_START EQU $0a", "", "\tnewcharmap compressing, no_ngrams", ""]
    for name, code in (
        ("#", 0x4D),
        ("#mon", 0x4E),
        ("<PLAYER>", 0x4F),
        ("<RIVAL>", 0x50),
        ("<TRENDY>", 0x51),
    ):
        lines.append(textcodes._charmap_line("ctxtmap", name, code, "0"))
    lines += ["", "\tnewcharmap default, compressing", ""]
    lines += [
        textcodes._charmap_line("charmap", f"<N{code:02X}>", code) for code in range(0x0A, 0x4D)
    ]
    lines += ["", "DEF NGRAMS_END EQU $51", "", "\tsetcharmap default", ""]
    return "\n".join(lines)


def _ngrams() -> str:
    labels = [f".n{code:02x}" for code in range(0x0A, 0x4D)] + [".Poke", ".Pokemon"]
    lines = ["NgramStrings:", "\ttable_width 1"] + [f"\tdr {label}" for label in labels]
    lines += ["\tassert_table_length 69", ""]
    lines += [f'{label}: rawchar "<N{int(label[2:], 16):02X}>@"' for label in labels[:-2]]
    lines += ['.Poke:    rawchar "Pk@"', '.Pokemon: rawchar "Pkmn@"', ""]
    return "\n".join(lines)


# --- engine patch ----------------------------------------------------------------------------


def test_engine_hunks_check_the_lines_they_replace_and_resolve_references():
    text = 'Start:\n\tld a, 1\n\tdb "Foe" ; old\n\tret\n'
    removed = ['\tdb "Foe" ; old']
    hunk = patch_module.Hunk(
        3, 1, _sha(removed), ("\t; moved after the name", ['\tdb " ', [0, 0], '@"'])
    )
    patch = patch_module.FilePatch("home/x.asm", (hunk,))
    assert patch_module.apply_file(patch, text) == (
        'Start:\n\tld a, 1\n\t; moved after the name\n\tdb " Foe@"\n\tret\n'
    )
    with pytest.raises(ClassicRetroError) as error:
        patch_module.apply_file(patch, text.replace("Foe", "Bar"))
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    insertion = patch_module.Hunk(2, 0, _sha([]), ("\tnop",))
    assert (
        patch_module.apply_file(patch_module.FilePatch("x", (insertion,)), "a\nb\n")
        == "a\n\tnop\nb\n"
    )
    new = patch_module.FilePatch("home/new.asm", new_lines=("New:", "\tret"))
    assert patch_module.apply_file(new, None) == "New:\n\tret\n"
    with pytest.raises(ClassicRetroError):
        patch_module.apply_file(new, "exists")


def _git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def test_the_engine_patch_is_made_from_a_branch_without_its_text(tmp_path):
    repository = tmp_path / "engine"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "home").mkdir()
    (repository / "constants").mkdir()
    (repository / "home" / "text.asm").write_text('Foo:\n\tdb "Foe" ; x\n\tret\n', encoding="utf-8")
    (repository / "constants" / "charmap.asm").write_text("old\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "base")
    (repository / "home" / "text.asm").write_text(
        'Foo:\n\tld a, 2\n\tdb " Foe@" ; after the name\n\tret\nINCLUDE "home/rtl.asm"\n',
        encoding="utf-8",
    )
    (repository / "home" / "rtl.asm").write_text("RTL:\n\tret\n", encoding="utf-8")
    (repository / "constants" / "charmap.asm").write_text("generated\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "engine")
    patch = patch_module.make_engine_patch(repository, "HEAD~1", "HEAD")
    assert patch.paths() == ["home/rtl.asm", "home/text.asm"]  # the charmap is generated
    stored = patch_module.dumps(patch)
    assert "Foe" not in stored and "[0, 0]" in stored
    again = patch_module.from_dict(json.loads(stored))
    assert again.files == patch.files
    rebuilt = patch_module.apply_file(again.files[1], 'Foo:\n\tdb "Foe" ; x\n\tret\n')
    assert (
        rebuilt == 'Foo:\n\tld a, 2\n\tdb " Foe@" ; after the name\n\tret\nINCLUDE "home/rtl.asm"\n'
    )
    # English the replaced lines do not hold cannot be stored.
    (repository / "home" / "text.asm").write_text('Foo:\n\tdb "Hello"\n\tret\n', encoding="utf-8")
    _git(repository, "commit", "-q", "-am", "text")
    with pytest.raises(ClassicRetroError, match="Latin text"):
        patch_module.make_engine_patch(repository, "HEAD~1", "HEAD")


def test_an_engine_patch_checked_out_with_crlf_line_endings_keeps_its_digest():
    raw = patch_module.dumps(patch_module.builtin_engine_patch()).encode("utf-8")
    lf, crlf = (
        patch_module.load_engine_patch(raw),
        patch_module.load_engine_patch(raw.replace(b"\n", b"\r\n")),
    )
    assert b"\n" in raw and crlf.digest == lf.digest and crlf.files == lf.files


def test_the_shipped_engine_patch_holds_no_english_string():
    patch = patch_module.builtin_engine_patch()
    assert patch.base == overlay.PINNED_COMMIT and len(patch.digest) == 64
    pins = overlay.pinned_blobs()
    for item in patch.files:
        assert item.is_new or item.path in pins, item.path
        added = list(item.new_lines or ()) + [
            line for hunk in item.hunks for line in hunk.added if isinstance(line, str)
        ]
        for line in added:
            if patch_module._CODE_STRINGS.match(line):
                continue
            for literal in patch_module.string_literals(line):
                assert not patch_module._text_letters(literal), (item.path, line)


# --- manifest ------------------------------------------------------------------------------


def _entry(entry_id: str, path: str, start: int, end: int, lines: list[str], **fields) -> dict:
    return {
        "id": entry_id,
        "kind": fields.get("kind", "dialog"),
        "file": path,
        "start": start,
        "end": end,
        "sha256": hashlib.sha256("\n".join(lines[start - 1 : end]).encode()).hexdigest(),
        "skeleton": fields.get("skeleton", []),
        "limits": fields.get("limits", {"width": 18}),
        "category": fields.get("category", "maps"),
        "charmap": "default",
        "fmt": fields.get("fmt", {"indent": "\t", "first": "text", "term": "done"}),
    }


def test_the_manifest_compacts_and_expands_its_entries():
    lines = ["Sign:", '\ttext "One"', "\tdone", "Other:", '\ttext "Two"', "\tdone"]
    entries = [
        _entry("maps/Town:Sign", "maps/Town.asm", 1, 3, lines),
        _entry("maps/Town:Other", "maps/Town.asm", 4, 6, lines),
        _entry("Elsewhere:Name", "maps/Town.asm", 2, 2, lines, kind="string"),
    ]
    data = manifest_module.compact(
        entries, commit="c" * 40, engine_patch="e" * 64, ngram_entries={}, groups={}
    )
    assert data["files"]["maps/Town.asm"][0][0] == ":Sign"
    assert data["files"]["maps/Town.asm"][2][0] == "=Elsewhere:Name"
    assert len(data["tables"]["fmt"]) == 1
    expanded = manifest_module.expand(json.loads(manifest_module.dumps(data)))
    assert list(expanded.entries) == [entry["id"] for entry in entries]
    first = expanded.entries["maps/Town:Sign"]
    assert first["sha256"] == manifest_module.pin(lines, 1, 3) and len(first["sha256"]) == 16
    clash = dict(entries[1], sha256=entries[0]["sha256"][:16] + "f" * 48)
    with pytest.raises(ClassicRetroError, match="share the pin"):
        manifest_module.compact(
            [entries[0], clash], commit="c", engine_patch="e", ngram_entries={}, groups={}
        )


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_the_shipped_manifest_follows_the_engine_patch_and_holds_no_text():
    manifest = manifest_module.builtin_manifest()
    assert manifest.commit == overlay.PINNED_COMMIT
    assert manifest.engine_patch == patch_module.builtin_engine_patch().digest
    assert len(manifest) > 13000
    pins = overlay.pinned_blobs()
    assert all(re.fullmatch(r"[0-9a-f]{40}", blob) for blob in pins.values())
    starts: dict[str, list[tuple[int, int]]] = {}
    for entry in manifest.entries.values():
        assert entry["file"] in pins and entry["kind"] in manifest_module.KINDS
        assert 1 <= entry["start"] <= entry["end"] and len(entry["sha256"]) == 16
        starts.setdefault(entry["file"], []).append((entry["start"], entry["end"]))
    for ranges in starts.values():
        ranges.sort()
        assert all(a[1] < b[0] for a, b in zip(ranges, ranges[1:], strict=False))
    data = json.loads(
        (Path(manifest_module.__file__).parent / "data" / "manifest.json").read_text("utf-8")
    )
    for table in ("fmt", "limits", "skeleton"):
        for item in data["tables"][table]:
            for value in _strings(item):
                for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', value):
                    assert not re.search(
                        r"[A-Za-z]{2}", re.sub(r"<[^<>]*>|\{[^{}]*\}", "", literal)
                    )


# --- encoder ---------------------------------------------------------------------------------


def _dialog(**limits) -> dict:
    return {
        "id": "t:dialog",
        "kind": "dialog",
        "skeleton": limits.pop("skeleton", []),
        "limits": {"width": 18, **limits},
        "fmt": {"indent": "\t", "first": "text", "term": "done"},
    }


def test_the_encoder_wraps_shapes_and_keeps_placeholders():
    text = "مرحبا {PLAYER}! هذا نص طويل يلتف على سطرين\\pهل أنت {مستعد|مستعدة}؟"
    lines = encode.encode(_dialog(skeleton=["{PLAYER}"]), text)
    assert lines[0].startswith('\ttext "') and lines[-1] == "\tdone"
    assert any(line.startswith('\tpara "') for line in lines)
    assert "<PLAYER>" in lines[0]
    assert "<GM>" in "".join(lines) and "<GF>" in "".join(lines) and "<GE>" in "".join(lines)
    assert encode.check(_dialog(skeleton=["{PLAYER}"]), "مرحبا") == [
        "missing placeholders: {PLAYER}"
    ]
    assert any("not in the font" in error for error in encode.check(_dialog(), "Hello"))
    assert any(
        "only allowed in dialog" in error
        for error in encode.check(
            {
                **_dialog(),
                "kind": "box",
                "limits": {"width": 18, "lines": 2},
                "fmt": {"first": "text"},
            },
            "أ\\pب",
        )
    )
    assert encode.cells("بيت {PLAYER}") == 3 + 1 + 7


# --- injection -------------------------------------------------------------------------------


def _manifest(entries: list[dict], groups: dict | None = None) -> manifest_module.Manifest:
    data = manifest_module.compact(
        entries, commit="c", engine_patch="e", ngram_entries={}, groups=groups or {}
    )
    return manifest_module.expand(data)


def test_injection_replaces_pinned_lines_from_the_bottom_up():
    lines = ["A:", '\ttext "One"', "\tdone", "B:", '\ttext "Two"', '\tline "Three"', "\tdone", ""]
    source = "\n".join(lines)
    manifest = _manifest(
        [
            _entry("maps/Town:A", "maps/Town.asm", 2, 3, lines),
            _entry("maps/Town:B", "maps/Town.asm", 5, 7, lines),
        ]
    )
    encoded = inject.encode_entries(manifest, {"maps/Town:A": "ألف", "maps/Town:B": "باء"}, None)
    out = inject.inject({"maps/Town.asm": source}, manifest, encoded)["maps/Town.asm"].split("\n")
    assert out[0] == "A:" and out[3] == "B:" and out[-1] == ""
    assert out[1] == f'\ttext "{shape("ألف")}"' and out[4] == f'\ttext "{shape("باء")}"'
    with pytest.raises(ClassicRetroError) as error:
        inject.inject({"maps/Town.asm": source.replace("Two", "2")}, manifest, encoded)
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError) as error:
        inject.encode_entries(manifest, {"maps/Town:A": "ب" * 20}, None)
    assert error.value.code is ErrorCode.TEXT_OVERFLOW
    assert inject.plain_bytes(['\tli "ابت"', '\tdb "ب{d:X}" ; c']) == 4 + 1 + 5
    lines_with_group = ['\tdb "Ab@"']
    group = _entry(
        "t:s",
        "t.asm",
        1,
        1,
        lines_with_group,
        kind="string",
        limits={"width": 8, "dr_groups": ["t:T"], "en_bytes": 3},
    )
    grouped = _manifest([group], {"t:T": {"slack": 2, "members": ["t:s"]}})
    assert inject.group_growth(grouped, {"t:s": ['\tdb "ابتثج@"']}) == {"t:T": (3, 2)}


# --- text codes ------------------------------------------------------------------------------


def test_select_ngrams_keeps_the_comma_and_respects_the_budget():
    runs = [[("a", 0x80), ("b", 0x81), ("c", 0x82)]] * 20 + [[(",", 0x9D), (" ", 0x7F)]]
    chosen = textcodes.select_ngrams(runs, 4, budget=8)
    assert chosen[0][0] == textcodes.COMMA_SPACE
    assert chosen[1][0] == (0x80, 0x81, 0x82)
    assert sum(len(sequence) + 1 for sequence, _ in chosen) <= 8


def test_the_charmap_and_ngrams_are_written_over_the_originals():
    charmap = _charmap()
    leaves = {leaf: "0" for leaf in huffman.LEAVES}
    structure = Charmap(text=textcodes.charmap_asm(charmap, leaves, None))
    arabic = shape("بيت كبير")
    entries = [
        ({"kind": "dialog", "limits": {}}, [f'\ttext "{arabic}"', "\tdone"]),
        ({"kind": "string", "limits": {}, "charmap": "default"}, [f'\tdb "{arabic}@"'] * 5),
    ]
    codes = textcodes.train(structure, entries, ngram_budget=40)
    assert set(codes.huffman) == set(huffman.LEAVES)
    assert codes.ngrams[0x0A] == (textcodes.COMMA_SPACE, (", ",))
    written = textcodes.charmap_asm(charmap, codes.huffman, codes.ngrams)
    assert "DEF FIRST_SHIFTED_LEAF_CHAR_ID EQU $4a" in written
    assert '\tctxtmap "<GM>",     $4a, ' + codes.huffman[0x4A] in written
    assert f'\tcharmap "{shape("ب")}", ${CODES["beh.if"]:02x} ; beh.if' in written
    assert "<N0B>" not in written  # the synthetic n-grams are gone
    for line in written.split("\n"):
        match = textcodes._CTXTMAP.match(line)
        if match:
            assert match.group(6) == codes.huffman[int(match.group(4), 16)]
    ngrams = textcodes.ngrams_asm(_ngrams(), codes.ngrams)
    assert len(ngrams.split("\n")) == len(_ngrams().split("\n"))
    assert '.Pokemon: rawchar "Pkmn@"' in ngrams and "\tdr .ngram0a" in ngrams
    assert '.n4a:   rawchar "@" ; <GM>/<GF>/<GE> are not n-grams' in ngrams
    assert textcodes.ngram_string_bytes(_ngrams(), structure) > 0


# --- short jumps -----------------------------------------------------------------------------


def test_short_jumps_over_growing_text_become_long():
    source = "\n".join(
        [
            "Script:",
            "\tsjumpfwd .done",
            "\tifequalfwd 3, .done",
            "\tjr nz, Far",
            ".text",
            '\ttext "x"',
            "\tdone",
            ".done",
            "\tend",
            "Far:",
            "\tret",
        ]
    )
    found = jumps.short_jumps(source)
    assert [(jump.line, jump.kind, jump.target) for jump in found] == [
        (2, "sjumpfwd", 8),
        (3, "ifequalfwd", 8),
        (4, "jr", 10),
    ]
    assert jumps.jumps_to_lengthen(source, [(6, 7, -10)]) == []
    assert jumps.jumps_to_lengthen(source, [(6, 7, 1)]) == [2, 3, 4]
    longer = jumps.lengthen(source, [2, 3, 4]).split("\n")
    assert longer[1:4] == ["\tsjump .done", "\tifequal 3, .done", "\tjp nz, Far"]
    # A jump to another file's label is always made long; a macro's body is not code yet.
    other = "MACRO skip\n\tjr nz, \\1\nENDM\nScript:\n\tsjumpfwd OtherFile_Script\n"
    assert [(jump.line, jump.target) for jump in jumps.short_jumps(other)] == [(5, None)]
    assert jumps.jumps_to_lengthen(other, []) == [5]


# --- the Pokédex's tilemaps --------------------------------------------------------------


def _tilemaps(artwork: int | None = None) -> dict[str, tuple[bytes, bytes]]:
    tiles = bytearray([dex.SPACE] * (dex.WIDTH * 19))
    attributes = bytearray(dex.WIDTH * 19)
    if artwork is not None:
        attributes[artwork] = dex.BANK_BIT
    return {name: (bytes(tiles), bytes(attributes)) for name in dex.MAPS}


def test_pokedex_labels_go_into_font_cells_in_visual_order():
    texts = {text_id: "باب" for text_id in dex.label_entries()}
    texts["gfx/pokedex/description:height_unit"] = "م"
    texts["gfx/pokedex/description:weight_unit"] = "كغ"
    out = dex.apply(_tilemaps(), texts)
    seen = out["main"][6 * dex.WIDTH : 7 * dex.WIDTH]
    word = [glyph_code(char) for char in reversed(shape("باب"))]
    assert list(seen[17:20]) == word  # right-aligned in x 15..19
    owned = out["main"][6 * dex.WIDTH + 11 : 6 * dex.WIDTH + 14]
    assert list(owned) == word  # right-aligned in x 9..13
    with pytest.raises(ClassicRetroError, match="no text cell"):
        dex.apply(_tilemaps(artwork=6 * dex.WIDTH + 9), texts)
    with pytest.raises(ClassicRetroError) as error:
        dex.check_label("gfx/pokedex/description:height_unit", "باب")
    assert error.value.code is ErrorCode.TEXT_OVERFLOW
    assert len(dex.label_entries()) == 35


# --- the shipped translation ---------------------------------------------------------------


def test_the_shipped_translation_passes_and_reports_its_coverage(tmp_path):
    report = overlay.check_polished_crystal_translations(
        tmp_path / overlay.GLYPH_ATLAS, tmp_path / overlay.SPECIMEN
    )
    coverage = report["coverage"]
    shipped = builtin_translation_set(overlay.TARGET)
    extras = overlay.extra_entries()
    assert coverage["entries"] == len(manifest_module.builtin_manifest())
    assert coverage["translated"] == len(shipped.entries) - len(extras)
    assert coverage["translated"] + coverage["untranslated"] == coverage["entries"]
    assert (
        sum(item["translated"] for item in coverage["by_category"].values())
        == (coverage["translated"])
    )
    for name in (overlay.GLYPH_ATLAS, overlay.SPECIMEN):
        with Image.open(tmp_path / name) as image:
            assert image.width > 100
    manifest = manifest_module.builtin_manifest()
    for entry in shipped.entries:
        assert entry.id in manifest.entries or entry.id in extras, entry.id
        assert entry.context and not re.search(r'"[^"]*[A-Za-z]{2}[^"]*"', entry.context), entry.id
    assert shipped.notation and "{masculine|" in shipped.notation
    texts = " ".join(entry.text for entry in shipped.entries)
    assert all(term.text in texts for term in shipped.glossary)


def test_a_translation_must_know_its_ids_and_have_the_labels():
    shipped = builtin_translation_set(overlay.TARGET)
    unknown = replace(shipped, entries=(*shipped.entries, Translation("maps/Nowhere:Text", "باب")))
    with pytest.raises(ClassicRetroError, match="unknown maps/Nowhere:Text"):
        overlay.translation_texts(unknown)
    without = replace(
        shipped, entries=tuple(e for e in shipped.entries if e.id != overlay.KEY_PHRASE_ID)
    )
    with pytest.raises(ClassicRetroError, match="missing"):
        overlay.translation_texts(without)
    # An empty text is an entry left in English.
    first = shipped.entries[0]
    emptied = replace(shipped, entries=(replace(first, text=""), *shipped.entries[1:]))
    assert first.id not in overlay.translation_texts(emptied)


# --- prepare on a tiny tree ---------------------------------------------------------------


def _blank_png() -> bytes:
    from classic_retro.engines.pokemon_gen2_arabic.fonts import png_bytes

    return png_bytes(Image.new("L", (128, 64), 255))


def _tree(root: Path) -> dict[str, bytes]:
    town = [
        "TestTown_MapScripts:",
        "\tsjumpfwd .done",
        "TestTownSignText:",
        '\ttext "An invented"',
        '\tline "sign"',
        "\tdone",
        ".done",
        "\tend",
        "",
    ]
    files = {
        "constants/charmap.asm": _charmap().encode(),
        "data/text/ngrams.asm": _ngrams().encode(),
        "data/text/input_chars.asm": b"; the keyboards\n",
        "home/text.asm": b"PlaceString:\n\tld a, 1\n\tret\n",
        "maps/TestTown.asm": "\n".join(town).encode(),
        "gfx/font/normal.png": _blank_png(),
        "gfx/font/vwf.png": _blank_png(),
    }
    for name, (tiles, attributes) in _tilemaps().items():
        files[f"gfx/pokedex/{name}.tilemap"] = tiles
        files[f"gfx/pokedex/{name}.attrmap"] = attributes
    for relative, data in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(data)
    return files


def _fake_overlay(monkeypatch, files: dict[str, bytes]) -> TranslationSet:
    lines = files["maps/TestTown.asm"].decode().split("\n")
    entries = [_entry("maps/TestTown:TestTownSignText", "maps/TestTown.asm", 4, 6, lines)]
    fake_manifest = _manifest(entries)
    engine = patch_module.EnginePatch(
        "c",
        "e",
        (
            patch_module.FilePatch(
                "home/text.asm",
                (patch_module.Hunk(2, 1, _sha(["\tld a, 1"]), ("\tld a, 2 ; right to left",)),),
            ),
            patch_module.FilePatch("home/rtl.asm", new_lines=("RTL:", "\tret")),
        ),
        "d" * 64,
    )
    pins = {relative: overlay.git_blob_sha1(data) for relative, data in files.items()}
    monkeypatch.setattr(overlay, "builtin_manifest", lambda: fake_manifest)
    monkeypatch.setattr(overlay, "builtin_engine_patch", lambda: engine)
    monkeypatch.setattr(overlay, "pinned_blobs", lambda: pins)
    texts = [Translation(text_id, "م", context="label") for text_id in dex.label_entries()]
    texts.append(Translation(overlay.KEY_PHRASE_ID, "محظوظ", context="phrase"))
    texts.append(Translation("maps/TestTown:TestTownSignText", "لافتة مخترعة", context="a sign"))
    return TranslationSet(overlay.TARGET, "notation", tuple(texts))


def test_prepare_patches_a_pinned_tree_once_and_refuses_any_other(monkeypatch, tmp_path):
    root = tmp_path / "pc"
    files = _tree(root)
    translations = _fake_overlay(monkeypatch, files)
    report = overlay.prepare_polished_crystal_arabic_source(root, None, translations)
    assert report["already_prepared"] is False and report["translated_entries"] == 1
    town = (root / "maps/TestTown.asm").read_text(encoding="utf-8").split("\n")
    assert town[3] == f'\ttext "{shape("لافتة مخترعة")}"' and town[4] == "\tdone"
    assert town[1] in ("\tsjumpfwd .done", "\tsjump .done")
    assert "ld a, 2 ; right to left" in (root / "home/text.asm").read_text(encoding="utf-8")
    assert (root / "home/rtl.asm").read_text(encoding="utf-8") == "RTL:\n\tret\n"
    charmap = (root / "constants/charmap.asm").read_text(encoding="utf-8")
    assert "<GM>" in charmap and "; Arabic presentation forms" in charmap
    assert (root / "data/text/lucky_key_phrase.asm").read_text(encoding="utf-8").count("db $") == 1
    assert (root / "data/text/arabic_shaping.asm").exists()
    assert (root / "gfx/font/bold.png").exists() and (root / "gfx/pokedex/main.tilemap").exists()
    state = json.loads((root / overlay.STATE_FILE).read_text(encoding="utf-8"))
    assert (
        state["upstream_commit"] == overlay.PINNED_COMMIT
        and "maps/TestTown.asm" in state["written"]
    )
    # The same translation again: nothing to do.
    again = overlay.prepare_polished_crystal_arabic_source(root, None, translations)
    assert again["already_prepared"] is True
    # Another translation, or a changed tree, is refused.
    other = replace(translations, entries=translations.entries[:-1])
    with pytest.raises(ClassicRetroError, match="another translation"):
        overlay.prepare_polished_crystal_arabic_source(root, None, other)
    (root / "maps/TestTown.asm").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ClassicRetroError) as error:
        overlay.prepare_polished_crystal_arabic_source(root, None, translations)
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    # A tree that differs from the pins is refused before anything is written.
    fresh = tmp_path / "fresh"
    _tree(fresh)
    (fresh / "home/text.asm").write_text("PlaceString:\n\tret\n", encoding="utf-8")
    with pytest.raises(ClassicRetroError, match="does not match"):
        overlay.prepare_polished_crystal_arabic_source(fresh, None, translations)
    assert not (fresh / overlay.STATE_FILE).exists()
    assert not (fresh / "data/text/arabic_shaping.asm").exists()


def test_make_bps_refuses_another_rom_and_verifies_the_patch(monkeypatch, tmp_path):
    original = bytes(range(256)) * 64
    arabic = bytearray(original)
    arabic[100:110] = b"\x80" * 10
    (tmp_path / "base.gbc").write_bytes(original)
    (tmp_path / "ar.gbc").write_bytes(bytes(arabic))
    with pytest.raises(ClassicRetroError) as error:
        overlay.make_bps(tmp_path / "base.gbc", tmp_path / "ar.gbc", tmp_path / "x.bps")
    assert error.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    monkeypatch.setattr(overlay, "ROM_SHA256", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(overlay, "ROM_SIZE", len(original))
    report = overlay.make_bps(tmp_path / "base.gbc", tmp_path / "ar.gbc", tmp_path / "x.bps")
    assert report["patch_bytes"] == (tmp_path / "x.bps").stat().st_size
    (tmp_path / "short.gbc").write_bytes(bytes(arabic[:-1]))
    with pytest.raises(ClassicRetroError, match="overflowed"):
        overlay.make_bps(tmp_path / "base.gbc", tmp_path / "short.gbc", tmp_path / "y.bps")


def test_the_command_group_holds_the_engines_tools(capsys):
    assert main(["polished-crystal", "encode-arabic", "مرحبا {PLAYER}"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    assert encoded["errors"] == [] and encoded["lines"][0].startswith('\ttext "')
    assert encoded["glyph_codes"][0] == f"${glyph_code(shape('مرحبا')[0]):02x}"
    assert main(["polished-crystal", "encode-arabic", "Hello"]) == 0
    assert json.loads(capsys.readouterr().out)["errors"]
