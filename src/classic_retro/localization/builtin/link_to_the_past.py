"""The Legend of Zelda: A Link to the Past (USA): the ROM overlay."""

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
from classic_retro.rom import alttp_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return alttp_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The messages checked without the ROM; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return alttp_arabic.check_alttp_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = alttp_arabic.build_alttp_arabic_rom(rom, font, translations=translations)
    written = alttp_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own ROM."""
    image_spec = alttp_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, alttp_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(alttp_arabic.encode_alttp_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    link_to_the_past = subcommands.add_parser(
        "link-to-the-past", help="A Link to the Past (USA) Arabic ROM overlay helpers"
    )
    commands = link_to_the_past.add_subparsers(dest="link_to_the_past_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation (a line a page, {line} to end a line)",
    )
    encode.add_argument("text")
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to lay the pages out")
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="link-to-the-past",
    game_id="zelda-link-to-the-past-usa",
    title="The Legend of Zelda: A Link to the Past (USA)",
    platform_id="snes",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "Three messages of the opening (Zelda's call, Link's uncle leaving, the lamp in the "
        "chest); the others stay in English"
    ),
    guide="docs/ALTTP_ARABIC_TEST_AR.md",
    notes="docs/ALTTP_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="909eb8e405583012e1b526a56a5b8b5e0eea134077d3bd80161b0f29e85b6479",
)
