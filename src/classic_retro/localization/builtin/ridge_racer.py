"""Ridge Racer (USA): the disc overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.engines.ridge_racer_arabic import FONTS, SMALL
from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.rom import ridge_racer_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_strings_preview.png")


def check_hooks() -> dict[str, object]:
    return ridge_racer_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The strings checked without the disc; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return ridge_racer_arabic.check_ridge_racer_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """``rom`` is the disc's data track (Track 01), the file the patch applies to."""
    result = ridge_racer_arabic.build_ridge_racer_arabic_image(rom, font, translations=translations)
    written = ridge_racer_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own data track."""
    image_spec = ridge_racer_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, ridge_racer_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        ridge_racer_arabic.encode_ridge_racer_arabic_string(args.text, args.size, args.font)
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    ridge_racer = subcommands.add_parser(
        "ridge-racer", help="Ridge Racer (USA) Arabic disc overlay helpers"
    )
    commands = ridge_racer.add_subparsers(dest="ridge_racer_command", required=True)

    encode = commands.add_parser(
        "encode-arabic", help="Encode one string's glyphs in visual order (without the header)"
    )
    encode.add_argument("text")
    encode.add_argument(
        "--size", choices=FONTS, default=SMALL, help="The font that draws it (default: small)"
    )
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to report the width")
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="ridge-racer",
    game_id="ridge-racer-usa",
    title="Ridge Racer (USA)",
    platform_id="ps1",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "Three strings of the program: the title screen's prompt, the main menu's help line "
        "with the pad's buttons, and the memory card load screen's title; the others stay "
        "in English"
    ),
    guide="docs/RIDGE_RACER_ARABIC_TEST_AR.md",
    notes="docs/RIDGE_RACER_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="13b861334cea6cedea139a56f7edc3dfa727a39d8c95e1852f252eb15ec653d0",
)
