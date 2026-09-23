from __future__ import annotations

from classic_retro.adapters.registry import AdapterRegistry
from classic_retro.platforms.gameboy import GameBoyColorPlatformAdapter, GameBoyPlatformAdapter
from classic_retro.platforms.gba import GBAPlatformAdapter
from classic_retro.platforms.megadrive import MegaDrivePlatformAdapter
from classic_retro.platforms.n64 import N64PlatformAdapter
from classic_retro.platforms.nes import NESPlatformAdapter
from classic_retro.platforms.ps1 import PlayStationPlatformAdapter
from classic_retro.platforms.snes import SNESPlatformAdapter


def register_builtin_adapters(registry: AdapterRegistry) -> None:
    for adapter in (
        GameBoyPlatformAdapter(),
        GameBoyColorPlatformAdapter(),
        GBAPlatformAdapter(),
        NESPlatformAdapter(),
        SNESPlatformAdapter(),
        MegaDrivePlatformAdapter(),
        PlayStationPlatformAdapter(),
        N64PlatformAdapter(),
    ):
        registry.register_platform(adapter)
