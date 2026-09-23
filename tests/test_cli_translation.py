from __future__ import annotations

import json

from classic_retro.cli import main


def test_cli_translation_validate(tmp_path, capsys):
    document = {
        "schema_version": "1.0",
        "game_id": "fixture-game",
        "source_language": "en",
        "target_language": "ar",
        "entries": [
            {
                "id": "menu.start",
                "status": "final",
                "source": {
                    "tokens": [
                        {"type": "text", "text": "Start"},
                    ]
                },
                "target": {
                    "tokens": [
                        {"type": "text", "text": "ابدأ"},
                    ]
                },
            }
        ],
    }
    path = tmp_path / "translation.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert main(["translation", "validate", str(path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["entries"] == 1
    assert output["status"]["final"] == 1
    assert output["target_language"] == "ar"
