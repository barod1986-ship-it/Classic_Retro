from __future__ import annotations

import json

from classic_retro.cli import main


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
