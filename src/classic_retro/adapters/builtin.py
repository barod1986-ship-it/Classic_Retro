from __future__ import annotations

from classic_retro.adapters.registry import AdapterRegistry
from classic_retro.engines.ff6a import Ff6aEngineAdapter
from classic_retro.engines.fire_emblem import FireEmblemEngineAdapter
from classic_retro.engines.fomt import FomtEngineAdapter
from classic_retro.engines.golden_sun import GoldenSunEngineAdapter
from classic_retro.engines.mlss import MlssEngineAdapter
from classic_retro.engines.mmbn import MmbnEngineAdapter
from classic_retro.engines.pmd import PmdEngineAdapter
from classic_retro.engines.pokemon_gen3 import PokemonGen3EngineAdapter
from classic_retro.engines.tmc import TmcEngineAdapter
from classic_retro.games.final_fantasy_vi_advance import FinalFantasyVIAdvanceUsaGameAdapter
from classic_retro.games.fire_emblem_sacred_stones import FireEmblemSacredStonesUsaGameAdapter
from classic_retro.games.golden_sun import GoldenSunUsaEuropeGameAdapter
from classic_retro.games.harvest_moon_fomt import HarvestMoonFomtUsaGameAdapter
from classic_retro.games.mario_luigi_superstar_saga import MarioLuigiSuperstarSagaUsaGameAdapter
from classic_retro.games.megaman_battle_network import MegaManBattleNetworkUsaGameAdapter
from classic_retro.games.pokemon_firered import PokemonFireRedRev1GameAdapter
from classic_retro.games.pokemon_mystery_dungeon_red import PokemonMysteryDungeonRedUsaGameAdapter
from classic_retro.games.zelda_minish_cap import ZeldaMinishCapUsaGameAdapter
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

    registry.register_engine(PokemonGen3EngineAdapter())
    registry.register_engine(TmcEngineAdapter())
    registry.register_engine(Ff6aEngineAdapter())
    registry.register_engine(GoldenSunEngineAdapter())
    registry.register_engine(FireEmblemEngineAdapter())
    registry.register_engine(PmdEngineAdapter())
    registry.register_engine(MmbnEngineAdapter())
    registry.register_engine(MlssEngineAdapter())
    registry.register_engine(FomtEngineAdapter())
    registry.register_game(PokemonFireRedRev1GameAdapter())
    registry.register_game(ZeldaMinishCapUsaGameAdapter())
    registry.register_game(FinalFantasyVIAdvanceUsaGameAdapter())
    registry.register_game(GoldenSunUsaEuropeGameAdapter())
    registry.register_game(FireEmblemSacredStonesUsaGameAdapter())
    registry.register_game(PokemonMysteryDungeonRedUsaGameAdapter())
    registry.register_game(MegaManBattleNetworkUsaGameAdapter())
    registry.register_game(MarioLuigiSuperstarSagaUsaGameAdapter())
    registry.register_game(HarvestMoonFomtUsaGameAdapter())
