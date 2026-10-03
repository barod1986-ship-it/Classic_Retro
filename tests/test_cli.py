from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from classic_retro.cli import main
from classic_retro.rebuild.bps import BPS_MAGIC

SRC = Path(__file__).resolve().parents[1] / "src"


def test_cli_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_cli_fingerprint(tmp_path, capsys):
    sample = tmp_path / "sample.rom"
    sample.write_bytes(b"abc")

    assert main(["fingerprint", str(sample)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["name"] == "sample.rom"
    assert output["size"] == 3
    assert len(output["sha256"]) == 64


def test_cli_media_inspect(tmp_path, capsys):
    sample = tmp_path / "sample.rom"
    sample.write_bytes(b"abc")

    assert main(["media", "inspect", str(sample)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["kind"] == "single-file"
    assert output["members"][0]["name"] == "sample.rom"
    assert len(output["identity_sha256"]) == 64


def test_cli_check_translations_records_the_library_versions(capsys):
    assert main(["targets", "check-translations", "ff6a"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["raster"]["pillow"] and report["raster"]["freetype"]
    assert "digests" not in report


def test_cli_digest_flags_need_a_font_and_a_preview_folder(capsys):
    assert main(["targets", "check-translations", "ff6a", "--check-digests"]) == 2
    assert capsys.readouterr().err.startswith(
        "FONT_BUILD_FAILED: --check-digests and --update-digests need --font and --preview-dir"
    )


@pytest.mark.parametrize("name", ["لعبة.rom", "🎮.rom"])
def test_cli_fingerprint_escapes_a_name_the_console_cannot_show(tmp_path, name):
    # A cp1252 console cannot show an Arabic file name: the JSON then carries it
    # as \uXXXX escapes, which read back as the same name, instead of a traceback.
    # A character beyond the BMP (the emoji) becomes JSON's surrogate pair.
    sample = tmp_path / name
    sample.write_bytes(b"abc")
    path = os.pathsep.join(filter(None, [str(SRC), os.environ.get("PYTHONPATH")]))
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONPATH": path}
    result = subprocess.run(
        [sys.executable, "-m", "classic_retro", "fingerprint", str(sample)],
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("cp1252", "replace")
    assert json.loads(result.stdout.decode("cp1252"))["name"] == name


# ---------------------------------------------------------------------------
# The rebuild commands write where they are told; the only files they refuse to
# replace are their own inputs and, for bps-create, a file that is not a patch.


def _images(tmp_path: Path) -> tuple[Path, Path, Path]:
    """An original, a modified image and the patch between them."""
    source = tmp_path / "orig.z64"
    source.write_bytes(bytes(range(256)) * 16)
    target = tmp_path / "modified.z64"
    target.write_bytes(bytes(range(256)) * 15 + b"\xff" * 256)
    patch = tmp_path / "arabic.bps"
    assert main(["rebuild", "bps-create", str(source), str(target), str(patch)]) == 0
    return source, target, patch


def test_cli_bps_create_and_apply_round_trip(tmp_path, capsys):
    source, target, patch = _images(tmp_path)
    report = json.loads(capsys.readouterr().out)
    assert report["patch_bytes"] == patch.stat().st_size
    assert report["target_bytes"] == 4096
    assert patch.read_bytes().startswith(BPS_MAGIC)

    # An applied image is regenerable: an existing one is replaced without a flag.
    output = tmp_path / "out.z64"
    output.write_bytes(b"stale")
    assert main(["rebuild", "bps-apply", str(patch), str(source), str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == {"output_bytes": 4096}
    assert output.read_bytes() == target.read_bytes()


@pytest.mark.parametrize(
    "argv",
    [
        ["bps-apply", "{patch}", "{source}", "{source}"],
        ["bps-apply", "{patch}", "{source}", "{patch}"],
        ["bps-create", "{source}", "{target}", "{source}"],
        ["bps-create", "{source}", "{target}", "{target}"],
        ["bps-create", "{source}", "{target}", "{source}", "--force"],
    ],
)
def test_cli_rebuild_refuses_an_output_that_is_an_input(tmp_path, capsys, argv):
    source, target, patch = _images(tmp_path)
    capsys.readouterr()
    before = {path: path.read_bytes() for path in (source, target, patch)}
    names = {"source": str(source), "target": str(target), "patch": str(patch)}
    argv = [arg.format(**names) for arg in argv]

    assert main(["rebuild", *argv]) == 2

    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"OUTPUT_EXISTS: output {argv[3]} is one of the inputs\n"
    assert {path: path.read_bytes() for path in before} == before


def test_cli_rebuild_knows_an_input_under_another_spelling(tmp_path, capsys, monkeypatch):
    source, target, patch = _images(tmp_path)
    capsys.readouterr()
    # A relative spelling of the source.
    monkeypatch.chdir(tmp_path)
    assert main(["rebuild", "bps-apply", str(patch), str(source), source.name]) == 2
    assert capsys.readouterr().err == f"OUTPUT_EXISTS: output {source.name} is one of the inputs\n"
    # A hard link to the source, which only the file system knows is the same file.
    link = tmp_path / "link.z64"
    try:
        os.link(source, link)
    except OSError:
        pytest.skip("hard links are unavailable here")
    assert main(["rebuild", "bps-apply", str(patch), str(source), str(link)]) == 2
    assert capsys.readouterr().err == f"OUTPUT_EXISTS: output {link} is one of the inputs\n"
    assert source.read_bytes() == bytes(range(256)) * 16


def test_cli_bps_create_replaces_only_a_bps_patch_unless_forced(tmp_path, capsys):
    source, target, patch = _images(tmp_path)
    capsys.readouterr()
    image = tmp_path / "other.z64"
    image.write_bytes(b"not a patch")

    assert main(["rebuild", "bps-create", str(source), str(target), str(image)]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert (
        err == f"OUTPUT_EXISTS: {image} exists and is not a BPS patch; pass --force to replace it\n"
    )
    assert image.read_bytes() == b"not a patch"

    # bps-create typed in bps-apply's order would replace the modified image.
    modified = target.read_bytes()
    assert main(["rebuild", "bps-create", str(patch), str(source), str(target)]) == 2
    assert capsys.readouterr().err.startswith(f"OUTPUT_EXISTS: {target} exists and is not")
    assert target.read_bytes() == modified

    assert main(["rebuild", "bps-create", str(source), str(target), str(image), "--force"]) == 0
    assert image.read_bytes() == patch.read_bytes()

    # An earlier patch is replaced without the flag.
    image.write_bytes(BPS_MAGIC + b"stale")
    assert main(["rebuild", "bps-create", str(source), str(target), str(image)]) == 0
    assert image.read_bytes() == patch.read_bytes()
