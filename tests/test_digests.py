from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import PIL
import pytest
from PIL import Image, PngImagePlugin

from classic_retro.core.environment import library_versions
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization import digests as digests_module
from classic_retro.localization.commands import register_cli
from classic_retro.localization.digests import (
    PATH_KEYS,
    VOLATILE_KEYS,
    compare,
    digest_entry,
    load_expected,
    preview_digest,
    report_digest,
    save_expected,
)
from classic_retro.localization.strategies import build_strategy_registry
from classic_retro.localization.targets import (
    LocalizationTarget,
    TargetRegistry,
    build_target_registry,
    preview_paths,
)
from classic_retro.localization.translations import Translation, TranslationSet
from classic_retro.patching.outputs import base_report
from classic_retro.rebuild.bps import create_bps

# A 4x3 picture with a different colour in every pixel: any change shows.
PIXELS = [(x * 60, y * 90, 7) for y in range(3) for x in range(4)]
REPORT = {"strings": 2, "messages": ["مرحبا", "وداعا"], "lines_measured": True, "widest_line": 41}


def _png(
    path: Path, pixels: list, mode: str = "RGB", size: tuple[int, int] = (4, 3), **save
) -> Path:
    image = Image.new(mode, size)
    image.putdata(pixels)
    image.save(path, **save)
    return path


def test_library_versions_name_the_rasterization_stack():
    versions = library_versions()
    assert list(versions) == [
        "pillow",
        "freetype",
        "harfbuzz",
        "fonttools",
        "arabic_reshaper",
        "python_bidi",
        "jsonschema",
        "pycdlib",
        "python",
    ]
    assert all(isinstance(version, str) and version for version in versions.values())
    assert versions["pillow"] == PIL.__version__
    assert versions["python"] == platform.python_version()
    # The glyphs are drawn by FreeType: Pillow must have been built with it.
    assert versions["freetype"][0].isdigit()
    assert library_versions() == versions


def test_build_reports_record_the_library_versions():
    rom, output = b"\x00" * 16, b"\x01" + b"\x00" * 15
    report = base_report("Test Game", rom, output, create_bps(rom, output))
    assert report["raster"] == library_versions()
    assert report["patch_bytes"] > 0 and report["target_bytes"] == 16


def test_report_digest_ignores_volatile_and_path_keys_and_key_order():
    digest = report_digest(REPORT)
    canonical = json.dumps(REPORT, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    reordered = dict(reversed(list(REPORT.items())))
    assert list(reordered) != list(REPORT) and report_digest(reordered) == digest
    assert VOLATILE_KEYS == {"translations", "raster", "digests"}
    assert PATH_KEYS == {
        "outputs",
        "workspace",
        "source",
        "rom",
        "font_png",
        "widths",
        "font_binary",
    }
    noisy = {
        **REPORT,
        "translations": "demo.workspace.json",
        "raster": library_versions(),
        "digests": {"outcome": "match"},
        "outputs": {"patch": "/somewhere/demo.bps"},
        "workspace": "demo.workspace.json",
        "source": "/somewhere/upstream",
        "rom": "/somewhere/demo.gba",
        "font_png": "/somewhere/font.png",
        "widths": "/somewhere/widths.bin",
        "font_binary": "/somewhere/font.bin",
    }
    assert report_digest(noisy) == digest
    assert report_digest({**REPORT, "strings": 3}) != digest
    assert report_digest({**REPORT, "messages": ["مرحبا", "وداعاً"]}) != digest
    assert (
        report_digest({key: value for key, value in REPORT.items() if key != "strings"}) != digest
    )


def test_preview_digest_is_of_the_decoded_pixels_not_the_file(tmp_path):
    comment = PngImagePlugin.PngInfo()
    comment.add_text("Comment", "saved by another encoder")
    stored = _png(tmp_path / "stored.png", PIXELS, compress_level=0)
    packed = _png(tmp_path / "packed.png", PIXELS, compress_level=9, optimize=True, pnginfo=comment)
    assert stored.read_bytes() != packed.read_bytes()
    digest = preview_digest(stored)
    assert len(digest) == 64 and preview_digest(packed) == digest
    header = b"RGB:4x3:"
    with Image.open(stored) as image:
        assert digest == hashlib.sha256(header + image.tobytes()).hexdigest()

    changed = [*PIXELS]
    changed[5] = (changed[5][0], changed[5][1], 8)
    assert preview_digest(_png(tmp_path / "changed.png", changed)) != digest
    # The same bytes in another shape, or another mode, are another picture.
    blank = _png(tmp_path / "blank.png", [0] * 12, mode="L")
    turned = _png(tmp_path / "turned.png", [0] * 12, mode="L", size=(3, 4))
    assert preview_digest(blank) != preview_digest(turned)
    assert preview_digest(_png(tmp_path / "rgb.png", [(0, 0, 0)] * 12)) != preview_digest(blank)


def test_compare_reports_a_missing_entry_and_every_difference_by_name(tmp_path):
    previews = tmp_path / "previews"
    previews.mkdir()
    _png(previews / "a.png", PIXELS)
    _png(previews / "b.png", PIXELS)
    names = ("a.png", "b.png")

    assert compare("demo", REPORT, previews, names, expected={}) == [
        "demo: no digest recorded (record it with --update-digests)"
    ]
    entry = digest_entry(REPORT, previews, names)
    assert set(entry) == {"report", "previews", "generated_with"}
    assert entry["report"] == report_digest(REPORT)
    assert entry["previews"] == {name: preview_digest(previews / name) for name in names}
    assert entry["generated_with"] == library_versions()
    expected = {"demo": entry}
    assert compare("demo", REPORT, previews, names, expected=expected) == []
    volatile = {**REPORT, "raster": {"pillow": "0.0.0"}, "translations": "x.json"}
    assert compare("demo", volatile, previews, names, expected=expected) == []

    changed_report = {**REPORT, "strings": 3}
    assert compare("demo", changed_report, previews, names, expected=expected) == [
        f"report: recorded {entry['report']}, now {report_digest(changed_report)}"
    ]

    changed = [*PIXELS]
    changed[0] = (1, 2, 3)
    _png(previews / "b.png", changed)
    differences = compare("demo", REPORT, previews, names, expected=expected)
    assert differences == [
        f"preview b.png: recorded {entry['previews']['b.png']}, "
        f"now {preview_digest(previews / 'b.png')}"
    ]
    _png(previews / "b.png", PIXELS)

    # A preview the record lacks, one the target no longer writes, one not written.
    differences = compare("demo", REPORT, previews, ("a.png", "c.png"), expected=expected)
    assert differences == [
        "preview c.png: not written",
        "preview b.png: recorded, but the target no longer writes it",
    ]
    _png(previews / "c.png", PIXELS)
    assert compare("demo", REPORT, previews, ("a.png", "c.png"), expected=expected) == [
        "preview c.png: no digest recorded",
        "preview b.png: recorded, but the target no longer writes it",
    ]

    # When something differs and the libraries moved, the last line says which.
    old = {"demo": {**entry, "generated_with": {**entry["generated_with"], "freetype": "2.0.0"}}}
    assert compare("demo", REPORT, previews, names, expected=old) == []
    differences = compare("demo", changed_report, previews, names, expected=old)
    assert differences[-1] == (
        f"libraries changed since the record: freetype 2.0.0 -> {library_versions()['freetype']}"
    )
    assert len(differences) == 2


def test_expected_digests_round_trip_with_sorted_keys_and_a_trailing_newline(tmp_path):
    path = tmp_path / "digests.json"
    digests = {
        "zeta": {"report": "b" * 64, "previews": {"z.png": "c" * 64}, "generated_with": {}},
        "alpha": {"report": "a" * 64, "previews": {}, "generated_with": {"pillow": "1"}},
    }
    save_expected(digests, path)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and text.index('"alpha"') < text.index('"zeta"')
    assert load_expected(path) == digests
    assert json.loads(text) == digests


def test_the_shipped_digests_name_checked_targets_and_their_previews():
    """Every recorded target exists and has the previews it records; the file is canonical."""
    shipped = load_expected()
    checked = {
        target.id: target
        for target in build_target_registry(load_external=False)
        if target.check_translations is not None
    }
    assert set(shipped) <= set(checked)
    for target_id, entry in shipped.items():
        assert set(entry) == {"report", "previews", "generated_with"}, target_id
        assert len(entry["report"]) == 64, target_id
        assert set(entry["previews"]) == set(checked[target_id].previews), target_id
        assert all(len(digest) == 64 for digest in entry["previews"].values()), target_id
        assert set(entry["generated_with"]) == set(library_versions()), target_id
    text = digests_module.DIGESTS_PATH.read_text(encoding="utf-8")
    assert text == json.dumps(shipped, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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


def _demo_registry() -> tuple[TargetRegistry, dict]:
    """A target whose report and preview the test can change between runs."""
    state = {"strings": 2, "pixels": [*PIXELS]}

    def check_translations(font, preview_dir, translations=None):
        (preview,) = preview_paths(font, preview_dir, "demo_preview.png")
        if preview is not None:
            _png(preview, state["pixels"])
        return {"strings": state["strings"], "lines_measured": font is not None}

    def prepare(source, font, translations=None):
        return {"prepared": source.name}

    registry = TargetRegistry(build_strategy_registry(load_external=False))
    registry.register(
        _target(check_translations=check_translations, previews=("demo_preview.png",))
    )
    registry.register(
        _target("bare", kind="source-overlay", strategies=("line-cells",), prepare=prepare)
    )
    return registry, state


def _run(registry: TargetRegistry, argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    register_cli(parser.add_subparsers(dest="command", required=True), registry)
    args = parser.parse_args(argv)
    return args.handler(args)


def _without(report: dict, *keys: str) -> dict:
    return {key: value for key, value in report.items() if key not in keys}


def test_check_translations_records_and_checks_digests(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(digests_module, "DIGESTS_PATH", tmp_path / "digests.json")
    save_expected({})
    registry, state = _demo_registry()
    previews = tmp_path / "previews"
    argv = ["targets", "check-translations", "demo", "--font", "f.ttf", "--preview-dir"]
    argv.append(str(previews))

    assert _run(registry, argv) == 0
    plain = json.loads(capsys.readouterr().out)
    assert plain["raster"] == library_versions() and "digests" not in plain
    assert _without(plain, "raster") == {"strings": 2, "lines_measured": True}

    with pytest.raises(ClassicRetroError) as error:
        _run(registry, [*argv, "--check-digests"])
    assert error.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    assert str(error.value) == (
        "Target demo differs from its recorded digests: "
        "demo: no digest recorded (record it with --update-digests)"
    )

    assert _run(registry, [*argv, "--update-digests"]) == 0
    recorded = json.loads(capsys.readouterr().out)
    preview = preview_digest(previews / "demo_preview.png")
    assert recorded["digests"] == {
        "outcome": "recorded",
        "report": report_digest(plain),
        "previews": {"demo_preview.png": preview},
    }
    assert _without(recorded, "digests") == plain
    assert load_expected() == {
        "demo": {
            "report": report_digest(plain),
            "previews": {"demo_preview.png": preview},
            "generated_with": library_versions(),
        }
    }
    assert (tmp_path / "digests.json").read_text(encoding="utf-8").endswith("\n")

    assert _run(registry, [*argv, "--check-digests"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["digests"] == {**recorded["digests"], "outcome": "match"}
    assert _without(checked, "digests") == plain

    state["pixels"][0] = (1, 2, 3)
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, [*argv, "--check-digests"])
    assert error.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    assert str(error.value).startswith(
        f"Target demo differs from its recorded digests: preview demo_preview.png: recorded {preview}, now "
    )
    state["pixels"][0] = PIXELS[0]
    state["strings"] = 3
    with pytest.raises(ClassicRetroError) as error:
        _run(registry, [*argv, "--check-digests"])
    assert str(error.value).startswith(
        f"Target demo differs from its recorded digests: report: recorded {report_digest(plain)}, now "
    )
    # A second record replaces the entry and keeps the others.
    expected = load_expected()
    expected["other"] = {"report": "0" * 64, "previews": {}, "generated_with": {}}
    save_expected(expected)
    assert _run(registry, [*argv, "--update-digests"]) == 0
    capsys.readouterr()
    assert set(load_expected()) == {"demo", "other"}
    assert load_expected()["demo"]["report"] == report_digest({**plain, "strings": 3})
    assert _run(registry, [*argv, "--check-digests"]) == 0


def test_digest_flags_need_a_font_a_preview_folder_and_the_shipped_translations(tmp_path):
    registry, _ = _demo_registry()
    for extra in (
        ["--check-digests"],
        ["--update-digests"],
        ["--font", "f.ttf", "--check-digests"],
    ):
        with pytest.raises(ClassicRetroError) as error:
            _run(registry, ["targets", "check-translations", "demo", *extra])
        assert error.value.code is ErrorCode.FONT_BUILD_FAILED
        assert (
            str(error.value) == "--check-digests and --update-digests need --font and --preview-dir"
        )
    translations = tmp_path / "demo.json"
    translations.write_text(
        TranslationSet("demo", "plain text", (Translation("greeting", "مرحبا"),)).dumps(),
        encoding="utf-8",
    )
    argv = ["targets", "check-translations", "demo", "--font", "f.ttf", "--preview-dir"]
    argv += [str(tmp_path / "previews"), "--translations", str(translations)]
    for flag in ("--check-digests", "--update-digests"):
        with pytest.raises(ClassicRetroError) as error:
            _run(registry, [*argv, flag])
        assert error.value.code is ErrorCode.INVALID_REFERENCE
        assert "do not take --translations" in str(error.value)
    with pytest.raises(SystemExit):
        _run(registry, [*argv[:-2], "--check-digests", "--update-digests"])
    assert not (tmp_path / "previews").exists()


def test_prepare_reports_carry_the_library_versions(tmp_path, capsys):
    registry, _ = _demo_registry()
    assert _run(registry, ["targets", "prepare", "bare", str(tmp_path / "src"), "--font", "f"]) == 0
    assert json.loads(capsys.readouterr().out) == {"prepared": "src", "raster": library_versions()}
