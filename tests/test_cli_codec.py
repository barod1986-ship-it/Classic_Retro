from __future__ import annotations

import json

from classic_retro.cli import main


def test_cli_codec_verify(tmp_path, capsys):
    profile = {
        "schema_version": "1.0",
        "id": "fixture",
        "glyphs": [
            {"sequence": "A", "bytes_hex": "01"},
            {"sequence": "B", "bytes_hex": "02"},
        ],
        "terminators": [
            {"id": "end", "bytes_hex": "ff"},
        ],
    }
    profile_path = tmp_path / "codec.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    data_path = tmp_path / "text.bin"
    data_path.write_bytes(b"\x01\x02\xff")

    assert (
        main(
            [
                "codec",
                "verify",
                str(profile_path),
                str(data_path),
                "--require-terminator",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["round_trip"] is True
    assert output["visible_text"] == "AB"
    assert output["terminator_id"] == "end"
