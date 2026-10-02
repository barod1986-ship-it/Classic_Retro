"""``classic-retro targets``: what every localization target runs the same way.

These commands take a target id, so a guide, a script or a CI matrix runs any
target without knowing its module. A target's own command group holds only
the tools of its engine (``encode-arabic``, ``source-check``).
``--translations`` gives any of them a translations file or workspace
(``classic_retro.localization.translations``) instead of the shipped one.
``check-entries`` lists every entry of a file that a target's check refuses
(``classic_retro.localization.entries``); ``split`` and ``merge`` cut a file into
batches and put them back (``classic_retro.localization.batches``).

Every report that draws glyphs carries ``raster``, the library versions it
was made with (``classic_retro.core.environment``); ``check-translations``
compares or records digests of its output (``--check-digests``,
``--update-digests``; ``classic_retro.localization.digests``).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from classic_retro.core.environment import library_versions
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.batches import merge_translations, split_translations
from classic_retro.localization.digests import compare, digest_entry, load_expected, save_expected
from classic_retro.localization.entries import entry_report, load_batch
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
    digests = check.add_mutually_exclusive_group()
    digests.add_argument(
        "--check-digests",
        action="store_true",
        help="With --font and --preview-dir: compare the report and previews with the "
        "recorded digests, and fail on any difference",
    )
    digests.add_argument(
        "--update-digests",
        action="store_true",
        help="With --font and --preview-dir: record the report's and previews' digests",
    )
    check.set_defaults(handler=lambda args: _check_translations(registry, args))

    entries = commands.add_parser(
        "check-entries",
        help="List every entry of a translations file, workspace or batch that the target's "
        "check refuses, and why, in one run",
    )
    entries.add_argument("target")
    entries.add_argument("translations", type=Path, help="The file to check; it may hold a batch")
    entries.add_argument("--font", type=Path, help="Arabic TTF/OTF: lay every line out too")
    entries.add_argument(
        "--baseline",
        type=Path,
        help="Complete translations that pass the check (default: the shipped ones); an "
        "entry the checked file lacks takes its text",
    )
    entries.add_argument(
        "--entries",
        nargs="+",
        metavar="ID",
        default=(),
        help="Check only these entries of the file (shell patterns: 'guardia.5*')",
    )
    entries.add_argument(
        "--max-runs",
        type=int,
        default=1000,
        help="Stop the search after this many runs of the target's check (default: 1000)",
    )
    entries.set_defaults(handler=lambda args: _check_entries(registry, args))

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

    split = commands.add_parser(
        "split",
        help="Cut a translations file or workspace into batches of a few entries each",
    )
    split.add_argument("translations", type=Path)
    split.add_argument("--size", type=int, default=20, help="Entries a batch (default: 20)")
    split.add_argument("--out-dir", type=Path, required=True)
    split.add_argument(
        "--entries",
        nargs="+",
        metavar="ID",
        default=(),
        help="Only these entries (shell patterns: 'guardia.*')",
    )
    split.add_argument("--force", action="store_true", help="Replace existing batch files")
    split.set_defaults(handler=lambda args: _split(registry, args))

    merge = commands.add_parser(
        "merge",
        help="Put the text of batches back into their translations file or workspace",
    )
    merge.add_argument("translations", type=Path)
    merge.add_argument("batches", type=Path, nargs="+")
    merge.add_argument("--out", type=Path, required=True, help="The merged file to write")
    merge.add_argument("--force", action="store_true", help="Replace an existing file")
    merge.set_defaults(handler=lambda args: _merge(registry, args))

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
    digests = args.check_digests or args.update_digests
    if digests and (args.font is None or args.preview_dir is None):
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            "--check-digests and --update-digests need --font and --preview-dir",
        )
    if digests and args.translations is not None:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            "The digests are those of the shipped translations: "
            "--check-digests and --update-digests do not take --translations",
        )
    translations = _translations(target, args.translations)
    report = target.check_translations(args.font, args.preview_dir, translations)
    if args.preview_dir is not None:
        missing = [name for name in target.previews if not (args.preview_dir / name).is_file()]
        if missing:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Target {target.id} did not write {', '.join(missing)}",
            )
    report = {**report, "raster": library_versions()}
    if translations is not None:
        report["translations"] = str(args.translations)
        if translations.is_workspace:
            report["glossary"] = glossary_report(translations)
    if digests:
        report["digests"] = _digests(target, report, args)
    return print_json(report)


def _check_entries(registry: TargetRegistry, args: argparse.Namespace) -> int:
    """Every refused entry and its reason; exit 1 when there is one (``entries``)."""
    target = registry.get(args.target)
    if target.check_translations is None:
        raise _unsupported(target.id, "check-entries")
    if args.max_runs < 1:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "--max-runs must be at least 1")
    baseline = (
        builtin_translation_set(target.id)
        if args.baseline is None
        else load_translation_set(args.baseline, target.id)
    )
    batch = load_batch(args.translations, target.id, baseline, args.entries)
    report = entry_report(target.check_translations, batch, args.font, max_runs=args.max_runs)
    print_json(
        {
            "target": target.id,
            "translations": str(args.translations),
            "baseline": "shipped" if args.baseline is None else str(args.baseline),
            **report,
        }
    )
    return 0 if report["ok"] else 1


def _digests(
    target: LocalizationTarget, report: dict[str, object], args: argparse.Namespace
) -> dict[str, object]:
    """Record the report's digests, or compare them: the outcome, for the report.

    Neither changes the rest of the report. A comparison that finds a
    difference fails the command, listing every difference.
    """
    if args.update_digests:
        entry = digest_entry(report, args.preview_dir, target.previews)
        expected = load_expected()
        expected[target.id] = entry
        save_expected(expected)
        outcome = "recorded"
    else:
        differences = compare(target.id, report, args.preview_dir, target.previews)
        if differences:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Target {target.id} differs from its recorded digests: " + "; ".join(differences),
            )
        entry = digest_entry(report, args.preview_dir, target.previews)
        outcome = "match"
    return {"outcome": outcome, "report": entry["report"], "previews": entry["previews"]}


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
    report = target.prepare(args.source, args.font, translations)
    return print_json({**report, "raster": library_versions()})


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


def _split(registry: TargetRegistry, args: argparse.Namespace) -> int:
    translations = load_translation_set(args.translations)
    target = registry.get(translations.target)
    batches = split_translations(translations, args.size, args.entries)
    width = max(3, len(str(len(batches))))
    paths = [
        _writable(args.out_dir / f"{target.id}.batch-{number:0{width}d}.json", args.force)
        for number in range(1, len(batches) + 1)
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for path, batch in zip(paths, batches, strict=True):
        path.write_text(batch.dumps(), encoding="utf-8")
    return print_json(
        {
            "target": target.id,
            "batches": [
                {"file": str(path), "entries": len(batch.entries), "glossary": len(batch.glossary)}
                for path, batch in zip(paths, batches, strict=True)
            ],
            "entries": sum(len(batch.entries) for batch in batches),
            "workspace": translations.is_workspace,
        }
    )


def _merge(registry: TargetRegistry, args: argparse.Namespace) -> int:
    translations = load_translation_set(args.translations)
    target = registry.get(translations.target)
    batches = [load_translation_set(path, target.id) for path in args.batches]
    merged, report = merge_translations(translations, batches)
    out = _writable(args.out, args.force)
    out.write_text(merged.dumps(), encoding="utf-8")
    return print_json({"target": target.id, "translations": str(out), **report})


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
