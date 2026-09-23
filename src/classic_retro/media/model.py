from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from classic_retro.core.identity import FileFingerprint


class MediaKind(StrEnum):
    SINGLE_FILE = "single-file"
    CUE_SHEET = "cue-sheet"


@dataclass(frozen=True, slots=True)
class MediaMember:
    role: str
    path: Path
    fingerprint: FileFingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.path.name,
            "size": self.fingerprint.size,
            "sha256": self.fingerprint.sha256,
        }


@dataclass(frozen=True, slots=True)
class MediaSet:
    entry_path: Path
    kind: MediaKind
    members: tuple[MediaMember, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("media set must contain at least one payload member")
        object.__setattr__(self, "entry_path", self.entry_path.expanduser())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def identity_sha256(self) -> str:
        canonical = {
            "kind": self.kind.value,
            "layout_sha256": self.metadata.get("layout_sha256"),
            "members": [
                {
                    "role": member.role,
                    "size": member.fingerprint.size,
                    "sha256": member.fingerprint.sha256,
                }
                for member in self.members
            ],
        }
        encoded = json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def primary(self) -> MediaMember:
        return self.members[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "entry": self.entry_path.name,
            "identity_sha256": self.identity_sha256,
            "members": [member.to_dict() for member in self.members],
            "metadata": dict(self.metadata),
        }
