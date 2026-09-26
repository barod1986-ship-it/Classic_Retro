"""Pokémon Platinum (USA, Rev 0): the binary ROM overlay, the first Nintendo DS target."""

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
from classic_retro.rom import platinum_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return platinum_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return platinum_arabic.check_platinum_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = platinum_arabic.build_platinum_arabic_rom(rom, font, translations=translations)
    written = platinum_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    rom = image.read_bytes()
    base = platinum_arabic.verify_platinum_image(rom)
    origin = f"{platinum_arabic.TITLE} image ({base})"
    return origin, platinum_arabic.extract_originals(rom, translations)


def _check_translations_command(args: argparse.Namespace) -> int:
    return print_json(
        platinum_arabic.check_platinum_translations(args.font, args.preview, args.text_preview)
    )


def _check_hooks_command(_: argparse.Namespace) -> int:
    return print_json(check_hooks())


def _build_command(args: argparse.Namespace) -> int:
    return print_json(build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom))


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        platinum_arabic.encode_platinum_arabic_string(args.text, args.font, window=args.window)
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    platinum = subcommands.add_parser(
        "platinum", help="Pokémon Platinum (USA, Rev 0) Arabic ROM overlay helpers"
    )
    commands = platinum.add_subparsers(dest="platinum_command", required=True)

    check = commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the right-to-left glyphs and measures every line",
    )
    check.add_argument("--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG")
    check.add_argument(
        "--text-preview",
        type=Path,
        help="Write every translated string, laid out as the game shows it, as one PNG",
    )
    check.set_defaults(handler=_check_translations_command)

    hooks = commands.add_parser(
        "check-hooks",
        help="Re-assemble the ARM9 Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    hooks.set_defaults(handler=_check_hooks_command)

    build_parser = commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    build_parser.add_argument("rom", type=Path)
    build_parser.add_argument("--font", type=Path, required=True)
    build_parser.add_argument("--out-dir", type=Path, required=True)
    build_parser.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    build_parser.set_defaults(handler=_build_command)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one string in notation (\\n, \\r, \\f, {STRVAR_1 3, 0, 0}...) in paint order",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the width of each line"
    )
    encode.add_argument(
        "--window",
        choices=tuple(platinum_arabic.WINDOWS),
        default="dialogue",
        help="The intro's window the string is shown in (the message box by default)",
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="platinum",
    game_id="pokemon-platinum-usa",
    title="Pokémon Platinum Version (USA, Rev 0)",
    platform_id="nds",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "Professor Rowan's new-game intro, its info pages and menus, and the television "
        "comment that ends it (38 strings)"
    ),
    guide="docs/PLATINUM_ARABIC_TEST_AR.md",
    notes="docs/PLATINUM_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    # The patch from No-Intro Rev 0 (the image pret/pokeplatinum builds), then
    # from the dump with the header's reserved bytes cleared.
    reference_patch_sha256="12749c9d5384f579d66f1b6c018010e5d5828b77a6e2dc4cce27b0e0f3f1a0e9",
    reference_patches={
        "ede62292aa7f7014ff27d42097e769753380531739889c29b968b67b80f80678": (
            "12749c9d5384f579d66f1b6c018010e5d5828b77a6e2dc4cce27b0e0f3f1a0e9"
        ),
        "67de86a1bc8e7eb6479dbbbd6e8f5edfc2fa160576a38e40e06d2180ed63b110": (
            "6690bae4422dad9dd2a58adc0d4eb03aa65589f02e0b0604cb03bb9adf3717db"
        ),
    },
)
