from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization import strategies as strategies_module
from classic_retro.localization import targets as targets_module
from classic_retro.localization.commands import register_cli
from classic_retro.localization.strategies import (
    RenderingStrategy,
    StrategyRegistry,
    build_strategy_registry,
)
from classic_retro.localization.targets import (
    LocalizationTarget,
    TargetRegistry,
    build_target_registry,
    preview_paths,
    write_build_report,
)

REPO = Path(__file__).resolve().parents[1]
ROM_OVERLAYS = ("ff6a", "golden-sun", "fire-emblem", "pmd-red", "mmbn", "mlss", "fomt")


def _no_cli(_: argparse._SubParsersAction) -> None:
    return None


def _target(target_id: str = "demo", **changes) -> LocalizationTarget:
    fields = {
        "id": target_id,
        "game_id": f"{target_id}-game",
        "title": "Demo Game",
        "platform_id": "gba",
        "kind": "rom-overlay",
        "strategies": ("glyph-font",),
        "scope": "a demo",
        "guide": "docs/DEMO.md",
        "notes": "docs/DEMO_NOTES.md",
        "register_cli": _no_cli,
    }
    return LocalizationTarget(**{**fields, **changes})


def _strategy(strategy_id: str = "texture-font", **changes) -> RenderingStrategy:
    fields = {
        "id": strategy_id,
        "title": "Texture font",
        "summary": "An invented strategy for a platform the toolkit does not cover yet.",
        "engine_needs": ("a texture the text is drawn from",),
        "core": (),
        "tradeoffs": ("none known",),
    }
    return RenderingStrategy(**{**fields, **changes})


class _EntryPoint:
    def __init__(self, name, loaded):
        self.name = name
        self._loaded = loaded

    def load(self):
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


def test_the_nine_reference_targets_keep_their_order_and_strategies():
    registry = build_target_registry(load_external=False)
    described = {target.id: target for target in registry}
    assert list(described) == [
        "firered",
        "minish-cap",
        "ff6a",
        "golden-sun",
        "fire-emblem",
        "pmd-red",
        "mmbn",
        "mlss",
        "fomt",
    ]
    assert registry.using("line-cells") == ["mmbn", "fomt"]
    assert registry.using("text-images") == ["fire-emblem"]
    assert described["fire-emblem"].strategies == ("glyph-font", "text-images")
    for target_id in ("firered", "minish-cap"):
        assert described[target_id].kind == "source-overlay"
        assert described[target_id].operations() == [] and described[target_id].previews == ()
    for target_id in ROM_OVERLAYS:
        target = described[target_id]
        assert target.kind == "rom-overlay" and target.platform_id == "gba"
        assert target.operations() == ["check-hooks", "check-translations", "build"]
        assert target.previews and all(name.endswith(".png") for name in target.previews)
        reference = target.reference_patch_sha256
        assert reference is None if target_id == "ff6a" else len(reference) == 64
    adapters = build_registry(load_external=False)
    for target in registry:
        assert (REPO / target.guide).is_file(), target.guide
        assert (REPO / target.notes).is_file(), target.notes
        assert adapters.games[target.game_id].platform_id == target.platform_id
    assert registry.get("harvest-moon-fomt-usa") is described["fomt"]


def test_the_proven_strategies_are_a_starting_set():
    registry = build_strategy_registry(load_external=False)
    assert [strategy.id for strategy in registry] == ["glyph-font", "line-cells", "text-images"]
    assert all(strategy.status == "proven" for strategy in registry)

    registry.register(_strategy())
    assert "texture-font" in registry
    assert registry.get("texture-font").status == "experimental"
    targets = TargetRegistry(registry)
    targets.register(_target(strategies=("texture-font",)))
    assert targets.using("texture-font") == ["demo"]


def test_strategy_registry_checks_what_it_is_given():
    registry = StrategyRegistry()
    registry.register(_strategy())
    with pytest.raises(ClassicRetroError) as error:
        registry.register(_strategy())
    assert error.value.code is ErrorCode.ADAPTER_ID_CONFLICT
    with pytest.raises(ClassicRetroError) as error:
        registry.register(_strategy("tried", status="maybe"))
    assert error.value.code is ErrorCode.ADAPTER_TYPE_ERROR
    with pytest.raises(ClassicRetroError) as error:
        registry.register(_strategy(""))
    assert error.value.code is ErrorCode.ADAPTER_TYPE_ERROR
    with pytest.raises(ClassicRetroError) as error:
        registry.get("unknown")
    assert error.value.code is ErrorCode.INVALID_REFERENCE


def test_target_registry_checks_what_it_is_given():
    registry = TargetRegistry(build_strategy_registry(load_external=False))
    registry.register(_target())
    cases = {
        ErrorCode.ADAPTER_ID_CONFLICT: _target(),
        ErrorCode.ADAPTER_TYPE_ERROR: _target("other", kind="save-editor"),
        ErrorCode.INVALID_REFERENCE: _target("third", strategies=("unknown",)),
    }
    for code, target in cases.items():
        with pytest.raises(ClassicRetroError) as error:
            registry.register(target)
        assert error.value.code is code
    with pytest.raises(ClassicRetroError) as error:
        registry.register(_target("fourth", strategies=()))
    assert error.value.code is ErrorCode.ADAPTER_TYPE_ERROR
    with pytest.raises(ClassicRetroError) as error:
        registry.get("missing")
    assert error.value.code is ErrorCode.INVALID_REFERENCE
    assert "known: demo" in str(error.value)
    assert registry.get("demo-game").id == "demo"


def test_entry_points_add_strategies_and_targets(monkeypatch):
    def fake_entry_points(group):
        return {
            strategies_module.STRATEGY_ENTRY_POINT_GROUP: [_EntryPoint("texture", _strategy)],
            targets_module.TARGET_ENTRY_POINT_GROUP: [
                _EntryPoint("demo", _target(strategies=("texture-font",)))
            ],
        }[group]

    monkeypatch.setattr(strategies_module, "entry_points", fake_entry_points)
    monkeypatch.setattr(targets_module, "entry_points", fake_entry_points)
    registry = build_target_registry()
    assert registry.get("demo").strategies == ("texture-font",)
    assert "texture-font" in registry.strategies


@pytest.mark.parametrize(
    ("loaded", "code"),
    [
        (RuntimeError("broken plugin"), ErrorCode.ADAPTER_LOAD_FAILED),
        (object(), ErrorCode.ADAPTER_TYPE_ERROR),
    ],
)
def test_entry_points_that_provide_the_wrong_thing_are_refused(monkeypatch, loaded, code):
    monkeypatch.setattr(
        strategies_module, "entry_points", lambda group: [_EntryPoint("bad", loaded)]
    )
    with pytest.raises(ClassicRetroError) as error:
        build_strategy_registry()
    assert error.value.code is code
    monkeypatch.setattr(strategies_module, "entry_points", lambda group: [])
    monkeypatch.setattr(targets_module, "entry_points", lambda group: [_EntryPoint("bad", loaded)])
    with pytest.raises(ClassicRetroError) as error:
        build_target_registry()
    assert error.value.code is code


def test_preview_paths_and_build_report(tmp_path):
    assert preview_paths(None, tmp_path / "p", "a.png") == [None]
    assert preview_paths(tmp_path / "font.ttf", None, "a.png", "b.png") == [None, None]
    paths = preview_paths(tmp_path / "font.ttf", tmp_path / "p", "a.png", "b.png")
    assert paths == [tmp_path / "p" / "a.png", tmp_path / "p" / "b.png"]
    assert (tmp_path / "p").is_dir()
    report = {"game": "Demo", "outputs": {"patch": "ع"}}
    assert write_build_report(tmp_path, report) is report
    text = (tmp_path / "build-report.json").read_text(encoding="utf-8")
    assert text.endswith("\n") and json.loads(text) == report and "ع" in text


def _run(registry: TargetRegistry, argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    register_cli(parser.add_subparsers(dest="command", required=True), registry)
    args = parser.parse_args(argv)
    return args.handler(args)


def _demo_registry(tmp_path) -> tuple[TargetRegistry, list]:
    calls = []

    def check_translations(font, preview_dir):
        (preview,) = preview_paths(font, preview_dir, "demo_preview.png")
        calls.append(("check-translations", font, preview))
        if preview is not None:
            preview.write_bytes(b"demo")
        return {"strings": 2, "preview": None if preview is None else preview.name}

    def build(rom, font, out_dir, rom_name):
        calls.append(("build", rom, font, out_dir, rom_name))
        return {"patch_sha256": "ab" * 32}

    registry = TargetRegistry(build_strategy_registry(load_external=False))
    registry.register(
        _target(
            check_hooks=lambda: {"match": True},
            check_translations=check_translations,
            build=build,
            previews=("demo_preview.png",),
            reference_patch_sha256="ab" * 32,
        )
    )
    registry.register(_target("bare", kind="source-overlay", strategies=("line-cells",)))
    registry.register(
        _target("sloppy", check_translations=lambda font, preview_dir: {}, previews=("a.png",))
    )
    return registry, calls


def test_targets_commands_run_any_target_by_id(tmp_path, capsys):
    registry, calls = _demo_registry(tmp_path)

    assert _run(registry, ["targets", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [target["id"] for target in listed] == ["demo", "bare", "sloppy"]
    assert listed[0]["operations"] == ["check-hooks", "check-translations", "build"]
    assert listed[0]["previews"] == ["demo_preview.png"]
    assert listed[1]["operations"] == []

    assert _run(registry, ["targets", "strategies"]) == 0
    strategies = {s["id"]: s["targets"] for s in json.loads(capsys.readouterr().out)}
    assert strategies == {
        "glyph-font": ["demo", "sloppy"],
        "line-cells": ["bare"],
        "text-images": [],
    }

    assert _run(registry, ["targets", "check-hooks"]) == 0
    assert json.loads(capsys.readouterr().out) == {"demo": {"match": True}}

    font = tmp_path / "font.ttf"
    argv = ["targets", "check-translations", "demo", "--font", str(font)]
    assert _run(registry, [*argv, "--preview-dir", str(tmp_path / "previews")]) == 0
    assert json.loads(capsys.readouterr().out) == {"strings": 2, "preview": "demo_preview.png"}
    assert calls[-1] == ("check-translations", font, tmp_path / "previews" / "demo_preview.png")
    assert _run(registry, ["targets", "check-translations", "demo"]) == 0
    assert json.loads(capsys.readouterr().out) == {"strings": 2, "preview": None}

    rom = tmp_path / "game.gba"
    rom.write_bytes(b"\x01\x02")
    argv = ["targets", "build", "demo-game", str(rom), "--font", str(font)]
    assert _run(registry, [*argv, "--out-dir", str(tmp_path / "out"), "--write-rom", "x.gba"]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["target"] == "demo" and built["matches_reference"] is True
    assert calls[-1] == ("build", b"\x01\x02", font, tmp_path / "out", "x.gba")


def test_targets_commands_refuse_what_a_target_cannot_do(tmp_path):
    registry, _ = _demo_registry(tmp_path)
    for argv in (
        ["targets", "check-hooks", "bare"],
        ["targets", "check-translations", "bare"],
        ["targets", "build", "bare", str(tmp_path / "x"), "--font", "f", "--out-dir", "o"],
    ):
        with pytest.raises(ClassicRetroError) as error:
            _run(registry, argv)
        assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, ["targets", "check-translations", "demo", "--preview-dir", str(tmp_path)])
    assert str(error.value) == "A preview needs --font"
    argv = ["targets", "check-translations", "sloppy", "--font", "f"]
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, [*argv, "--preview-dir", str(tmp_path / "p")])
    assert error.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    assert str(error.value) == "Target sloppy did not write a.png"
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, ["targets", "check-hooks", "nothing"])
    assert error.value.code is ErrorCode.INVALID_REFERENCE


def test_the_cli_keeps_every_command_group_and_adds_targets(capsys):
    for group in (
        "pokemon-gen3",
        "tmc",
        "ff6a",
        "golden-sun",
        "fire-emblem",
        "pmd",
        "mmbn",
        "mlss",
        "fomt",
        "targets",
    ):
        with pytest.raises(SystemExit) as exit_:
            main([group, "--help"])
        assert exit_.value.code == 0
        assert capsys.readouterr().out.startswith(f"usage: classic-retro {group} ")

    assert main(["targets", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [target["id"] for target in listed][-1] == "fomt"
    assert main(["targets", "check-hooks", "not-a-target"]) == 2
    assert capsys.readouterr().err.startswith("INVALID_REFERENCE: Unknown localization target")
