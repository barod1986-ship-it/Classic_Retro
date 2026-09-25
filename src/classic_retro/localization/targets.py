"""Localization targets: one supported game revision and how it is put into Arabic.

A target ties a game adapter (``classic_retro.games``) to its Arabic work: the
rendering strategies it uses, its documents, and the operations the toolkit
runs the same way for every target (``classic-retro targets ...``):

- ``check_hooks()``: re-assemble the hook code and compare it with the stored bytes;
- ``check_translations(font, preview_dir, translations)``: validate the script
  without the game image; with a font, lay out every string and write the
  target's ``previews`` into ``preview_dir``;
- ``build(rom, font, out_dir, rom_name, translations)``: build the patch from the
  user's image (a rom overlay);
- ``prepare(source, font, translations)``: patch the user's decompilation checkout
  (a source overlay);
- ``extract(input, translations)``: read the original of every entry from the
  user's own copy (the image, or the checkout), for a translator's workspace.

``translations`` is a ``TranslationSet`` to use instead of the target's shipped
``classic_retro/translations/<target>.json``, or None for the shipped one.

A target also keeps its own command group (``classic-retro fomt ...``) with any
command specific to it. Targets come from ``classic_retro.localization.builtin``
and, from other packages, the ``classic_retro.targets.v1`` entry point group.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.metadata import entry_points
from inspect import isclass
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.strategies import StrategyRegistry, build_strategy_registry
from classic_retro.localization.translations import TranslationSet

TARGET_ENTRY_POINT_GROUP = "classic_retro.targets.v1"
# How a target changes the game: a patch built from the user's image, or a
# patched source tree of a decompilation that builds the image.
KINDS = ("rom-overlay", "source-overlay")

HookCheck = Callable[[], dict[str, object]]
TranslationCheck = Callable[[Path | None, Path | None, TranslationSet | None], dict[str, object]]
Build = Callable[[bytes, Path, Path, str | None, TranslationSet | None], dict[str, object]]
Prepare = Callable[[Path, Path, TranslationSet | None], dict[str, object]]
# Where the originals come from (for the workspace), and each entry's original by id.
Extract = Callable[[Path, TranslationSet | None], tuple[str, dict[str, str]]]
RegisterCli = Callable[[argparse._SubParsersAction], None]


@dataclass(frozen=True, slots=True)
class LocalizationTarget:
    id: str
    game_id: str
    title: str
    platform_id: str
    kind: str
    strategies: tuple[str, ...]
    scope: str
    guide: str
    notes: str
    register_cli: RegisterCli
    check_hooks: HookCheck | None = None
    check_translations: TranslationCheck | None = None
    build: Build | None = None
    prepare: Prepare | None = None
    extract: Extract | None = None
    # Files ``check_translations`` writes into its preview folder when given a font.
    previews: tuple[str, ...] = ()
    # SHA-256 of the patch built from the pinned image with the reference font.
    reference_patch_sha256: str | None = None

    def operations(self) -> list[str]:
        names = {
            "check-hooks": self.check_hooks,
            "check-translations": self.check_translations,
            "build": self.build,
            "prepare": self.prepare,
            "extract": self.extract,
        }
        return [name for name, operation in names.items() if operation is not None]

    def describe(self) -> dict[str, object]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "title": self.title,
            "platform": self.platform_id,
            "kind": self.kind,
            "strategies": list(self.strategies),
            "scope": self.scope,
            "guide": self.guide,
            "notes": self.notes,
            "operations": self.operations(),
            "previews": list(self.previews),
            "reference_patch_sha256": self.reference_patch_sha256,
        }


class TargetRegistry:
    """Targets by id, in registration order, checked against the strategies."""

    def __init__(self, strategies: StrategyRegistry) -> None:
        self.strategies = strategies
        self._targets: dict[str, LocalizationTarget] = {}

    def register(self, target: LocalizationTarget) -> None:
        if not target.id:
            raise ClassicRetroError(ErrorCode.ADAPTER_TYPE_ERROR, "Target id cannot be empty")
        if target.id in self._targets:
            raise ClassicRetroError(
                ErrorCode.ADAPTER_ID_CONFLICT, f"Duplicate target id: {target.id}"
            )
        if target.kind not in KINDS:
            raise ClassicRetroError(
                ErrorCode.ADAPTER_TYPE_ERROR,
                f"Target {target.id}: kind must be one of {', '.join(KINDS)}",
            )
        if not target.strategies:
            raise ClassicRetroError(
                ErrorCode.ADAPTER_TYPE_ERROR, f"Target {target.id} names no rendering strategy"
            )
        for strategy in target.strategies:
            self.strategies.get(strategy)
        self._targets[target.id] = target

    def get(self, target_id: str) -> LocalizationTarget:
        if target_id in self._targets:
            return self._targets[target_id]
        for target in self._targets.values():
            if target.game_id == target_id:
                return target
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            f"Unknown localization target: {target_id} (known: {', '.join(self._targets)})",
        )

    def __iter__(self) -> Iterator[LocalizationTarget]:
        return iter(self._targets.values())

    def using(self, strategy_id: str) -> list[str]:
        return [target.id for target in self if strategy_id in target.strategies]

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group=TARGET_ENTRY_POINT_GROUP):
            try:
                loaded = entry_point.load()
                target = loaded() if isclass(loaded) or callable(loaded) else loaded
            except Exception as exc:
                raise ClassicRetroError(
                    ErrorCode.ADAPTER_LOAD_FAILED,
                    f"Failed to load {TARGET_ENTRY_POINT_GROUP}:{entry_point.name}: {exc}",
                ) from exc
            if not isinstance(target, LocalizationTarget):
                raise ClassicRetroError(
                    ErrorCode.ADAPTER_TYPE_ERROR,
                    f"{TARGET_ENTRY_POINT_GROUP}:{entry_point.name} did not provide "
                    "a LocalizationTarget",
                )
            self.register(target)


def build_target_registry(*, load_external: bool = True) -> TargetRegistry:
    from classic_retro.localization.builtin import builtin_targets

    registry = TargetRegistry(build_strategy_registry(load_external=load_external))
    for target in builtin_targets():
        registry.register(target)
    if load_external:
        registry.load_entry_points()
    return registry


def print_json(payload: object) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def preview_paths(font: Path | None, preview_dir: Path | None, *names: str) -> list[Path | None]:
    """Where previews go: ``preview_dir`` under ``names``; nowhere without a font."""
    if font is None or preview_dir is None:
        return [None] * len(names)
    preview_dir.mkdir(parents=True, exist_ok=True)
    return [preview_dir / name for name in names]


def write_build_report(out_dir: Path, report: dict[str, object]) -> dict[str, object]:
    """``build-report.json`` in ``out_dir``, as every build writes it."""
    (out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
