"""Final Fantasy VI Advance (USA): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.rom import ff6a_arabic

PREVIEWS = ("arabic_font_preview.png",)


def check_hooks() -> dict[str, object]:
    return ff6a_arabic.check_hook_code()


def check_translations(font: Path | None, preview_dir: Path | None) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return ff6a_arabic.check_ff6a_translations(font, *previews)


def build(rom: bytes, font: Path, out_dir: Path, rom_name: str | None) -> dict[str, object]:
    result = ff6a_arabic.build_ff6a_arabic_rom(rom, font)
    written = ff6a_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def _check_translations_command(args: argparse.Namespace) -> int:
    return print_json(ff6a_arabic.check_ff6a_translations(args.font, args.preview))


def _check_hooks_command(_: argparse.Namespace) -> int:
    return print_json(check_hooks())


def _build_command(args: argparse.Namespace) -> int:
    return print_json(build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom))


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(ff6a_arabic.encode_ff6a_arabic_line(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    ff6a = subcommands.add_parser(
        "ff6a",
        help="Final Fantasy VI Advance (USA) Arabic ROM overlay helpers",
    )
    ff6a_commands = ff6a.add_subparsers(dest="ff6a_command", required=True)

    ff6a_check = ff6a_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    ff6a_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the font and measures every translated line",
    )
    ff6a_check.add_argument(
        "--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG"
    )
    ff6a_check.set_defaults(handler=_check_translations_command)

    ff6a_hooks = ff6a_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    ff6a_hooks.set_defaults(handler=_check_hooks_command)

    ff6a_build = ff6a_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the USA ROM",
    )
    ff6a_build.add_argument("rom", type=Path)
    ff6a_build.add_argument("--font", type=Path, required=True)
    ff6a_build.add_argument("--out-dir", type=Path, required=True)
    ff6a_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    ff6a_build.set_defaults(handler=_build_command)

    ff6a_encode = ff6a_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to FF6A codes in right-to-left paint order",
    )
    ff6a_encode.add_argument("text")
    ff6a_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of the line",
    )
    ff6a_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="ff6a",
    game_id="final-fantasy-vi-advance-usa",
    title="Final Fantasy VI Advance (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope="The new-game opening: the narration, the cliff above Narshe and the way to the mines (19 messages)",
    guide="docs/FF6A_ARABIC_TEST_AR.md",
    notes="docs/FF6A_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    previews=PREVIEWS,
)
