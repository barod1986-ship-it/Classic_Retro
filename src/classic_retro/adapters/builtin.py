from __future__ import annotations

from classic_retro.adapters.registry import AdapterRegistry
from classic_retro.engines.advance_wars import AdvanceWarsEngineAdapter
from classic_retro.engines.ff6a import Ff6aEngineAdapter
from classic_retro.engines.fire_emblem import FireEmblemEngineAdapter
from classic_retro.engines.fomt import FomtEngineAdapter
from classic_retro.engines.golden_sun import GoldenSunEngineAdapter
from classic_retro.engines.metroid_fusion import MetroidFusionEngineAdapter
from classic_retro.engines.mlss import MlssEngineAdapter
from classic_retro.engines.mmbn import MmbnEngineAdapter
from classic_retro.engines.nsmb import NsmbEngineAdapter
from classic_retro.engines.phantom_hourglass import PhantomHourglassEngineAdapter
from classic_retro.engines.pmd import PmdEngineAdapter
from classic_retro.engines.pokemon_gen3 import PokemonGen3EngineAdapter
from classic_retro.engines.pokemon_gen4 import PokemonGen4EngineAdapter
from classic_retro.engines.sotn import SotnEngineAdapter
from classic_retro.engines.tactics_ogre import TacticsOgreEngineAdapter
from classic_retro.engines.tmc import TmcEngineAdapter
from classic_retro.games.advance_wars import AdvanceWarsUsaGameAdapter
from classic_retro.games.castlevania_sotn import CastlevaniaSotnUsaGameAdapter
from classic_retro.games.final_fantasy_vi_advance import FinalFantasyVIAdvanceUsaGameAdapter
from classic_retro.games.fire_emblem_sacred_stones import FireEmblemSacredStonesUsaGameAdapter
from classic_retro.games.golden_sun import GoldenSunUsaEuropeGameAdapter
from classic_retro.games.harvest_moon_fomt import HarvestMoonFomtUsaGameAdapter
from classic_retro.games.mario_luigi_superstar_saga import MarioLuigiSuperstarSagaUsaGameAdapter
from classic_retro.games.megaman_battle_network import MegaManBattleNetworkUsaGameAdapter
from classic_retro.games.metroid_fusion import MetroidFusionUsaGameAdapter
from classic_retro.games.new_super_mario_bros import NewSuperMarioBrosUsaGameAdapter
from classic_retro.games.pokemon_firered import PokemonFireRedRev1GameAdapter
from classic_retro.games.pokemon_mystery_dungeon_red import PokemonMysteryDungeonRedUsaGameAdapter
from classic_retro.games.pokemon_platinum import PokemonPlatinumUsaGameAdapter
from classic_retro.games.tactics_ogre import TacticsOgreUsaGameAdapter
from classic_retro.games.zelda_minish_cap import ZeldaMinishCapUsaGameAdapter
from classic_retro.games.zelda_phantom_hourglass import ZeldaPhantomHourglassUsaGameAdapter
from classic_retro.platforms.gameboy import GameBoyColorPlatformAdapter, GameBoyPlatformAdapter
from classic_retro.platforms.gba import GBAPlatformAdapter
from classic_retro.platforms.megadrive import MegaDrivePlatformAdapter
from classic_retro.platforms.n64 import N64PlatformAdapter
from classic_retro.platforms.nds import NDSPlatformAdapter
from classic_retro.platforms.nes import NESPlatformAdapter
from classic_retro.platforms.ps1 import PlayStationPlatformAdapter
from classic_retro.platforms.snes import SNESPlatformAdapter


def register_builtin_adapters(registry: AdapterRegistry) -> None:
    for adapter in (
        GameBoyPlatformAdapter(),
        GameBoyColorPlatformAdapter(),
        GBAPlatformAdapter(),
        NDSPlatformAdapter(),
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
    registry.register_engine(AdvanceWarsEngineAdapter())
    registry.register_engine(MetroidFusionEngineAdapter())
    registry.register_engine(TacticsOgreEngineAdapter())
    registry.register_engine(NsmbEngineAdapter())
    registry.register_engine(PokemonGen4EngineAdapter())
    registry.register_engine(PhantomHourglassEngineAdapter())
    registry.register_engine(SotnEngineAdapter())
    registry.register_game(PokemonFireRedRev1GameAdapter())
    registry.register_game(ZeldaMinishCapUsaGameAdapter())
    registry.register_game(FinalFantasyVIAdvanceUsaGameAdapter())
    registry.register_game(GoldenSunUsaEuropeGameAdapter())
    registry.register_game(FireEmblemSacredStonesUsaGameAdapter())
    registry.register_game(PokemonMysteryDungeonRedUsaGameAdapter())
    registry.register_game(MegaManBattleNetworkUsaGameAdapter())
    registry.register_game(MarioLuigiSuperstarSagaUsaGameAdapter())
    registry.register_game(HarvestMoonFomtUsaGameAdapter())
    registry.register_game(AdvanceWarsUsaGameAdapter())
    registry.register_game(MetroidFusionUsaGameAdapter())
    registry.register_game(TacticsOgreUsaGameAdapter())
    registry.register_game(NewSuperMarioBrosUsaGameAdapter())
    registry.register_game(PokemonPlatinumUsaGameAdapter())
    registry.register_game(ZeldaPhantomHourglassUsaGameAdapter())
    registry.register_game(CastlevaniaSotnUsaGameAdapter())
