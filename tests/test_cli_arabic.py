from __future__ import annotations

import json

from classic_retro.cli import main


def test_cli_arabic_check(tmp_path, capsys):
    document = {
        "schema_version": "1.0",
        "game_id": "fixture-game",
        "source_language": "en",
        "target_language": "ar",
        "entries": [
            {
                "id": "dialogue.001",
                "source": {
                    "tokens": [
                        {"type": "text", "text": "Hello "},
                        {
                            "type": "variable",
                            "id": "player",
                            "name": "PLAYER",
                            "movement": "free",
                        },
                    ]
                },
                "target": {
                    "tokens": [
                        {"type": "text", "text": "مرحبًا "},
                        {
                            "type": "variable",
                            "id": "player",
                            "name": "PLAYER",
                            "movement": "free",
                        },
                    ]
                },
            }
        ],
    }
    path = tmp_path / "translation.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert main(["arabic", "check", str(path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["entries"] == 1
    assert output["inline_tokens"] == 1
    assert output["normalization"] == "NFC"
    assert output["base_direction"] == "R"
