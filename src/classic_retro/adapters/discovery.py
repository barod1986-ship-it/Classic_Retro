from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from classic_retro.adapters.base import GameRevision, ProbeResult, ProbeSource
from classic_retro.adapters.registry import AdapterRegistry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.identity import FileFingerprint, fingerprint_file


@dataclass(frozen=True, slots=True)
class PlatformMatch:
    id: str
    display_name: str
    confidence: float
    evidence: tuple[str, ...]
    metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GameMatch:
    id: str
    title: str
    platform_id: str
    engine_id: str
    revision: GameRevision

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "platform_id": self.platform_id,
            "engine_id": self.engine_id,
            "revision": asdict(self.revision),
        }


@dataclass(frozen=True, slots=True)
class DetectionReport:
    fingerprint: FileFingerprint
    platform: PlatformMatch
    game: GameMatch | None
    supported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint.to_dict(),
            "platform": self.platform.to_dict(),
            "game": None if self.game is None else self.game.to_dict(),
            "supported": self.supported,
        }


def detect_platform(
    source: ProbeSource,
    registry: AdapterRegistry,
    *,
    minimum_confidence: float = 0.80,
) -> PlatformMatch:
    candidates: list[tuple[str, str, ProbeResult]] = []

    for adapter in registry.platforms.values():
        result = adapter.probe(source)
        if result.confidence >= minimum_confidence:
            candidates.append((adapter.id, adapter.display_name, result))

    if not candidates:
        raise ClassicRetroError(
            ErrorCode.PLATFORM_NOT_DETECTED,
            f"No platform matched {source.name} with confidence >= {minimum_confidence:.2f}",
        )

    candidates.sort(key=lambda item: (-item[2].confidence, item[0]))
    best = candidates[0]
    if len(candidates) > 1 and abs(candidates[1][2].confidence - best[2].confidence) < 1e-9:
        tied = ", ".join(item[0] for item in candidates if item[2].confidence == best[2].confidence)
        raise ClassicRetroError(
            ErrorCode.AMBIGUOUS_PLATFORM,
            f"Platform detection is ambiguous: {tied}",
        )

    return PlatformMatch(
        id=best[0],
        display_name=best[1],
        confidence=best[2].confidence,
        evidence=best[2].evidence,
        metadata=dict(best[2].metadata),
    )


def detect_game(
    fingerprint: FileFingerprint,
    platform_id: str,
    registry: AdapterRegistry,
) -> GameMatch | None:
    matches: list[GameMatch] = []
    for adapter in registry.games.values():
        if adapter.platform_id != platform_id:
            continue
        revision = adapter.match_revision(fingerprint)
        if revision is not None:
            matches.append(
                GameMatch(
                    id=adapter.id,
                    title=adapter.title,
                    platform_id=adapter.platform_id,
                    engine_id=adapter.engine_id,
                    revision=revision,
                )
            )

    if len(matches) > 1:
        ids = ", ".join(match.id for match in matches)
        raise ClassicRetroError(
            ErrorCode.ADAPTER_ID_CONFLICT,
            f"Multiple game adapters claim the same exact revision: {ids}",
        )
    return matches[0] if matches else None


def detect_file(path: Path, registry: AdapterRegistry) -> DetectionReport:
    fingerprint = fingerprint_file(path)
    source = ProbeSource(path)
    platform = detect_platform(source, registry)
    game = detect_game(fingerprint, platform.id, registry)

    if game is not None and game.engine_id not in registry.engines:
        raise ClassicRetroError(
            ErrorCode.MISSING_ENGINE_ADAPTER,
            f"Game adapter {game.id} requires missing engine adapter {game.engine_id}",
        )

    return DetectionReport(
        fingerprint=fingerprint,
        platform=platform,
        game=game,
        supported=game is not None,
    )
