"""Chrono Trigger (USA): the ROM overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet, load_translation_set
from classic_retro.rom import chrono_trigger_arabic
from classic_retro.rom.chrono_trigger_tables import (
    adopt_table,
    check_table,
    list_tables,
    load_plan,
    plan_table,
    table_offset,
    table_workspace,
)

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return chrono_trigger_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The messages checked without the ROM; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return chrono_trigger_arabic.check_chrono_trigger_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = chrono_trigger_arabic.build_chrono_trigger_arabic_rom(
        rom, font, translations=translations
    )
    written = chrono_trigger_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own ROM."""
    image_spec = chrono_trigger_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, chrono_trigger_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        chrono_trigger_arabic.encode_chrono_trigger_arabic_message(args.text, args.font)
    )


def _tables_command(args: argparse.Namespace) -> int:
    rom = args.rom.read_bytes()
    chrono_trigger_arabic.verify_usa_image(rom)
    return print_json(list_tables(rom))


def _writable(path: Path, force: bool) -> Path:
    if path.exists() and not force:
        raise ClassicRetroError(
            ErrorCode.OUTPUT_EXISTS, f"{path} exists; pass --force to replace it"
        )
    return path


def _new_table_command(args: argparse.Namespace) -> int:
    rom = args.rom.read_bytes()
    table = table_offset(args.address)
    plan, originals = plan_table(rom, table, args.key, args.what or "")
    out_dir = args.out_dir
    plan_path = _writable(out_dir / f"{args.key}.plan.json", args.force)
    workspace_path = _writable(out_dir / f"{args.key}.workspace.json", args.force)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    workspace = table_workspace(plan, originals)
    workspace_path.write_text(workspace.dumps(), encoding="utf-8")
    return print_json(
        {
            "table": plan["table"],
            "plan": str(plan_path),
            "workspace": str(workspace_path),
            "decisions": len(plan["decisions"]),
            "tails": len(plan["tails"]),
            "review": len(plan["review"]),
            "events": plan["events"],
        }
    )


def _check_table_command(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    translations = load_translation_set(args.translations, TARGET.id)
    report = check_table(plan, translations, args.font)
    print_json({"translations": str(args.translations), **report})
    return 0 if report["ok"] else 1


def _adopt_table_command(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    workspace = load_translation_set(args.workspace, TARGET.id)
    return print_json(adopt_table(plan, workspace, args.font, what=args.what))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    chrono_trigger = subcommands.add_parser(
        "chrono-trigger", help="Chrono Trigger (USA) Arabic ROM overlay helpers"
    )
    commands = chrono_trigger.add_subparsers(dest="chrono_trigger_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation (a line a box, {line} to end a line)",
    )
    encode.add_argument("text")
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to lay the boxes out")
    encode.set_defaults(handler=_encode_command)

    tables = commands.add_parser(
        "tables",
        help="The dialogue's fifteen string tables in your ROM: strings, and which are translated",
    )
    tables.add_argument("rom", type=Path)
    tables.set_defaults(handler=_tables_command)

    new_table = commands.add_parser(
        "new-table",
        help="Read a string table from your ROM: a local workspace of its originals and a plan "
        "(pins, decisions, chains) that holds no text of the game",
    )
    new_table.add_argument("rom", type=Path)
    new_table.add_argument("address", help="The table's address, as tables lists it ($F8:4650)")
    new_table.add_argument("key", help="The table's key in the entries' ids (lower case)")
    new_table.add_argument("--what", help="What the table holds: its places first, by commas")
    new_table.add_argument("--out-dir", type=Path, default=Path("."))
    new_table.add_argument("--force", action="store_true", help="Replace existing files")
    new_table.set_defaults(handler=_new_table_command)

    check_table = commands.add_parser(
        "check-table",
        help="Check a new table's translated messages, or a batch of them, one by one",
    )
    check_table.add_argument("plan", type=Path)
    check_table.add_argument("translations", type=Path, help="The table's workspace, or a batch")
    check_table.add_argument("--font", type=Path, help="Arabic TTF/OTF: lay the boxes out too")
    check_table.set_defaults(handler=_check_table_command)

    adopt_table = commands.add_parser(
        "adopt-table",
        help="Put a translated table into the script module and the shipped translations",
    )
    adopt_table.add_argument("plan", type=Path)
    adopt_table.add_argument("workspace", type=Path)
    adopt_table.add_argument("--font", type=Path, required=True)
    adopt_table.add_argument("--what", help="What the table holds, if the plan does not say")
    adopt_table.set_defaults(handler=_adopt_table_command)


TARGET = LocalizationTarget(
    id="chrono-trigger",
    game_id="chrono-trigger-usa",
    title="Chrono Trigger (USA)",
    platform_id="snes",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "The dialogue table by table: three of the game's fifteen string tables, 2058 "
        "messages of Crono's house and Truce in 1000 and in 600, Truce Canyon, the "
        "prison's cell, Lab 32, the Proto Dome, the Sun Keep and the Geno Dome; of "
        "Leene Square with the Millennial Fair, the trial, the castle's cellars, Melchior's "
        "hut, Norstein Bekkler's tent, the Tyrano Lair's cells, the Lavos crater, Zeal's "
        "sealed palace and Death Peak; and of Castle Guardia in 600 and 1000, the domes of "
        "2300 A.D., Medina, the End of Time with Gaspar and Spekkio, Ozzie's and Magus's "
        "scenes, the Blackbird and the Reptites' land; the other twelve tables stay English"
    ),
    guide="docs/CHRONO_TRIGGER_ARABIC_TEST_AR.md",
    notes="docs/CHRONO_TRIGGER_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="dcbb38d299ddf98716482e253ec28a138e79a0509eeb840f96696a9ece5fc1e2",
)
