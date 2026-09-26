"""``classic-retro targets``: what every localization target runs the same way.

Each target also keeps its own command group; these commands take a target id
instead, so a script or a CI matrix can run any target without knowing its
module. ``--translations`` gives any of them a translations file or workspace
(``classic_retro.localization.translations``) instead of the shipped one.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.targets import LocalizationTarget, TargetRegistry, print_json
from classic_retro.localization.translations import (
    TranslationSet,
    builtin_translation_set,
    glossary_report,
    load_translation_set,
)

_TRANSLATIONS_HELP = "Use this translations file or workspace instead of the shipped one"


def register_cli(subcommands: argparse._SubParsersAction, registry: TargetRegistry) -> None:
    """Every target's own command group, then the ``targets`` group."""
    for target in registry:
        target.register_cli(subcommands)

    group = subcommands.add_parser(
        "targets",
        help="List localization targets and run their checks and builds by target id",
    )
    commands = group.add_subparsers(dest="targets_command", required=True)

    listing = commands.add_parser(
        "list", help="Every target: its game, platform, strategies, documents and operations"
    )
    listing.set_defaults(handler=lambda _: print_json([t.describe() for t in registry]))

    strategies = commands.add_parser(
        "strategies",
        help="Every registered way of drawing Arabic, and the targets that use it",
    )
    strategies.set_defaults(
        handler=lambda _: print_json(
            [
                {**strategy.describe(), "targets": registry.using(strategy.id)}
                for strategy in registry.strategies
            ]
        )
    )

    hooks = commands.add_parser(
        "check-hooks",
        help="Re-assemble the hook code of targets (all of them without ids) and compare it",
    )
    hooks.add_argument("targets", nargs="*", metavar="TARGET")
    hooks.set_defaults(handler=lambda args: _check_hooks(registry, args.targets))

    check = commands.add_parser(
        "check-translations",
        help="Validate a target's script without the game image; with --font, lay it out",
    )
    check.add_argument("target")
    check.add_argument("--font", type=Path, help="Arabic TTF/OTF to draw every string with")
    check.add_argument(
        "--preview-dir", type=Path, help="With --font: write the target's previews into it"
    )
    check.add_argument("--translations", type=Path, help=_TRANSLATIONS_HELP)
    check.set_defaults(handler=lambda args: _check_translations(registry, args))

    build = commands.add_parser(
        "build", help="Build a target's patch from its game image and compare it with the reference"
    )
    build.add_argument("target")
    build.add_argument("rom", type=Path)
    build.add_argument("--font", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    build.add_argument("--translations", type=Path, help=_TRANSLATIONS_HELP)
    build.set_defaults(handler=lambda args: _build(registry, args))

    prepare = commands.add_parser(
        "prepare",
        help="Patch a pristine decompilation checkout of a source-overlay target",
    )
    prepare.add_argument("target")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("--font", type=Path, required=True)
    prepare.add_argument("--translations", type=Path, help=_TRANSLATIONS_HELP)
    prepare.set_defaults(handler=lambda args: _prepare(registry, args))

    extract = commands.add_parser(
        "extract",
        help="Write a translator's workspace: every entry with its original from your own copy",
    )
    extract.add_argument("target")
    extract.add_argument(
        "input", type=Path, help="Your game image, or your checkout of the decompilation"
    )
    extract.add_argument(
        "--out",
        type=Path,
        help="Workspace to write (default: <target>.workspace.json); it stays local",
    )
    extract.add_argument(
        "--translations",
        type=Path,
        help="Take the Arabic from this file or workspace instead of the shipped one",
    )
    extract.add_argument("--force", action="store_true", help="Replace an existing workspace")
    extract.set_defaults(handler=lambda args: _extract(registry, args))

    strip = commands.add_parser(
        "strip",
        help="Write a workspace's translations without the originals, ready to commit",
    )
    strip.add_argument("workspace", type=Path)
    strip.add_argument(
        "--out", type=Path, help="Translations file to write (default: <target>.json)"
    )
    strip.add_argument("--force", action="store_true", help="Replace an existing file")
    strip.set_defaults(handler=lambda args: _strip(registry, args))


def _unsupported(target_id: str, operation: str) -> ClassicRetroError:
    return ClassicRetroError(
        ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Target {target_id} has no {operation} operation"
    )


def _check_hooks(registry: TargetRegistry, target_ids: list[str]) -> int:
    targets = (
        [registry.get(target_id) for target_id in target_ids]
        if target_ids
        else [target for target in registry if target.check_hooks is not None]
    )
    results = {}
    for target in targets:
        if target.check_hooks is None:
            raise _unsupported(target.id, "check-hooks")
        results[target.id] = target.check_hooks()
    return print_json(results)


def _translations(target: LocalizationTarget, path: Path | None) -> TranslationSet | None:
    return None if path is None else load_translation_set(path, target.id)


def _check_translations(registry: TargetRegistry, args: argparse.Namespace) -> int:
    target = registry.get(args.target)
    if target.check_translations is None:
        raise _unsupported(target.id, "check-translations")
    if args.preview_dir is not None and args.font is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    translations = _translations(target, args.translations)
    report = target.check_translations(args.font, args.preview_dir, translations)
    if args.preview_dir is not None:
        missing = [name for name in target.previews if not (args.preview_dir / name).is_file()]
        if missing:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Target {target.id} did not write {', '.join(missing)}",
            )
    if translations is not None:
        report = {**report, "translations": str(args.translations)}
        if translations.is_workspace:
            report["glossary"] = glossary_report(translations)
    return print_json(report)


def _build(registry: TargetRegistry, args: argparse.Namespace) -> int:
    target = registry.get(args.target)
    if target.build is None:
        raise _unsupported(target.id, "build")
    translations = _translations(target, args.translations)
    report = target.build(
        args.rom.read_bytes(), args.font, args.out_dir, args.write_rom, translations
    )
    if translations is not None:
        report = {**report, "translations": str(args.translations)}
    base = report.get("base_sha256")
    reference = target.reference_for(base if isinstance(base, str) else None)
    return print_json(
        {
            **report,
            "target": target.id,
            "reference_patch_sha256": reference,
            "matches_reference": None if reference is None else report["patch_sha256"] == reference,
        }
    )


def _prepare(registry: TargetRegistry, args: argparse.Namespace) -> int:
    target = registry.get(args.target)
    if target.prepare is None:
        raise _unsupported(target.id, "prepare")
    translations = _translations(target, args.translations)
    return print_json(target.prepare(args.source, args.font, translations))


def _writable(out: Path, force: bool) -> Path:
    if out.exists() and not force:
        raise ClassicRetroError(
            ErrorCode.OUTPUT_EXISTS, f"{out} exists; pass --force to replace it"
        )
    return out


def _extract(registry: TargetRegistry, args: argparse.Namespace) -> int:
    target = registry.get(args.target)
    if target.extract is None:
        raise _unsupported(target.id, "extract")
    out = _writable(args.out or Path(f"{target.id}.workspace.json"), args.force)
    translations = _translations(target, args.translations) or builtin_translation_set(target.id)
    origin, originals = target.extract(args.input, translations)
    workspace = translations.with_sources(originals, origin)
    out.write_text(workspace.dumps(), encoding="utf-8")
    return print_json(
        {
            "target": target.id,
            "workspace": str(out),
            "from": origin,
            "entries": len(workspace.entries),
            "with_original": sum(entry.source is not None for entry in workspace.entries),
        }
    )


def _strip(registry: TargetRegistry, args: argparse.Namespace) -> int:
    workspace = load_translation_set(args.workspace)
    target = registry.get(workspace.target)
    translations = replace(
        workspace,
        entries=tuple(replace(entry, source=None) for entry in workspace.entries),
        workspace_from=None,
    )
    out = _writable(args.out or Path(f"{target.id}.json"), args.force)
    out.write_text(translations.dumps(), encoding="utf-8")
    return print_json(
        {"target": target.id, "translations": str(out), "entries": len(translations.entries)}
    )
