from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping

from classic_retro.core.identity import FileFingerprint


@dataclass(frozen=True, slots=True)
class ProbeSource:
    path: Path
    size: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path.expanduser())
        object.__setattr__(self, "size", self.path.stat().st_size)

    @property
    def name(self) -> str:
        return self.path.name

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        if length == 0 or offset >= self.size:
            return b""
        with self.path.open("rb") as stream:
            stream.seek(offset)
            return stream.read(length)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    confidence: float
    evidence: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def no_match(cls) -> ProbeResult:
        return cls(0.0)


class PlatformAdapter(ABC):
    id: str
    display_name: str

    @abstractmethod
    def probe(self, source: ProbeSource) -> ProbeResult:
        """Return content-based evidence that the source belongs to this platform."""


class EngineAdapter(ABC):
    id: str
    display_name: str
    platform_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GameRevision:
    sha256: str
    size: int | None = None
    region: str | None = None
    revision: str | None = None

    def __post_init__(self) -> None:
        digest = self.sha256.lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("sha256 must be 64 hexadecimal characters")
        object.__setattr__(self, "sha256", digest)

    def matches(self, fingerprint: FileFingerprint) -> bool:
        return self.sha256 == fingerprint.sha256 and (
            self.size is None or self.size == fingerprint.size
        )


class GameAdapter(ABC):
    id: str
    title: str
    platform_id: str
    engine_id: str
    revisions: tuple[GameRevision, ...]

    def match_revision(self, fingerprint: FileFingerprint) -> GameRevision | None:
        return next(
            (revision for revision in self.revisions if revision.matches(fingerprint)),
            None,
        )
