"""Advance Wars (USA, Rev 1): the binary ROM overlay."""

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
from classic_retro.rom import advance_wars_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return advance_wars_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return advance_wars_arabic.check_advance_wars_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = advance_wars_arabic.build_advance_wars_arabic_rom(rom, font, translations=translations)
    written = advance_wars_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    origin = f"{advance_wars_arabic.IMAGE.title} image, SHA-256 {advance_wars_arabic.IMAGE.sha256}"
    return origin, advance_wars_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(advance_wars_arabic.encode_advance_wars_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    advance_wars = subcommands.add_parser(
        "advance-wars",
        help="Advance Wars (USA, Rev 1) Arabic ROM overlay helpers",
    )
    commands = advance_wars.add_subparsers(dest="advance_wars_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message text in notation ({0F}, {15}, {16}, \\n) in paint order",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the width of each line"
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="advance-wars",
    game_id="advance-wars-usa",
    title="Advance Wars (USA, Rev 1)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope="Nell's opening, up to the first Field Training lesson (14 messages)",
    guide="docs/ADVANCE_WARS_ARABIC_TEST_AR.md",
    notes="docs/ADVANCE_WARS_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="7e4a32315de0af0506c3f1c3486fd2633635c0dc735824f0c553abe7be42cdc2",
)
