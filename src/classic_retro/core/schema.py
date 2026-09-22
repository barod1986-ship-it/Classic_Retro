from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from classic_retro.core.errors import ClassicRetroError, ErrorCode

_SCHEMA_PACKAGE = "classic_retro.schemas"


def load_schema(name: str) -> dict[str, Any]:
    resource = files(_SCHEMA_PACKAGE).joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_document(schema_name: str, instance: object) -> None:
    schema = load_schema(schema_name)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    if not errors:
        return

    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "<root>"
    raise ClassicRetroError(
        ErrorCode.INVALID_SCHEMA_INSTANCE,
        f"{schema_name}: {location}: {first.message}",
    )
