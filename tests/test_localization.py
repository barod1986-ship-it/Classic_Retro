from __future__ import annotations

import argparse
import importlib
import json
import re
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
from classic_retro.localization.translations import (
    GlossaryTerm,
    Translation,
    TranslationSet,
    load_translation_set,
)

REPO = Path(__file__).resolve().parents[1]
# Python 3.14 colours help output when the environment asks for colour.
COLOUR_CODES = re.compile(r"\x1b\[[0-9;]*m")
ROM_OVERLAYS = (
    "ff6a",
    "golden-sun",
    "fire-emblem",
    "pmd-red",
    "mmbn",
    "mlss",
    "fomt",
    "advance-wars",
)


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


def test_the_ten_reference_targets_keep_their_order_and_strategies():
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
        "advance-wars",
    ]
    assert registry.using("line-cells") == ["mmbn", "fomt"]
    assert registry.using("text-images") == ["fire-emblem"]
    assert described["fire-emblem"].strategies == ("glyph-font", "text-images")
    for target_id in ("firered", "minish-cap"):
        assert described[target_id].kind == "source-overlay"
        assert described[target_id].operations() == ["prepare", "extract"]
        assert described[target_id].previews == ()
    for target_id in ROM_OVERLAYS:
        target = described[target_id]
        assert target.kind == "rom-overlay" and target.platform_id == "gba"
        assert target.operations() == ["check-hooks", "check-translations", "build", "extract"]
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


def test_the_core_modules_of_every_strategy_exist():
    for strategy in build_strategy_registry(load_external=False):
        for module in strategy.core:
            importlib.import_module(module)


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


def _demo_translations(tmp_path, target: str = "demo", text: str = "مرحبا") -> Path:
    """A translations file of the demo target; the invented original names Mila."""
    translations = TranslationSet(
        target,
        "plain text",
        (Translation("greeting", text, context="an invented line"),),
        glossary=(GlossaryTerm("Mila", "ميلا"),),
    )
    path = tmp_path / f"{target}.json"
    path.write_text(translations.dumps(), encoding="utf-8")
    return path


def _demo_registry(tmp_path) -> tuple[TargetRegistry, list]:
    calls = []

    def check_translations(font, preview_dir, translations=None):
        (preview,) = preview_paths(font, preview_dir, "demo_preview.png")
        calls.append(("check-translations", font, preview, translations))
        if preview is not None:
            preview.write_bytes(b"demo")
        return {"strings": 2, "preview": None if preview is None else preview.name}

    def build(rom, font, out_dir, rom_name, translations=None):
        calls.append(("build", rom, font, out_dir, rom_name, translations))
        return {"patch_sha256": "ab" * 32}

    def prepare(source, font, translations=None):
        calls.append(("prepare", source, font, translations))
        return {"prepared": source.name}

    def extract(path, translations=None):
        calls.append(("extract", path, translations))
        return "an invented image", {"greeting": "Hello, Mila!"}

    registry = TargetRegistry(build_strategy_registry(load_external=False))
    registry.register(
        _target(
            check_hooks=lambda: {"match": True},
            check_translations=check_translations,
            build=build,
            extract=extract,
            previews=("demo_preview.png",),
            reference_patch_sha256="ab" * 32,
        )
    )
    registry.register(
        _target("bare", kind="source-overlay", strategies=("line-cells",), prepare=prepare)
    )
    registry.register(
        _target(
            "sloppy",
            check_translations=lambda font, preview_dir, translations=None: {},
            previews=("a.png",),
        )
    )
    return registry, calls


def test_targets_commands_run_any_target_by_id(tmp_path, capsys):
    registry, calls = _demo_registry(tmp_path)

    assert _run(registry, ["targets", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [target["id"] for target in listed] == ["demo", "bare", "sloppy"]
    assert listed[0]["operations"] == ["check-hooks", "check-translations", "build", "extract"]
    assert listed[0]["previews"] == ["demo_preview.png"]
    assert listed[1]["operations"] == ["prepare"]

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
    assert calls[-1] == (
        "check-translations",
        font,
        tmp_path / "previews" / "demo_preview.png",
        None,
    )
    assert _run(registry, ["targets", "check-translations", "demo"]) == 0
    assert json.loads(capsys.readouterr().out) == {"strings": 2, "preview": None}

    rom = tmp_path / "game.gba"
    rom.write_bytes(b"\x01\x02")
    argv = ["targets", "build", "demo-game", str(rom), "--font", str(font)]
    assert _run(registry, [*argv, "--out-dir", str(tmp_path / "out"), "--write-rom", "x.gba"]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["target"] == "demo" and built["matches_reference"] is True
    assert calls[-1] == ("build", b"\x01\x02", font, tmp_path / "out", "x.gba", None)

    assert _run(registry, ["targets", "prepare", "bare", str(tmp_path / "src"), "--font", "f"]) == 0
    assert json.loads(capsys.readouterr().out) == {"prepared": "src"}
    assert calls[-1] == ("prepare", tmp_path / "src", Path("f"), None)


def test_translations_files_reach_every_operation(tmp_path, capsys, monkeypatch):
    registry, calls = _demo_registry(tmp_path)
    monkeypatch.chdir(tmp_path)
    shipped = _demo_translations(tmp_path)

    assert (
        _run(registry, ["targets", "extract", "demo", "game.gba", "--translations", str(shipped)])
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "target": "demo",
        "workspace": "demo.workspace.json",
        "from": "an invented image",
        "entries": 1,
        "with_original": 1,
    }
    assert calls[-1][:2] == ("extract", Path("game.gba"))
    workspace = load_translation_set(tmp_path / "demo.workspace.json", "demo")
    assert workspace.is_workspace and workspace.workspace_from == "an invented image"
    assert workspace.entries[0].source == "Hello, Mila!" and workspace.entries[0].text == "مرحبا"

    argv = ["targets", "extract", "demo", "game.gba", "--translations", str(shipped)]
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, argv)
    assert error.value.code is ErrorCode.OUTPUT_EXISTS
    assert _run(registry, [*argv, "--force", "--out", "second.json"]) == 0
    capsys.readouterr()

    assert _run(registry, ["targets", "strip", "demo.workspace.json", "--out", "clean.json"]) == 0
    assert json.loads(capsys.readouterr().out)["entries"] == 1
    assert (tmp_path / "clean.json").read_text(encoding="utf-8") == shipped.read_text(
        encoding="utf-8"
    )
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, ["targets", "strip", "demo.workspace.json", "--out", "clean.json"])
    assert error.value.code is ErrorCode.OUTPUT_EXISTS

    # The workspace's original names Mila, but its Arabic does not use the glossary's spelling.
    check = ["targets", "check-translations", "demo", "--translations", "demo.workspace.json"]
    assert _run(registry, check) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["translations"] == "demo.workspace.json"
    assert report["glossary"] == [{"id": "greeting", "term": "Mila", "expected": "ميلا"}]
    assert calls[-1][3] == workspace

    rom = tmp_path / "game.gba"
    rom.write_bytes(b"\x01")
    build = ["targets", "build", "demo", str(rom), "--font", "f", "--out-dir", "out"]
    assert _run(registry, [*build, "--translations", str(shipped)]) == 0
    assert json.loads(capsys.readouterr().out)["translations"] == str(shipped)
    assert calls[-1][5].entries[0].text == "مرحبا"

    other = _demo_translations(tmp_path, target="bare")
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, [*build, "--translations", str(other)])
    assert error.value.code is ErrorCode.INVALID_TRANSLATION_DOCUMENT
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, ["targets", "extract", "demo", "game.gba", "--out", "third.json"])
    assert error.value.code is ErrorCode.INVALID_REFERENCE


def test_targets_commands_refuse_what_a_target_cannot_do(tmp_path):
    registry, _ = _demo_registry(tmp_path)
    for argv in (
        ["targets", "check-hooks", "bare"],
        ["targets", "check-translations", "bare"],
        ["targets", "build", "bare", str(tmp_path / "x"), "--font", "f", "--out-dir", "o"],
        ["targets", "prepare", "demo", str(tmp_path), "--font", "f"],
        ["targets", "extract", "bare", str(tmp_path / "x"), "--out", str(tmp_path / "w.json")],
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
        "advance-wars",
        "targets",
    ):
        with pytest.raises(SystemExit) as exit_:
            main([group, "--help"])
        assert exit_.value.code == 0
        usage = COLOUR_CODES.sub("", capsys.readouterr().out)
        assert usage.startswith(f"usage: classic-retro {group} ")

    assert main(["targets", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [target["id"] for target in listed][-1] == "advance-wars"
    assert main(["targets", "check-hooks", "not-a-target"]) == 2
    assert capsys.readouterr().err.startswith("INVALID_REFERENCE: Unknown localization target")
