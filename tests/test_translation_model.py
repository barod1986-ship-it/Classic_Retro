from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.document import TranslationDocument


def _document(target_tokens):
    return {
        "schema_version": "1.0",
        "game_id": "fixture-game",
        "source_language": "en",
        "target_language": "ar",
        "entries": [
            {
                "id": "intro.001",
                "status": "reviewed",
                "source": {
                    "tokens": [
                        {"type": "text", "text": "Welcome, "},
                        {
                            "type": "variable",
                            "id": "player",
                            "name": "PLAYER",
                            "movement": "free",
                        },
                        {"type": "text", "text": "!"},
                        {
                            "type": "control",
                            "id": "wait",
                            "name": "WAIT",
                            "movement": "ordered",
                            "args": {"frames": 30},
                        },
                        {
                            "type": "page_break",
                            "id": "page",
                            "movement": "ordered",
                        },
                    ]
                },
                "target": {"tokens": target_tokens},
            }
        ],
    }


def _valid_target():
    return [
        {"type": "text", "text": "مرحبًا بك يا "},
        {
            "type": "variable",
            "id": "player",
            "name": "PLAYER",
            "movement": "free",
        },
        {"type": "text", "text": "!"},
        {
            "type": "control",
            "id": "wait",
            "name": "WAIT",
            "movement": "ordered",
            "args": {"frames": 30},
        },
        {
            "type": "page_break",
            "id": "page",
            "movement": "ordered",
        },
    ]


def test_valid_document_preserves_inline_codes():
    document = TranslationDocument.from_dict(_document(_valid_target()))

    assert document.entries[0].target.visible_text == "مرحبًا بك يا !"
    assert document.summary()["status"]["reviewed"] == 1


def test_free_variable_can_move_without_breaking_validation():
    target = _valid_target()
    variable = target.pop(1)
    target.insert(0, variable)

    TranslationDocument.from_dict(_document(target))


def test_missing_protected_token_is_rejected():
    target = [token for token in _valid_target() if token.get("id") != "player"]

    with pytest.raises(ClassicRetroError) as caught:
        TranslationDocument.from_dict(_document(target))

    assert caught.value.code is ErrorCode.TOKEN_SET_MISMATCH


def test_changed_control_definition_is_rejected():
    target = _valid_target()
    target[3] = {
        "type": "control",
        "id": "wait",
        "name": "WAIT",
        "movement": "ordered",
        "args": {"frames": 60},
    }

    with pytest.raises(ClassicRetroError) as caught:
        TranslationDocument.from_dict(_document(target))

    assert caught.value.code is ErrorCode.TOKEN_DEFINITION_MISMATCH


def test_ordered_control_sequence_cannot_be_reversed():
    target = _valid_target()
    wait = target.pop(3)
    page = target.pop(3)
    target.extend([page, wait])

    with pytest.raises(ClassicRetroError) as caught:
        TranslationDocument.from_dict(_document(target))

    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_duplicate_entry_ids_are_rejected():
    data = _document(_valid_target())
    data["entries"].append(dict(data["entries"][0]))

    with pytest.raises(ClassicRetroError) as caught:
        TranslationDocument.from_dict(data)

    assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID
