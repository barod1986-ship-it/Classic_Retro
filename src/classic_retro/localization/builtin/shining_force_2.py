"""Shining Force II (USA): the ROM overlay."""

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
from classic_retro.rom import sf2_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return sf2_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The strings checked without the ROM; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return sf2_arabic.check_sf2_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = sf2_arabic.build_sf2_arabic_rom(rom, font, translations=translations)
    written = sf2_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own ROM."""
    image_spec = sf2_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, sf2_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(sf2_arabic.encode_sf2_arabic_string(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    shining_force_2 = subcommands.add_parser(
        "shining-force-2", help="Shining Force II (USA) Arabic ROM overlay helpers"
    )
    commands = shining_force_2.add_subparsers(dest="shining_force_2_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one string in notation ({N} a line, {W2} a wait for the button)",
    )
    encode.add_argument("text")
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to lay the lines out")
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="shining-force-2",
    game_id="shining-force-2-usa",
    title="Shining Force II (USA)",
    platform_id="megadrive",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "Three strings of the witch who starts a new game (her greeting, her question, "
        "her word on the name the player gave); the others stay in English"
    ),
    guide="docs/SF2_ARABIC_TEST_AR.md",
    notes="docs/SF2_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="e61bed7cd87039dfad10ca4483974d944c681892a27304e3b12483be8166bc89",
)
