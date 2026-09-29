"""Final Fantasy III (USA): the ROM overlay."""

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
from classic_retro.rom import ff6_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return ff6_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The messages checked without the ROM; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return ff6_arabic.check_ff6_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = ff6_arabic.build_ff6_arabic_rom(rom, font, translations=translations)
    written = ff6_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own ROM."""
    image_spec = ff6_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, ff6_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(ff6_arabic.encode_ff6_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    final_fantasy_iii = subcommands.add_parser(
        "final-fantasy-iii", help="Final Fantasy III (USA) Arabic ROM overlay helpers"
    )
    commands = final_fantasy_iii.add_subparsers(dest="final_fantasy_iii_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation (a line a page, {line} to end a line)",
    )
    encode.add_argument("text")
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to lay the pages out")
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="final-fantasy-iii",
    game_id="final-fantasy-iii-usa",
    title="Final Fantasy III (USA)",
    platform_id="snes",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "The first ten chapters, the opening to Cyan's dream: the 2796 messages "
        "of Narshe, Figaro Castle, South Figaro, Mt. Kolts, the Returners' hideout and "
        "the raft, the three scenarios (Locke and Celes, Banon's party, Sabin's road "
        "through Doma, the Phantom Train, the Veldt and Nikeah), the classroom, the "
        "battle for Narshe and Terra's flight, then Kohlingen, Jidoor, Zozo and Ramuh, "
        "the Opera House and Setzer's coin, then Vector, the Magitek Research Facility, "
        "the escape and Maduin's story, then the sealed gate, the Espers' rush on Vector, "
        "the banquet and Albrook, then Thamasa, the Espers, Leo's death and the Floating "
        "Continent, then Celes's island, Mobliz, Nikeah, Figaro Castle and the Ancient "
        "Castle, the Colosseum, Daryl's tomb, Cyan's letters, Gogo and the Phoenix, Tritoch, "
        "Jidoor's auction, Owzer and Cyan's dream, and the "
        "characters' names in them; the "
        "others stay in English"
    ),
    guide="docs/FF6_ARABIC_TEST_AR.md",
    notes="docs/FF6_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="654339011be377f07d80b94953e3e349755d851eddd9f2a9074da8cb928f08fa",
)
