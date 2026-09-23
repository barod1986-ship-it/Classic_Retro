from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document


def test_game_identity_schema_accepts_multifile_media():
    validate_document(
        "game-identity.schema.json",
        {
            "schema_version": "1.0",
            "platform": "ps1",
            "title": "Example",
            "region": "USA",
            "revision": "1.0",
            "media": {
                "kind": "bin-cue",
                "files": [
                    {
                        "role": "data-track",
                        "name": "disc.bin",
                        "size": 2048,
                        "sha256": "a" * 64,
                    },
                    {
                        "role": "cue-sheet",
                        "name": "disc.cue",
                        "size": 100,
                        "sha256": "b" * 64,
                    },
                ],
            },
        },
    )


def test_translation_schema_requires_arabic_target():
    with pytest.raises(ClassicRetroError) as caught:
        validate_document(
            "translation.schema.json",
            {
                "schema_version": "1.0",
                "game_id": "example",
                "source_language": "en",
                "target_language": "en",
                "entries": [],
            },
        )

    assert caught.value.code is ErrorCode.INVALID_SCHEMA_INSTANCE


def test_translation_schema_accepts_typed_inline_tokens():
    validate_document(
        "translation.schema.json",
        {
            "schema_version": "1.0",
            "game_id": "example",
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
                                "id": "name",
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
                                "id": "name",
                                "name": "PLAYER",
                                "movement": "free",
                            },
                        ]
                    },
                }
            ],
        },
    )
