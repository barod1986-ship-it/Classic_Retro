"""Gran Turismo (USA) (Rev 1): the disc overlay."""

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
from classic_retro.rom import gran_turismo_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_briefings_preview.png")


def check_hooks() -> dict[str, object]:
    return gran_turismo_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The briefings checked without the disc; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return gran_turismo_arabic.check_gran_turismo_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """``rom`` is the disc's data track, the file the patch applies to."""
    result = gran_turismo_arabic.build_gran_turismo_arabic_image(
        rom, font, translations=translations
    )
    written = gran_turismo_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own data track."""
    image_spec = gran_turismo_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, gran_turismo_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(gran_turismo_arabic.encode_gran_turismo_arabic_briefing(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    gran_turismo = subcommands.add_parser(
        "gran-turismo", help="Gran Turismo (USA) (Rev 1) Arabic disc overlay helpers"
    )
    commands = gran_turismo.add_subparsers(dest="gran_turismo_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one briefing in notation (its title, then a line per paragraph)",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the title's and lines' widths"
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="gran-turismo",
    game_id="gran-turismo-usa",
    title="Gran Turismo (USA) (Rev 1)",
    platform_id="ps1",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "Three license test briefings (B-1, B-3 and B-8: their titles, instructions, cars and "
        "time limits); the other 21 stay in English"
    ),
    guide="docs/GRAN_TURISMO_ARABIC_TEST_AR.md",
    notes="docs/GRAN_TURISMO_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="c9318ea13a1a5e3a1a846fd4c9b9cdb9291fa04c3a844afd4996c8cf32d80559",
)
