from __future__ import annotations

import json

from classic_retro.cli import main


def test_cli_rebuild_verify(tmp_path, capsys):
    image = bytearray([0xFF] * 32)
    image[0:2] = (8).to_bytes(2, "little")
    image[8:12] = b"ABCD"

    image_path = tmp_path / "game.bin"
    image_path.write_bytes(bytes(image))

    plan = {
        "schema_version": "1.0",
        "id": "fixture",
        "resources": [
            {
                "id": "text",
                "start": 8,
                "size": 4
            }
        ],
        "references": [
            {
                "id": "text_ptr",
                "offset": 0,
                "target_resource_id": "text",
                "integer": {
                    "size_bytes": 2,
                    "byte_order": "little"
                }
            }
        ]
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    assert main(["rebuild", "verify", str(plan_path), str(image_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["round_trip"] is True
    assert output["resources"] == 1
    assert output["references"] == 1
    assert output["writes"] == 0
