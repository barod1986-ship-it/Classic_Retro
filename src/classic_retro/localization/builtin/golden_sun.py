"""Golden Sun (USA, Europe): the binary ROM overlay."""

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
from classic_retro.rom import golden_sun_arabic

PREVIEWS = ("arabic_font_preview.png",)


def check_hooks() -> dict[str, object]:
    return golden_sun_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return golden_sun_arabic.check_golden_sun_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = golden_sun_arabic.build_golden_sun_arabic_rom(rom, font, translations=translations)
    written = golden_sun_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    origin = f"{golden_sun_arabic.IMAGE.title} image, SHA-256 {golden_sun_arabic.IMAGE.sha256}"
    return origin, golden_sun_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(golden_sun_arabic.encode_golden_sun_arabic_line(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    golden_sun = subcommands.add_parser(
        "golden-sun",
        help="Golden Sun (USA, Europe) Arabic ROM overlay helpers",
    )
    golden_sun_commands = golden_sun.add_subparsers(dest="golden_sun_command", required=True)

    golden_sun_encode = golden_sun_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to Golden Sun codes in right-to-left paint order",
    )
    golden_sun_encode.add_argument("text")
    golden_sun_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of the line",
    )
    golden_sun_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="golden-sun",
    game_id="golden-sun-usa-europe",
    title="Golden Sun (USA, Europe)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope="The storm-night opening, both Yes/No branches (21 messages)",
    guide="docs/GOLDEN_SUN_ARABIC_TEST_AR.md",
    notes="docs/GOLDEN_SUN_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="41755b00e0ba0e13e9e78175807f27d9d069f3efb5f93954f35cacd9e3958f65",
)
