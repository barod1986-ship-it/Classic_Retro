# Pokémon Generation III Engine Adapter

Version: 1

## Reference game

The first exact game revision supported by Classic Retro is Pokémon FireRed Version (USA, Europe) (Rev 1).

Identity:
- GBA game code: BPRE
- ROM size: 16 MiB
- header revision: 1
- SHA-1: dd5945db9b930750cb39d00c84da8571feebf417
- SHA-256: 729041b940afe031302d630fdbe57c0c145f3f7b6d9b8eca5e98678d0ca4d059

The SHA-1 matches firered_rev1.sha1 in pret/pokefirered.

## Source rebuild path

The preferred implementation path is source rebuild rather than blind binary patching because pret/pokefirered matches this exact ROM revision.

Pinned research/build reference:
- repository: https://github.com/pret/pokefirered
- commit: c75f352304d529f6ba92d4f74b9cf8b5c3810788
- build target: firered_rev1
- verification target: compare_firered_rev1

At that commit, config.mk selects GAME_REVISION=1 and the Makefile exposes both targets. The compare target checks the built ROM against the known SHA-1.

References:
- https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/config.mk
- https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/Makefile
- https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/INSTALL.md

## Text renderer facts

Important bytes documented by characters.h/charmap.txt:
- F7: dynamic placeholder
- F8: keypad icon plus one byte
- F9: extra symbol plus one byte
- FA: prompt-scroll
- FB: prompt-clear
- FC: extended control code
- FD: placeholder plus one byte
- FE: newline
- FF: end of string

RenderText consumes the extended-control parameters explicitly. The adapter models those documented lengths instead of guessing them.

References:
- https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/characters.h
- https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/text.c
- https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/charmap.txt

## Codec strategy

PokemonGen3TextCodec is engine-specific.

It currently:
- decodes the common English/Latin glyph table,
- preserves placeholders as movable VARIABLE tokens,
- preserves extended controls as ordered CONTROL tokens,
- preserves prompt commands and icon/symbol prefixes,
- maps FE to LINE_BREAK,
- treats FF as EOS,
- preserves unmapped standalone bytes as ordered OPAQUE tokens,
- verifies byte-exact decode/encode round trips.

Protected tokens retain raw_hex so moving a placeholder during translation does not mutate its binary identity.

## Arabic implication

The original renderer is not an Arabic renderer.

RenderText advances currentX after drawing a glyph, and the game uses font-specific width functions. GetStringWidth walks the encoded stream and handles placeholders/control codes specially.

Arabic support should therefore be implemented as an explicit source-level renderer/font adaptation, not by reversing Arabic strings in translation files.

Relevant upstream areas:
- src/text.c
- include/text.h
- graphics/fonts/
- charmap.txt

The shared Arabic core (`arabic/`) shapes the logical text and puts it in visual order; `engines/pokemon_gen3_arabic.py` encodes it in the modified renderer's right-to-left paint order, through this codec.

## The Arabic target

FireRed Rev 1 is the `firered` localization target: `source/pokefirered_arabic.py` patches the pinned pokefirered checkout (the right-to-left renderer, the Arabic font and the 13 Professor Oak speech strings), which then builds the image. See [the renderer notes](POKEMON_GEN3_ARABIC_RENDERER.md).
