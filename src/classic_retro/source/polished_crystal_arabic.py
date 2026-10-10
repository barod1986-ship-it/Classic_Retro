"""Arabic source overlay for Pokémon Polished Crystal 3.2.3 (Rangi42/polishedcrystal, v3.2.3).

The pinned disassembly builds, with rgbds 1.0.0, the very ROM the target
supports (``polishedcrystal-3.2.3.gbc``). ``prepare`` turns a pristine checkout
of it into the Arabic game's source, which ``make`` then builds:

1. every file the overlay reads or writes is checked against its pinned git blob
   (``data/pins.json``); any other tree is refused before anything is written;
2. the engine patch (``data/engine_patch.json``) is applied: the right-to-left
   text engine, the naming screen's keyboards and runtime shaper, the menus and
   screens turned around. Each hunk checks the lines it replaces by their hash;
3. every translated entry of the manifest (``data/manifest.json``) is encoded
   (``polished_crystal.encode``) and put in place of the lines it owns, checked
   by their pin; a translation that leaves an entry out is refused, since the
   Arabic glyphs take the Latin letters' codes;
4. the generated files are written from the pinned originals: the Arabic glyphs
   in the 8x8 typefaces and the VWF font, the Arabic lettering of the words drawn
   in tile graphics (``gfx_labels``), the Pokédex's tilemap labels, the
   charmap with the presentation forms and the gender codes, the Huffman codes
   and n-grams trained on the translated tree, the keyboards, the shaping
   tables and the key phrase;
5. a state file records what was written, so a second run is a no-op on the
   same tree and is refused on a changed one.

Everything is computed before the first file is written. The font argument of
the toolkit's commands is not used: the glyphs are hand-drawn 8x8 pixel art
(``engines.pokemon_gen2_arabic``), since the reference font is illegible at 8
pixels. ``check_polished_crystal_translations`` checks a translation without a
checkout, and ``make_bps`` makes the patch from the user's ROM and the built one.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen2_arabic import fonts, naming
from classic_retro.engines.pokemon_gen2_arabic.forms import (
    CODES,
    JOINING,
    PRESENTATION_GLYPH,
    glyph_code,
    shape,
)
from classic_retro.engines.pokemon_gen2_arabic.glyphs import GLYPHS, PUNCTUATION_GLYPHS
from classic_retro.font.previews import glyph_atlas
from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.rebuild.bps import apply_bps, create_bps
from classic_retro.source.polished_crystal import (
    asmscan,
    dex,
    encode,
    gfx_labels,
    inject,
    jumps,
    textcodes,
)
from classic_retro.source.polished_crystal import manifest as manifest_module
from classic_retro.source.polished_crystal import patch as patch_module
from classic_retro.source.polished_crystal.manifest import Manifest, builtin_manifest
from classic_retro.source.polished_crystal.patch import EnginePatch, builtin_engine_patch
from classic_retro.source.polished_crystal.sizes import SizeModel
from classic_retro.source.polished_crystal.units import Charmap

TARGET = "polished-crystal"
REPOSITORY = "https://github.com/Rangi42/polishedcrystal"
PINNED_TAG = "v3.2.3"
PINNED_COMMIT = "3fa43192379df5c3e7b09a08e4d5d79af4f02f42"
RGBDS_VERSION = "1.0.0"
ROM_NAME = "polishedcrystal-3.2.3.gbc"
ROM_SIZE = 2_097_152
ROM_SHA1 = "6930b48af5844d373e3c9130f26d6dd1084cf4ed"
ROM_SHA256 = "f06dbebe3fd20db54e7804605f7a55ad05b8ca203c62209705290d8880864803"

OVERLAY_VERSION = 1
STATE_FILE = ".classic-retro-arabic.json"
# The previews check_translations writes.
GLYPH_ATLAS = "polished_crystal_glyphs.png"
SPECIMEN = "polished_crystal_specimen.png"
# The trendy phrase the game checks for; the naming screen stores it shaped.
KEY_PHRASE_ID = "engine/events/specials:CheckIfTrendyPhraseIsLucky.KeyPhrase"
KEY_PHRASE_FILE = "data/text/lucky_key_phrase.asm"

CHARMAP = "constants/charmap.asm"
NGRAMS = "data/text/ngrams.asm"
SHAPING_TABLES = "data/text/arabic_shaping.asm"
KEYBOARDS = "data/text/input_chars.asm"
FONT_DIR = "gfx/font"
DEX_DIR = "gfx/pokedex"


# --- pinned data -------------------------------------------------------------------------


def git_blob_sha1(data: bytes) -> str:
    """The id git gives a file's bytes (``git hash-object``)."""
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()


@cache
def pinned_blobs() -> dict[str, str]:
    """Every pristine file the overlay reads or writes -> its git blob id at the pinned commit."""
    resource = files("classic_retro.source.polished_crystal").joinpath("data", "pins.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    if data.get("commit") != PINNED_COMMIT:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "pins.json is for another commit")
    return dict(data["blobs"])


def generated_files() -> list[str]:
    """The files prepare writes from the originals and the translation."""
    out = [CHARMAP, NGRAMS, SHAPING_TABLES, KEYBOARDS, KEY_PHRASE_FILE]
    out += [f"{FONT_DIR}/{name}.png" for name in fonts.TYPEFACES]
    out.append(f"{FONT_DIR}/vwf.png")
    out += [f"{DEX_DIR}/{name}.tilemap" for name in dex.MAPS]
    out += gfx_labels.paths()
    return out


def read_pristine(source: Path, paths: Iterable[str] | None = None) -> dict[str, bytes]:
    """The pinned files of a checkout, refused unless every one matches its pin."""
    if not source.is_dir():
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"polishedcrystal checkout not found: {source}"
        )
    blobs = pinned_blobs()
    wanted = list(blobs) if paths is None else list(paths)
    data: dict[str, bytes] = {}
    mismatches = []
    for relative in wanted:
        path = source / relative
        if not path.is_file():
            mismatches.append(f"{relative}: missing")
            continue
        raw = path.read_bytes()
        if git_blob_sha1(raw) != blobs[relative]:
            mismatches.append(f"{relative}: {git_blob_sha1(raw)}")
            continue
        data[relative] = raw
    if mismatches:
        shown = ", ".join(mismatches[:10]) + (
            f" (and {len(mismatches) - 10} more)" if len(mismatches) > 10 else ""
        )
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"polishedcrystal source does not match {PINNED_TAG} ({PINNED_COMMIT}): {shown}",
        )
    return data


def _texts(pristine: Mapping[str, bytes]) -> dict[str, str]:
    return {path: raw.decode("utf-8") for path, raw in pristine.items() if path.endswith(".asm")}


def engine_sources(pristine: Mapping[str, bytes], engine: EnginePatch) -> dict[str, str]:
    """The pinned assembly sources with the engine patch applied (the manifest's tree)."""
    texts = _texts(pristine)
    texts.update(patch_module.apply(engine, texts))
    return texts


# --- the translation -----------------------------------------------------------------


def extra_entries() -> dict[str, str]:
    """Entries the translation must have beside the manifest's, by id: what each is."""
    out = {KEY_PHRASE_ID: "The trendy phrase the game checks for (letters, at most 7 glyphs)"}
    for text_id, placement in dex.label_entries().items():
        out[text_id] = f"Pokédex tilemap label ({placement.cells} cells)"
    return out


def translation_texts(
    translations: TranslationSet | None = None,
    manifest: Manifest | None = None,
    *,
    complete: bool = False,
) -> dict[str, str]:
    """The translation's text by id; an empty text is an entry not translated yet,
    except where the entry allows an empty text (it is then written empty).

    Unknown ids are refused, and so is a translation without the entries the
    engine needs (``extra_entries``). ``complete`` (prepare) also refuses a
    translation that leaves any entry out: the Arabic glyphs take the Latin
    letters' codes, so a text left in English would show as wrong letters.
    """
    manifest = manifest or builtin_manifest()
    translations = translations or builtin_translation_set(TARGET)
    extras = extra_entries()
    texts = {
        entry.id: entry.text
        for entry in translations.entries
        if entry.text.strip()
        or manifest.entries.get(entry.id, {}).get("limits", {}).get("allow_empty")
    }
    unknown = [
        entry.id
        for entry in translations.entries
        if entry.id not in manifest.entries and entry.id not in extras
    ]
    missing = [entry_id for entry_id in extras if entry_id not in texts]
    untranslated = [entry_id for entry_id in manifest.entries if entry_id not in texts]
    if unknown or missing or (complete and untranslated):
        problems = []
        if unknown:
            problems.append("unknown " + ", ".join(unknown[:20]))
        if missing:
            problems.append("missing " + ", ".join(missing))
        if complete and untranslated:
            more = f" (and {len(untranslated) - 10} more)" if len(untranslated) > 10 else ""
            problems.append(
                f"{len(untranslated)} entries untranslated, which would show as wrong letters: "
                + ", ".join(untranslated[:10])
                + more
            )
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"{TARGET} translations: " + "; ".join(problems),
        )
    return texts


def _check_key_phrase(text: str) -> list[int]:
    letters = text.strip()
    if any(char not in JOINING for char in letters):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, f"{KEY_PHRASE_ID}: the key phrase is letters only"
        )
    try:
        return naming.key_phrase_codes(letters, {})
    except ValueError as exc:
        raise ClassicRetroError(ErrorCode.TEXT_OVERFLOW, f"{KEY_PHRASE_ID}: {exc}") from exc


def check_entries(
    texts: Mapping[str, str], manifest: Manifest
) -> tuple[dict[str, list[str]], encode.Ngrams | None]:
    """Every translated entry encoded (or refused with its reasons), and the n-gram leaves."""
    ngrams = inject.ngram_leaves(manifest, texts)
    encoded = inject.encode_entries(manifest, texts, ngrams)
    for text_id in dex.label_entries():
        dex.check_label(text_id, texts[text_id])
    _check_key_phrase(texts[KEY_PHRASE_ID])
    overflows = [
        f"{group}: {growth} bytes, room for {slack}"
        for group, (growth, slack) in sorted(inject.group_growth(manifest, encoded).items())
        if growth > slack
    ]
    if overflows:
        raise ClassicRetroError(
            ErrorCode.TEXT_OVERFLOW,
            "strings of a one-byte offset table outgrow it: " + "; ".join(overflows),
        )
    return encoded, ngrams


def coverage(texts: Mapping[str, str], manifest: Manifest) -> dict[str, object]:
    """How much of the game the translation covers, overall and by category."""
    total: Counter[str] = Counter()
    done: Counter[str] = Counter()
    for entry_id, entry in manifest.entries.items():
        total[entry["category"]] += 1
        if entry_id in texts:
            done[entry["category"]] += 1
    translated = sum(done.values())
    return {
        "entries": len(manifest),
        "translated": translated,
        "untranslated": len(manifest) - translated,
        "percent": round(100 * translated / len(manifest), 1),
        "by_category": {
            category: {"entries": total[category], "translated": done[category]}
            for category in sorted(total)
        },
    }


# --- check without a checkout ---------------------------------------------------------


def check_polished_crystal_translations(
    atlas_path: Path | None = None,
    specimen_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Encode every translated entry with its limits; with paths, write the previews.

    No checkout is needed: the manifest carries every entry's structure and
    limits. What depends on the user's tree (the pins, the Huffman codes trained
    on it, text a ``jr`` jumps across) is checked by ``prepare``.
    """
    manifest = builtin_manifest()
    texts = translation_texts(translations, manifest)
    encoded, ngrams = check_entries(texts, manifest)
    report: dict[str, object] = {
        "upstream_commit": PINNED_COMMIT,
        "coverage": coverage(texts, manifest),
        "extra_entries": len(extra_entries()),
        "encoded_lines": sum(len(lines) for lines in encoded.values()),
        "ngram_leaves": sorted(ngrams.table) if ngrams is not None else [],
        "arabic_glyphs": len(CODES),
        "lines_measured": True,
        "font": "unused: the glyphs are hand-drawn 8x8 pixel art",
    }
    if atlas_path is not None:
        write_glyph_atlas(atlas_path)
    if specimen_path is not None:
        write_specimen(specimen_path, texts, manifest)
    return report


def _glyph_cells() -> list[tuple[str, ...]]:
    cells = [GLYPHS[glyph] for glyph in sorted(CODES, key=CODES.__getitem__)]
    return [*cells, *PUNCTUATION_GLYPHS.values()]


def write_glyph_atlas(path: Path) -> None:
    """Every Arabic glyph and redrawn punctuation in code order, 16 a row, 4x."""
    cells = _glyph_cells()

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        return (16, 16, 16) if cells[index][y][x] == "#" else (232, 232, 216)

    atlas = glyph_atlas(len(cells), 8, 8, colour, background=(120, 120, 120))
    atlas.resize((atlas.width * 4, atlas.height * 4), Image.Resampling.NEAREST).save(path)


SPECIMEN_LINES = 16


def _specimen_rows(texts: Mapping[str, str], manifest: Manifest) -> list[list[tuple[str, int]]]:
    """The first rows of the first translated speech-box texts, as the encoder wraps them."""
    rows: list[list[tuple[str, int]]] = []
    for entry_id, entry in manifest.entries.items():
        if entry["kind"] != "dialog" or entry_id not in texts:
            continue
        _, paragraphs, errors = encode._dialog_rows(entry, texts[entry_id])
        if errors or not paragraphs or not paragraphs[0]:
            continue
        cells: list[tuple[str, int]] = []
        for piece in paragraphs[0][0]:
            if piece.t == "t":
                cells += [(char, 1) for char in piece.s]
            elif piece.t == "alt":
                cells += [(char, 1) for char in piece.m]
            elif piece.t == "ph":
                cells.append(("", piece.w))
        rows.append(cells)
        if len(rows) == SPECIMEN_LINES:
            break
    return rows


def write_specimen(path: Path, texts: Mapping[str, str], manifest: Manifest) -> None:
    """Speech-box rows drawn right to left with the 8x8 glyphs, as the game draws them.

    Characters the game draws from its own font (digits, Latin punctuation) are
    hollow cells, and a placeholder is a grey run of its width.
    """
    rows = _specimen_rows(texts, manifest)
    width, scale = 18 * 8, 3
    image = Image.new("RGB", (width + 16, 12 * max(len(rows), 1) + 4), (248, 248, 232))
    punctuation = {",": 0x9D, "?": 0x9E, "“": 0xBA}
    for number, cells in enumerate(rows):
        pen = 8 + width
        top = 4 + 12 * number
        for char, cells_wide in cells:
            pen -= 8 * cells_wide
            if not char:
                for x in range(pen + 1, pen + 8 * cells_wide - 1):
                    for y in range(top + 2, top + 6):
                        image.putpixel((x, y), (168, 168, 168))
                continue
            code = glyph_code(char)
            rows_ = None
            if code is not None:
                glyph = next(name for name, value in CODES.items() if value == code)
                rows_ = GLYPHS[glyph]
            elif char in punctuation:
                rows_ = PUNCTUATION_GLYPHS[punctuation[char]]
            if char == " ":
                continue
            if rows_ is None:
                for x in range(pen + 1, pen + 7):
                    image.putpixel((x, top + 1), (96, 96, 96))
                    image.putpixel((x, top + 6), (96, 96, 96))
                continue
            for y, row in enumerate(rows_):
                for x, cell in enumerate(row):
                    if cell == "#":
                        image.putpixel((pen + x, top + y), (24, 24, 24))
    image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST).save(path)


# --- prepare --------------------------------------------------------------------------


def _png(image: Image.Image) -> bytes:
    return fonts.png_bytes(image)


def build_outputs(
    pristine: Mapping[str, bytes],
    texts: Mapping[str, str],
    manifest: Manifest,
    engine: EnginePatch,
) -> tuple[dict[str, bytes], dict[str, object]]:
    """Every file prepare writes (path -> bytes) and what the build found."""
    sources = engine_sources(pristine, engine)
    encoded, _ = check_entries(texts, manifest)

    # Train the codes on what the tree will hold.
    placeholder = {leaf: "0" for leaf in textcodes.LEAVES}
    pristine_charmap = sources[CHARMAP]
    structure = Charmap(text=textcodes.charmap_asm(pristine_charmap, placeholder, None))
    budget = textcodes.ngram_string_bytes(sources[NGRAMS], structure)
    codes = textcodes.train(structure, inject.entry_lines(sources, manifest, encoded), budget)
    charmap_text = textcodes.charmap_asm(pristine_charmap, codes.huffman, codes.ngrams)

    # A short jump over text that grows becomes a long one (jumps.py).
    consts = asmscan.Consts()
    before = SizeModel(charmap_text=pristine_charmap, consts=consts)
    after = SizeModel(charmap_text=charmap_text, consts=consts)
    growth: dict[str, list[tuple[int, int, int]]] = {}
    split = {path: text.split("\n") for path, text in sources.items()}
    for entry, lines in inject.entry_lines(sources, manifest, encoded):
        own = split[entry["file"]][entry["start"] - 1 : entry["end"]]
        delta = after.estimate(list(lines)) - before.estimate(own)
        growth.setdefault(entry["file"], []).append((entry["start"], entry["end"], delta))
    lengthened = jumps.lengthen_all(sources, growth)
    far_jumps = {path: count for path, (_, count) in lengthened.items()}
    sources = {**sources, **{path: text for path, (text, _) in lengthened.items()}}
    injected = inject.inject(sources, manifest, encoded)
    tree = {**sources, **injected}
    ngrams_text = textcodes.ngrams_asm(tree[NGRAMS], codes.ngrams)

    keyboard_charmap = naming.no_ngrams_charmap(charmap_text)
    naming.self_test(keyboard_charmap)
    outputs: dict[str, bytes] = {
        path: text.encode("utf-8") for path, text in tree.items() if path not in (CHARMAP, NGRAMS)
    }
    # Only the files the engine patch, the jumps or the translation changed are written.
    outputs = {
        path: data
        for path, data in outputs.items()
        if path in injected or path in engine.paths() or path in far_jumps
    }
    outputs[CHARMAP] = charmap_text.encode("utf-8")
    outputs[NGRAMS] = ngrams_text.encode("utf-8")
    outputs[SHAPING_TABLES] = naming.shaping_asm().encode("utf-8")
    outputs[KEYBOARDS] = naming.keyboards_asm(keyboard_charmap).encode("utf-8")
    outputs[KEY_PHRASE_FILE] = naming.key_phrase_asm(
        texts[KEY_PHRASE_ID].strip(), keyboard_charmap
    ).encode("utf-8")
    with _open(pristine[f"{FONT_DIR}/normal.png"]) as normal:
        for name, image in fonts.typefaces(normal).items():
            outputs[f"{FONT_DIR}/{name}.png"] = _png(image)
    with _open(pristine[f"{FONT_DIR}/vwf.png"]) as vwf:
        outputs[f"{FONT_DIR}/vwf.png"] = _png(fonts.draw_vwf_font(vwf))
    tilemaps = dex.apply(
        {
            name: (pristine[f"{DEX_DIR}/{name}.tilemap"], pristine[f"{DEX_DIR}/{name}.attrmap"])
            for name in dex.MAPS
        },
        texts,
    )
    for name, data in tilemaps.items():
        outputs[f"{DEX_DIR}/{name}.tilemap"] = data
    # The English words drawn in tile graphics, lettered in Arabic over the originals.
    outputs.update(gfx_labels.outputs(lambda path: pristine[path]))
    found = {
        "short_jumps_made_long": sum(far_jumps.values()),
        "translated_entries": len(encoded),
        "files_with_translations": len(injected),
        "text_codes": codes.report(),
    }
    return outputs, found


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _read_state(source: Path) -> dict[str, Any] | None:
    path = source / STATE_FILE
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Unreadable {STATE_FILE}; prepare a fresh checkout of {PINNED_COMMIT}",
        ) from exc
    if not isinstance(state, dict):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Untracked Arabic overlay; prepare a fresh checkout of {PINNED_COMMIT}",
        )
    return state


def _validate_prepared(source: Path, state: Mapping[str, Any]) -> None:
    """A tree an earlier prepare wrote, untouched since: or refused."""
    if (
        state.get("overlay_version") != OVERLAY_VERSION
        or state.get("upstream_commit") != PINNED_COMMIT
        or not isinstance(state.get("written"), dict)
        or not isinstance(state.get("source_blobs"), dict)
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Outdated Arabic overlay; prepare a fresh checkout of {PINNED_COMMIT}",
        )
    # What prepare wrote, and every pinned file it read but left as it was.
    expected = {**state["source_blobs"], **state["written"]}
    changed = [
        relative
        for relative, blob in expected.items()
        if not (source / relative).is_file()
        or git_blob_sha1((source / relative).read_bytes()) != blob
    ]
    if changed:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "Modified or partially patched polishedcrystal source: " + ", ".join(changed[:10]),
        )


def _translations_digest(texts: Mapping[str, str]) -> str:
    canonical = json.dumps(texts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prepare_polished_crystal_arabic_source(
    source: Path, font: Path | None = None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """Turn a pristine checkout into the Arabic game's source (see the module docstring).

    ``font`` is not used (the glyphs are hand-drawn). A tree this function
    already prepared with the same translation is left as it is; any other
    prepared or changed tree is refused.
    """
    source = source.expanduser().resolve()
    manifest = builtin_manifest()
    engine = builtin_engine_patch()
    texts = translation_texts(translations, manifest, complete=True)
    digest = _translations_digest(texts)
    state = _read_state(source)
    if state is not None:
        _validate_prepared(source, state)
        if state.get("translations_sha256") != digest or state.get("engine_patch") != engine.digest:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                "This checkout was prepared with another translation or engine patch; "
                f"prepare a fresh checkout of {PINNED_COMMIT}",
            )
        return {**_report_head(source), "already_prepared": True, **state.get("report", {})}

    pristine = read_pristine(source)
    outputs, found = build_outputs(pristine, texts, manifest, engine)
    written = {}
    for relative, data in sorted(outputs.items()):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written[relative] = git_blob_sha1(data)
    report = {
        "translation": coverage(texts, manifest),
        "engine_patch": {
            "files": len(engine.files),
            "new_files": sum(item.is_new for item in engine.files),
            "hunks": sum(len(item.hunks) for item in engine.files),
            "sha256": engine.digest,
        },
        **found,
        "files_written": len(written),
        "font": "unused: the glyphs are hand-drawn 8x8 pixel art",
    }
    state = {
        "overlay_version": OVERLAY_VERSION,
        "upstream_commit": PINNED_COMMIT,
        "engine_patch": engine.digest,
        "translations_sha256": digest,
        "source_blobs": {relative: pinned_blobs()[relative] for relative in sorted(pristine)},
        "written": written,
        "report": report,
    }
    (source / STATE_FILE).write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    return {**_report_head(source), "already_prepared": False, **report}


def _report_head(source: Path) -> dict[str, object]:
    return {
        "upstream": REPOSITORY,
        "upstream_tag": PINNED_TAG,
        "upstream_commit": PINNED_COMMIT,
        "source": str(source),
        "rgbds": RGBDS_VERSION,
        "build": f"make  (with rgbds {RGBDS_VERSION}; writes {ROM_NAME})",
    }


def check_polished_crystal_arabic_source(
    source: Path, translations: TranslationSet | None = None
) -> dict[str, object]:
    """Everything prepare checks and computes on a checkout, without writing a file."""
    source = source.expanduser().resolve()
    manifest = builtin_manifest()
    engine = builtin_engine_patch()
    texts = translation_texts(translations, manifest, complete=True)
    pristine = read_pristine(source)
    outputs, found = build_outputs(pristine, texts, manifest, engine)
    return {
        **_report_head(source),
        "files_verified": len(pristine),
        "dry_run": True,
        "would_write": len(outputs),
        **found,
        "translation": coverage(texts, manifest),
    }


# --- the originals, for a translator's workspace ----------------------------------------

_TREE_SUFFIXES = (".asm", ".inc", ".pal", ".link")


def engine_tree(source: Path, into: Path, engine: EnginePatch | None = None) -> dict[str, bytes]:
    """Copy a checkout's sources into ``into`` with the engine patch applied.

    The extractor reads files from disk; it needs the assembly sources (and the
    Makefile), never the build's outputs. Returns the checkout's pinned files.
    """
    engine = engine or builtin_engine_patch()
    pristine = read_pristine(source)
    for path in source.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if path.suffix in _TREE_SUFFIXES or path.name == "Makefile":
            target = into / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for relative, text in engine_sources(pristine, engine).items():
        if relative in engine.paths():
            (into / relative).parent.mkdir(parents=True, exist_ok=True)
            (into / relative).write_text(text, encoding="utf-8", newline="\n")
    return pristine


def _extractor(tree: Path):
    from classic_retro.source.polished_crystal.extract import Extractor

    return Extractor(str(tree)).run()


def extract_polished_crystal_originals(
    source: Path, translations: TranslationSet | None = None
) -> dict[str, str]:
    """Every entry's original, in the translators' notation, from the user's checkout.

    The extractor reads the engine-patched copy of the checkout; each entry must
    be where the manifest pins it. The Pokédex labels come from the tilemaps'
    cells and the key phrase from its string. All of it stays on the user's
    machine (a workspace is never committed).
    """
    source = source.expanduser().resolve()
    manifest = builtin_manifest()
    if translations is not None:
        translation_texts(translations, manifest)
    with tempfile.TemporaryDirectory(prefix="classic-retro-pc-") as temp:
        tree = Path(temp)
        pristine = engine_tree(source, tree)
        extractor = _extractor(tree)
    found = {entry["id"]: entry for entry in extractor.entries}
    originals = {}
    for entry_id, entry in manifest.entries.items():
        other = found.get(entry_id)
        if (
            other is None
            or (other["file"], other["start"], other["end"])
            != (
                entry["file"],
                entry["start"],
                entry["end"],
            )
            or other["sha256"][: len(entry["sha256"])] != entry["sha256"]
        ):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"{entry_id} is not where the manifest pins it"
            )
        originals[entry_id] = extractor.originals[entry_id]
    originals.update(_label_originals(pristine))
    return originals


# The English font's letters, to read the Pokédex's labels from its tilemaps.
_LATIN = {
    **{0x80 + index: chr(65 + index) for index in range(26)},
    **{0xA0 + index: chr(97 + index) for index in range(26)},
    0x9A: "(",
    0x9B: ")",
    0x9C: ".",
    0x9E: "?",
    0x9F: "!",
    0xBC: "-",
    0xBD: ":",
    0xDC: "/",
    0x7F: " ",
    **{0xE0 + digit: str(digit) for digit in range(10)},
}


def _label_originals(pristine: Mapping[str, bytes]) -> dict[str, str]:
    out = {}
    for label in dex.LABELS:
        tiles = pristine[f"{DEX_DIR}/{label.tilemap}.tilemap"]
        base = label.row * dex.WIDTH
        cells = tiles[base + label.clear_first : base + label.clear_last + 1]
        english = "".join(_LATIN.get(code, "?") for code in cells).strip()
        for placement in label.placements:
            if placement.text_id is not None:
                out[placement.text_id] = english
    specials = pristine["engine/events/specials.asm"].decode("utf-8").split("\n")
    at = specials.index(".KeyPhrase:")
    out[KEY_PHRASE_ID] = patch_module.string_literals(specials[at + 1])[0].removesuffix("@")
    return out


# --- for the overlay's developers ------------------------------------------------------


def make_manifest(source: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """The manifest, the contexts by id and the pins, from a pristine checkout.

    The extractor reads the engine-patched copy of the checkout (some engine
    changes restructure strings), so the manifest's line numbers and pins are
    those ``prepare`` meets after the engine patch. The contexts go to the
    translation file; the pins cover every file the overlay reads or writes.
    """
    source = source.expanduser().resolve()
    engine = builtin_engine_patch()
    with tempfile.TemporaryDirectory(prefix="classic-retro-pc-") as temp:
        tree = Path(temp)
        _copy_pinned_tree(source, tree, engine)
        extractor = _extractor(tree)
        sizes = SizeModel(str(tree))
        entries = []
        generated = set(generated_files())
        for entry in extractor.entries:
            if entry["file"] in generated and entry["file"] != NGRAMS:
                continue
            entry = dict(entry)
            limits = dict(entry.get("limits") or {})
            if limits.get("dr_groups"):
                lines = extractor.lines(entry["file"])[entry["start"] - 1 : entry["end"]]
                limits["en_bytes"] = sizes.estimate(lines)
            entry["limits"] = limits
            entries.append(entry)
        files_ = sorted({entry["file"] for entry in entries})
    manifest = manifest_module.compact(
        entries,
        commit=PINNED_COMMIT,
        engine_patch=engine.digest,
        ngram_entries=extractor.manifest()["ngram_entries"],
        groups=extractor.dr_groups,
    )
    contexts = {entry["id"]: entry["context"] for entry in entries}
    pinned = (
        set(files_)
        | set(engine.modified())
        | set(generated_files())
        | {f"{DEX_DIR}/{name}.attrmap" for name in dex.MAPS}
        | set(gfx_labels.pristine_sha256())
    )
    pinned -= {item.path for item in engine.files if item.is_new}
    pinned -= {SHAPING_TABLES, KEY_PHRASE_FILE}
    pins = {}
    for relative in sorted(pinned):
        pins[relative] = git_blob_sha1((source / relative).read_bytes())
    return manifest, contexts, pins


def _copy_pinned_tree(source: Path, tree: Path, engine: EnginePatch) -> None:
    """The checkout's sources with the engine patch, without checking pins (they are made here)."""
    texts = {}
    for path in source.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if path.suffix in _TREE_SUFFIXES or path.name == "Makefile":
            target = tree / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for item in engine.files:
        if not item.is_new:
            texts[item.path] = (source / item.path).read_text(encoding="utf-8")
    for relative, text in patch_module.apply(engine, texts).items():
        (tree / relative).parent.mkdir(parents=True, exist_ok=True)
        (tree / relative).write_text(text, encoding="utf-8", newline="\n")


# --- the patch ------------------------------------------------------------------------


def make_bps(original: Path, arabic: Path, out: Path) -> dict[str, object]:
    """The BPS patch from the user's ROM to the Arabic ROM ``make`` built, verified."""
    base = original.expanduser().read_bytes()
    if hashlib.sha256(base).hexdigest() != ROM_SHA256 or len(base) != ROM_SIZE:
        raise ClassicRetroError(
            ErrorCode.UNKNOWN_GAME_REVISION,
            f"{original} is not {ROM_NAME} (SHA-256 {ROM_SHA256})",
        )
    target = arabic.expanduser().read_bytes()
    if len(target) != ROM_SIZE:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            f"{arabic} is {len(target)} bytes, not {ROM_SIZE}: the build overflowed or failed",
        )
    patch = create_bps(base, target)
    if apply_bps(patch.data, base) != target:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "the BPS does not rebuild the ROM"
        )
    out = out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(patch.data)
    return {
        "game": ROM_NAME,
        "base_sha1": hashlib.sha1(base, usedforsecurity=False).hexdigest(),
        "base_sha256": ROM_SHA256,
        "target_sha256": hashlib.sha256(target).hexdigest(),
        "patch": str(out),
        "patch_sha256": hashlib.sha256(patch.data).hexdigest(),
        "patch_bytes": len(patch.data),
    }


def encode_arabic_line(text: str, width: int = 18) -> dict[str, object]:
    """One speech-box text in the overlay's notation, as the source lines it becomes."""
    tokens, _ = encode.tokenize(text)
    entry = {
        "id": "encode-arabic",
        "kind": "dialog",
        # The text's own placeholders: any the speech box takes.
        "skeleton": [token.a for token in tokens if token.t == "ph"],
        "limits": {"width": width},
        "fmt": {"indent": "\t", "first": "text", "term": "done"},
    }
    lines, errors = encode._encode(entry, text, None)
    shaped = shape(text)
    return {
        "lines": lines,
        "errors": errors,
        "glyph_codes": [
            f"${code:02x}" for code in (glyph_code(char) for char in shaped) if code is not None
        ],
        "cells": encode.cells(text),
        "presentation_forms": sum(char in PRESENTATION_GLYPH for char in shaped),
    }
