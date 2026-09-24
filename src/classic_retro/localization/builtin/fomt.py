"""Harvest Moon: Friends of Mineral Town (USA): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.rom import fomt_arabic

PREVIEWS = ("arabic_text_preview.png",)


def check_hooks() -> dict[str, object]:
    return fomt_arabic.check_hook_code()


def check_translations(font: Path | None, preview_dir: Path | None) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return fomt_arabic.check_fomt_translations(font, *previews)


def build(rom: bytes, font: Path, out_dir: Path, rom_name: str | None) -> dict[str, object]:
    result = fomt_arabic.build_fomt_arabic_rom(rom, font)
    written = fomt_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def _check_translations_command(args: argparse.Namespace) -> int:
    return print_json(fomt_arabic.check_fomt_translations(args.font, args.text_preview))


def _check_hooks_command(_: argparse.Namespace) -> int:
    return print_json(check_hooks())


def _build_command(args: argparse.Namespace) -> int:
    return print_json(build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom))


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(fomt_arabic.encode_fomt_arabic_text(args.text, args.font, story=args.story))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    fomt = subcommands.add_parser(
        "fomt",
        help="Harvest Moon: Friends of Mineral Town (USA) Arabic ROM overlay helpers",
    )
    fomt_commands = fomt.add_subparsers(dest="fomt_command", required=True)

    fomt_check = fomt_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, lay out every string",
    )
    fomt_check.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF; also draws every line and counts its cells"
    )
    fomt_check.add_argument(
        "--text-preview",
        type=Path,
        help="Write every translated box and name tag, laid out as the game draws it, as one PNG",
    )
    fomt_check.set_defaults(handler=_check_translations_command)

    fomt_hooks = fomt_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    fomt_hooks.set_defaults(handler=_check_hooks_command)

    fomt_build = fomt_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    fomt_build.add_argument("rom", type=Path)
    fomt_build.add_argument("--font", type=Path, required=True)
    fomt_build.add_argument("--out-dir", type=Path, required=True)
    fomt_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    fomt_build.set_defaults(handler=_build_command)

    fomt_encode = fomt_commands.add_parser(
        "encode-arabic",
        help="Encode one string in notation (\\n, {wait}, {clear}, {name}) as cell codes",
    )
    fomt_encode.add_argument("text")
    fomt_encode.add_argument(
        "--font", type=Path, required=True, help="Arabic TTF/OTF the lines are drawn with"
    )
    fomt_encode.add_argument(
        "--story",
        action="store_true",
        help="A story scene string (its name placeholder is a lone FF) rather than a script's",
    )
    fomt_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="fomt",
    game_id="harvest-moon-fomt-usa",
    title="Harvest Moon: Friends of Mineral Town (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("line-cells",),
    scope="The opening: Thomas on the farm, the flashback and the first morning (33 strings, 5 name tags)",
    guide="docs/FOMT_ARABIC_TEST_AR.md",
    notes="docs/FOMT_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    previews=PREVIEWS,
    reference_patch_sha256="8f565de602ec34b11b110886807eefac34ea2db8a36bf86191c5cb0cfa88058f",
)
