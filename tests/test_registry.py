from __future__ import annotations

import hashlib

import pytest

from classic_retro.adapters.base import EngineAdapter, GameAdapter, GameRevision, PlatformAdapter, ProbeResult
from classic_retro.adapters.discovery import detect_game
from classic_retro.adapters.registry import AdapterRegistry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.identity import FileFingerprint


class FixturePlatform(PlatformAdapter):
    id = "fixture"
    display_name = "Fixture"

    def probe(self, source):
        return ProbeResult.no_match()


class FixtureEngine(EngineAdapter):
    id = "fixture-engine"
    display_name = "Fixture Engine"
    platform_ids = ("fixture",)


class FixtureGame(GameAdapter):
    id = "fixture-game"
    title = "Fixture Game"
    platform_id = "fixture"
    engine_id = "fixture-engine"
    revisions = (GameRevision(hashlib.sha256(b"fixture").hexdigest(), size=7),)


def test_registry_rejects_duplicate_ids():
    registry = AdapterRegistry()
    registry.register_platform(FixturePlatform())
    with pytest.raises(ClassicRetroError) as caught:
        registry.register_platform(FixturePlatform())
    assert caught.value.code is ErrorCode.ADAPTER_ID_CONFLICT


def test_game_matching_is_exact_sha256_and_size():
    registry = AdapterRegistry()
    registry.register_engine(FixtureEngine())
    registry.register_game(FixtureGame())

    fingerprint = FileFingerprint(
        name="fixture.bin",
        size=7,
        sha256=hashlib.sha256(b"fixture").hexdigest(),
    )
    match = detect_game(fingerprint, "fixture", registry)
    assert match is not None
    assert match.id == "fixture-game"

    wrong = FileFingerprint(name="fixture.bin", size=7, sha256="0" * 64)
    assert detect_game(wrong, "fixture", registry) is None
