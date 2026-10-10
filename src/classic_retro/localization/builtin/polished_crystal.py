"""Pokémon Polished Crystal 3.2.3: the source overlay on Rangi42/polishedcrystal (Game Boy Color)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from classic_retro.localization.targets import LocalizationTarget, preview_paths, print_json
from classic_retro.localization.translations import TranslationSet, load_translation_set
from classic_retro.source.polished_crystal import manifest as manifest_module
from classic_retro.source.polished_crystal import patch as patch_module
from classic_retro.source.polished_crystal_arabic import (
    GLYPH_ATLAS,
    PINNED_COMMIT,
    PINNED_TAG,
    SPECIMEN,
    check_polished_crystal_arabic_source,
    check_polished_crystal_translations,
    encode_arabic_line,
    extract_polished_crystal_originals,
    make_bps,
    make_manifest,
    prepare_polished_crystal_arabic_source,
)
from classic_retro.source.polished_crystal_arabic import TARGET as TARGET_ID

# The glyph atlas and a specimen of speech-box rows, drawn with the hand-drawn glyphs.
PREVIEWS = (GLYPH_ATLAS, SPECIMEN)
DATA = Path(__file__).resolve().parents[2] / "source" / "polished_crystal" / "data"


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """Every translated entry encoded with its limits, without a checkout.

    The font is not read: the glyphs are hand-drawn 8x8 pixel art, as the
    reference font is illegible at 8 pixels. It only decides, as for every
    target, whether the previews are written.
    """
    atlas, specimen = preview_paths(font, preview_dir, *PREVIEWS)
    return check_polished_crystal_translations(atlas, specimen, translations=translations)


def prepare(
    source: Path, font: Path, translations: TranslationSet | None = None
) -> dict[str, object]:
    """Patch the user's pristine checkout: the engine, the generated files and the Arabic."""
    return prepare_polished_crystal_arabic_source(source, font, translations)


def extract(source: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read from the user's pristine checkout."""
    origin = f"Rangi42/polishedcrystal {PINNED_TAG} ({PINNED_COMMIT}), with the engine patch"
    return origin, extract_polished_crystal_originals(source, translations)


def _source_check(args: argparse.Namespace) -> int:
    translations = None if args.translations is None else load_translation_set(args.translations)
    return print_json(check_polished_crystal_arabic_source(args.source, translations))


def _encode_arabic(args: argparse.Namespace) -> int:
    return print_json(encode_arabic_line(args.text, args.width))


def _make_bps(args: argparse.Namespace) -> int:
    return print_json(make_bps(args.original, args.arabic, args.out))


def _make_manifest(args: argparse.Namespace) -> int:
    manifest, contexts, pins = make_manifest(args.source)
    out = args.out_dir or DATA
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(manifest_module.dumps(manifest), encoding="utf-8")
    (out / "pins.json").write_text(
        json.dumps({"commit": PINNED_COMMIT, "blobs": pins}, indent=1) + "\n", encoding="utf-8"
    )
    report: dict[str, object] = {
        "manifest": str(out / "manifest.json"),
        "pins": str(out / "pins.json"),
        "entries": sum(len(rows) for rows in manifest["files"].values()),
        "files": len(manifest["files"]),
        "pinned_files": len(pins),
    }
    if args.contexts is not None:
        args.contexts.write_text(
            json.dumps(contexts, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
        )
        report["contexts"] = str(args.contexts)
    return print_json(report)


def _make_engine_patch(args: argparse.Namespace) -> int:
    patch = patch_module.make_engine_patch(args.repository, args.base, args.ref)
    out = args.out or DATA / "engine_patch.json"
    out.write_text(patch_module.dumps(patch), encoding="utf-8")
    return print_json(
        {
            "engine_patch": str(out),
            "engine_commit": patch.engine,
            "files": len(patch.files),
            "new_files": sum(item.is_new for item in patch.files),
            "hunks": sum(len(item.hunks) for item in patch.files),
            "next": "run make-manifest on a pristine checkout: the manifest follows the patch",
        }
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    group = subcommands.add_parser(
        "polished-crystal",
        help="Pokémon Polished Crystal 3.2.3 (Rangi42/polishedcrystal) helpers",
    )
    commands = group.add_subparsers(dest="polished_crystal_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one speech-box text in the overlay's notation to its source lines",
    )
    encode.add_argument("text")
    encode.add_argument("--width", type=int, default=18, help="Cells a line (18 in the speech box)")
    encode.set_defaults(handler=_encode_arabic)

    source_check = commands.add_parser(
        "source-check",
        help="Dry-run prepare on a pristine checkout: pins, engine patch, every entry, the codes",
    )
    source_check.add_argument("source", type=Path)
    source_check.add_argument("--translations", type=Path, help="A translations file or workspace")
    source_check.set_defaults(handler=_source_check)

    bps = commands.add_parser(
        "make-bps",
        help="Make (and verify) the BPS patch from your ROM and the Arabic ROM make built",
    )
    bps.add_argument("original", type=Path, help="Your polishedcrystal-3.2.3.gbc")
    bps.add_argument("arabic", type=Path, help="The ROM the prepared checkout built")
    bps.add_argument("--out", type=Path, default=Path("polishedcrystal-3.2.3-arabic.bps"))
    bps.set_defaults(handler=_make_bps)

    manifest = commands.add_parser(
        "make-manifest",
        help="(Developers) rebuild the manifest and pins from a pristine checkout",
    )
    manifest.add_argument("source", type=Path)
    manifest.add_argument("--out-dir", type=Path, help="Where to write (default: the package data)")
    manifest.add_argument(
        "--contexts", type=Path, help="Also write every entry's context (id -> text) here"
    )
    manifest.set_defaults(handler=_make_manifest)

    engine_patch = commands.add_parser(
        "make-engine-patch",
        help="(Developers) rebuild the engine patch from an engine branch of polishedcrystal",
    )
    engine_patch.add_argument("repository", type=Path, help="A git clone with the engine commits")
    engine_patch.add_argument("--base", default=PINNED_COMMIT)
    engine_patch.add_argument("--ref", default="main")
    engine_patch.add_argument("--out", type=Path, help="Where to write (default: the package data)")
    engine_patch.set_defaults(handler=_make_engine_patch)


TARGET = LocalizationTarget(
    id=TARGET_ID,
    game_id="pokemon-polished-crystal-3.2.3",
    title="Pokémon Polished Crystal 3.2.3 (Game Boy Color)",
    platform_id="gbc",
    kind="source-overlay",
    strategies=("glyph-font",),
    scope="The whole game's text, as far as translated (the coverage is in the report)",
    guide="docs/POLISHED_CRYSTAL_ARABIC_TEST_AR.md",
    notes="docs/POLISHED_CRYSTAL_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_translations=check_translations,
    prepare=prepare,
    extract=extract,
    previews=PREVIEWS,
)
