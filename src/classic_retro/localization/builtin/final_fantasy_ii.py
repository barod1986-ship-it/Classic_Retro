"""Final Fantasy II (USA, Rev 1): the ROM overlay."""

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
from classic_retro.rom import ff4_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return ff4_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The messages checked without the ROM; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return ff4_arabic.check_ff4_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = ff4_arabic.build_ff4_arabic_rom(rom, font, translations=translations)
    written = ff4_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own ROM."""
    image_spec = ff4_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, ff4_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(ff4_arabic.encode_ff4_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    final_fantasy_ii = subcommands.add_parser(
        "final-fantasy-ii", help="Final Fantasy II (USA, Rev 1) Arabic ROM overlay helpers"
    )
    commands = final_fantasy_ii.add_subparsers(dest="final_fantasy_ii_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation (a line a page, {line} to end a row)",
    )
    encode.add_argument("text")
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to lay the pages out")
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="final-fantasy-ii",
    game_id="final-fantasy-ii-usa",
    title="Final Fantasy II (USA, Rev 1)",
    platform_id="snes",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "Six messages of the opening on the deck of the Red Wings' airship, and the "
        "characters' names in them; the others stay in English"
    ),
    guide="docs/FF4_ARABIC_TEST_AR.md",
    notes="docs/FF4_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="449f47b41bfcda150b51b5195d1b263e12af3e2eabadfecfca3b116ddec99d68",
)
