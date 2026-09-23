from __future__ import annotations

import json
import zlib

from classic_retro.cli import main


def test_cli_transform_verify(tmp_path, capsys):
    profile = {
        "schema_version": "1.0",
        "id": "fixture",
        "stages": [
            {
                "codec": "zlib",
                "options": {"level": 9, "max_output_bytes": 1024},
            }
        ],
    }
    profile_path = tmp_path / "transform.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    data_path = tmp_path / "resource.bin"
    data_path.write_bytes(zlib.compress(b"HELLO HELLO", level=1))

    assert main(["transform", "verify", str(profile_path), str(data_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["round_trip"] is True
    assert output["reused_original"] is True
    assert output["decoded_bytes"] == len(b"HELLO HELLO")
    assert output["stages"] == ["zlib"]
