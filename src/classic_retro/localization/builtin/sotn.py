"""Castlevania: Symphony of the Night (USA): the disc overlay."""

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
from classic_retro.rom import sotn_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return sotn_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the disc; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return sotn_arabic.check_sotn_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """``rom`` is the disc's data track (Track 1), the file the patch applies to."""
    result = sotn_arabic.build_sotn_arabic_image(rom, font, translations=translations)
    written = sotn_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own data track."""
    image_spec = sotn_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, sotn_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(sotn_arabic.encode_sotn_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    sotn = subcommands.add_parser(
        "sotn", help="Castlevania: Symphony of the Night (USA) Arabic disc overlay helpers"
    )
    commands = sotn.add_subparsers(dest="sotn_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation ({wait N}, {speed N}, {flag N}, \\n...) in paint order",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the width of each line"
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="sotn",
    game_id="castlevania-sotn-usa",
    title="Castlevania: Symphony of the Night (USA)",
    platform_id="ps1",
    kind="rom-overlay",
    strategies=("composed-lines",),
    scope=(
        "The prologue: Richter's and Dracula's dialogue before the last battle of 1792 "
        "(6 messages) and their names"
    ),
    guide="docs/SOTN_ARABIC_TEST_AR.md",
    notes="docs/SOTN_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="8fec16b975e52257b8687a72b9b7910c88584f8dc4a7bba0a36e19d4b2dfba8f",
)
