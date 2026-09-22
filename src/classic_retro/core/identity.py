from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    name: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint_file(path: Path) -> FileFingerprint:
    path = path.expanduser()

    if not path.exists():
        raise ClassicRetroError(ErrorCode.INPUT_NOT_FOUND, f"Input does not exist: {path}")

    if not path.is_file():
        raise ClassicRetroError(ErrorCode.INPUT_NOT_FILE, f"Input is not a file: {path}")

    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()

    return FileFingerprint(name=path.name, size=path.stat().st_size, sha256=digest)
