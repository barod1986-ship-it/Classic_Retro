from __future__ import annotations

from importlib.metadata import entry_points
from inspect import isclass
from typing import TypeVar

from classic_retro.adapters.base import EngineAdapter, GameAdapter, PlatformAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

PLATFORM_ENTRY_POINT_GROUP = "classic_retro.platforms.v1"
ENGINE_ENTRY_POINT_GROUP = "classic_retro.engines.v1"
GAME_ENTRY_POINT_GROUP = "classic_retro.games.v1"

AdapterT = TypeVar("AdapterT", PlatformAdapter, EngineAdapter, GameAdapter)


class AdapterRegistry:
    def __init__(self) -> None:
        self.platforms: dict[str, PlatformAdapter] = {}
        self.engines: dict[str, EngineAdapter] = {}
        self.games: dict[str, GameAdapter] = {}

    def register_platform(self, adapter: PlatformAdapter) -> None:
        self._register(self.platforms, adapter)

    def register_engine(self, adapter: EngineAdapter) -> None:
        self._register(self.engines, adapter)

    def register_game(self, adapter: GameAdapter) -> None:
        self._register(self.games, adapter)

    @staticmethod
    def _register(target: dict[str, AdapterT], adapter: AdapterT) -> None:
        adapter_id = getattr(adapter, "id", "")
        if not adapter_id:
            raise ClassicRetroError(ErrorCode.ADAPTER_TYPE_ERROR, "Adapter id cannot be empty")
        if adapter_id in target:
            raise ClassicRetroError(
                ErrorCode.ADAPTER_ID_CONFLICT,
                f"Duplicate adapter id: {adapter_id}",
            )
        target[adapter_id] = adapter

    def load_entry_points(self) -> None:
        self._load_group(PLATFORM_ENTRY_POINT_GROUP, PlatformAdapter, self.register_platform)
        self._load_group(ENGINE_ENTRY_POINT_GROUP, EngineAdapter, self.register_engine)
        self._load_group(GAME_ENTRY_POINT_GROUP, GameAdapter, self.register_game)

    def _load_group(self, group: str, expected_type: type[AdapterT], register) -> None:
        for entry_point in entry_points(group=group):
            try:
                loaded = entry_point.load()
                adapter = loaded() if isclass(loaded) else loaded
            except Exception as exc:
                raise ClassicRetroError(
                    ErrorCode.ADAPTER_LOAD_FAILED,
                    f"Failed to load {group}:{entry_point.name}: {exc}",
                ) from exc

            if not isinstance(adapter, expected_type):
                raise ClassicRetroError(
                    ErrorCode.ADAPTER_TYPE_ERROR,
                    f"{group}:{entry_point.name} did not provide {expected_type.__name__}",
                )
            register(adapter)


def build_registry(*, load_external: bool = True) -> AdapterRegistry:
    from classic_retro.adapters.builtin import register_builtin_adapters

    registry = AdapterRegistry()
    register_builtin_adapters(registry)
    if load_external:
        registry.load_entry_points()
    return registry
