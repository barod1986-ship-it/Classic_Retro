"""Mega Man Battle Network (USA): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.rom import mmbn_arabic

PREVIEWS = ("arabic_pages_preview.png",)


def check_hooks() -> dict[str, object]:
    return mmbn_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return mmbn_arabic.check_mmbn_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = mmbn_arabic.build_mmbn_arabic_rom(rom, font, translations=translations)
    written = mmbn_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    origin = f"{mmbn_arabic.IMAGE.title} image, SHA-256 {mmbn_arabic.IMAGE.sha256}"
    return origin, mmbn_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(mmbn_arabic.encode_mmbn_arabic_section(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    mmbn = subcommands.add_parser(
        "mmbn",
        help="Mega Man Battle Network (USA) Arabic ROM overlay helpers",
    )
    mmbn_commands = mmbn.add_subparsers(dest="mmbn_command", required=True)

    mmbn_encode = mmbn_commands.add_parser(
        "encode-arabic",
        help="Encode one section in notation (<, >, \\p, {cls N}...) and report its pages",
    )
    mmbn_encode.add_argument("text")
    mmbn_encode.add_argument(
        "--font", type=Path, required=True, help="Arabic TTF/OTF the pages are drawn with"
    )
    mmbn_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="mmbn",
    game_id="megaman-battle-network-usa",
    title="Mega Man Battle Network (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("line-cells",),
    scope="Lan's first morning, from a new game to the school gate (50 script sections)",
    guide="docs/MMBN_ARABIC_TEST_AR.md",
    notes="docs/MMBN_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="78046aa04cc5f64ada2dff69b35a4bd50564b71685fa3469ed5323d1056e9b7a",
)
