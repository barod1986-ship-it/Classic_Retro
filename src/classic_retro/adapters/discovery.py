from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from classic_retro.adapters.base import GameRevision, ProbeResult, ProbeSource, SourceBuildSpec
from classic_retro.adapters.registry import AdapterRegistry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.media.model import MediaKind, MediaSet
from classic_retro.media.resolve import resolve_media


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
    source_build: SourceBuildSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "platform_id": self.platform_id,
            "engine_id": self.engine_id,
            "revision": asdict(self.revision),
            "source_build": (None if self.source_build is None else asdict(self.source_build)),
        }


@dataclass(frozen=True, slots=True)
class DetectionReport:
    media: MediaSet
    platform: PlatformMatch
    game: GameMatch | None
    supported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "media": self.media.to_dict(),
            "platform": self.platform.to_dict(),
            "game": None if self.game is None else self.game.to_dict(),
            "supported": self.supported,
        }


def _choose_platform(
    candidates: list[tuple[str, str, ProbeResult]],
    source_name: str,
    minimum_confidence: float,
) -> PlatformMatch:
    candidates = [item for item in candidates if item[2].confidence >= minimum_confidence]
    if not candidates:
        raise ClassicRetroError(
            ErrorCode.PLATFORM_NOT_DETECTED,
            f"No platform matched {source_name} with confidence >= {minimum_confidence:.2f}",
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


def detect_platform(
    source: ProbeSource,
    registry: AdapterRegistry,
    *,
    minimum_confidence: float = 0.80,
) -> PlatformMatch:
    candidates = [
        (adapter.id, adapter.display_name, adapter.probe(source))
        for adapter in registry.platforms.values()
    ]
    return _choose_platform(candidates, source.name, minimum_confidence)


def detect_platform_media(
    media: MediaSet,
    registry: AdapterRegistry,
    *,
    minimum_confidence: float = 0.80,
) -> PlatformMatch:
    candidates = [
        (adapter.id, adapter.display_name, adapter.probe_media(media))
        for adapter in registry.platforms.values()
    ]
    return _choose_platform(candidates, media.entry_path.name, minimum_confidence)


def detect_game(
    media: MediaSet,
    platform_id: str,
    registry: AdapterRegistry,
) -> GameMatch | None:
    matches: list[GameMatch] = []
    for adapter in registry.games.values():
        if adapter.platform_id != platform_id:
            continue
        revision = adapter.match_revision(media)
        if revision is not None:
            matches.append(
                GameMatch(
                    id=adapter.id,
                    title=adapter.title,
                    platform_id=adapter.platform_id,
                    engine_id=adapter.engine_id,
                    revision=revision,
                    source_build=adapter.source_build,
                )
            )

    if len(matches) > 1:
        ids = ", ".join(match.id for match in matches)
        raise ClassicRetroError(
            ErrorCode.ADAPTER_ID_CONFLICT,
            f"Multiple game adapters claim the same exact revision: {ids}",
        )
    return matches[0] if matches else None


def detect_input(path: Path, registry: AdapterRegistry) -> DetectionReport:
    media = resolve_media(path)

    if media.kind is MediaKind.SINGLE_FILE:
        platform = detect_platform(ProbeSource(media.primary.path), registry)
    else:
        platform = detect_platform_media(media, registry)

    game = detect_game(media, platform.id, registry)
    if game is not None and game.engine_id not in registry.engines:
        raise ClassicRetroError(
            ErrorCode.MISSING_ENGINE_ADAPTER,
            f"Game adapter {game.id} requires missing engine adapter {game.engine_id}",
        )

    return DetectionReport(
        media=media,
        platform=platform,
        game=game,
        supported=game is not None,
    )
