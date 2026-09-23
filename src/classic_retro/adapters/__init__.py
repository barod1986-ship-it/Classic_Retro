"""Adapter contracts and registry."""

from classic_retro.adapters.base import EngineAdapter, GameAdapter, GameRevision, PlatformAdapter
from classic_retro.adapters.registry import AdapterRegistry, build_registry

__all__ = [
    "AdapterRegistry",
    "EngineAdapter",
    "GameAdapter",
    "GameRevision",
    "PlatformAdapter",
    "build_registry",
]
