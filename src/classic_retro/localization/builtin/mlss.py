"""Mario & Luigi: Superstar Saga (USA): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.rom import mlss_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return mlss_arabic.check_hook_code()


def check_translations(font: Path | None, preview_dir: Path | None) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return mlss_arabic.check_mlss_translations(font, *previews)


def build(rom: bytes, font: Path, out_dir: Path, rom_name: str | None) -> dict[str, object]:
    result = mlss_arabic.build_mlss_arabic_rom(rom, font)
    written = mlss_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def _check_translations_command(args: argparse.Namespace) -> int:
    return print_json(
        mlss_arabic.check_mlss_translations(args.font, args.preview, args.text_preview)
    )


def _check_hooks_command(_: argparse.Namespace) -> int:
    return print_json(check_hooks())


def _build_command(args: argparse.Namespace) -> int:
    return print_json(build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom))


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(mlss_arabic.encode_mlss_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    mlss = subcommands.add_parser(
        "mlss",
        help="Mario & Luigi: Superstar Saga (USA) Arabic ROM overlay helpers",
    )
    mlss_commands = mlss.add_subparsers(dest="mlss_command", required=True)

    mlss_check = mlss_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every message",
    )
    mlss_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the right-to-left font and computes every header",
    )
    mlss_check.add_argument(
        "--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG"
    )
    mlss_check.add_argument(
        "--text-preview",
        type=Path,
        help="Write every translated message, laid out as the game draws it, as one PNG",
    )
    mlss_check.set_defaults(handler=_check_translations_command)

    mlss_hooks = mlss_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hook with arm-none-eabi binutils and compare the bytes",
    )
    mlss_hooks.set_defaults(handler=_check_hooks_command)

    mlss_build = mlss_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    mlss_build.add_argument("rom", type=Path)
    mlss_build.add_argument("--font", type=Path, required=True)
    mlss_build.add_argument("--out-dir", type=Path, required=True)
    mlss_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    mlss_build.set_defaults(handler=_build_command)

    mlss_encode = mlss_commands.add_parser(
        "encode-arabic",
        help="Encode one message text in notation ({FF 0B 01}, \\n, ... {FF 0A}) in paint order",
    )
    mlss_encode.add_argument("text")
    mlss_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the width of each line and the header",
    )
    mlss_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="mlss",
    game_id="mario-luigi-superstar-saga-usa",
    title="Mario & Luigi: Superstar Saga (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope="The opening up to the first battle (12 messages)",
    guide="docs/MLSS_ARABIC_TEST_AR.md",
    notes="docs/MLSS_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    previews=PREVIEWS,
    reference_patch_sha256="39803b96a4f4cfe5f8c4ec1ab23d6a0fd861683d1b318cc3637a3ad75271eb58",
)
