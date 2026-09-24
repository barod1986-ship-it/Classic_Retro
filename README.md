# Classic Retro Arabic Translation Toolkit

A clean-room toolkit for researching, extracting, translating, rebuilding, and validating Arabic localizations for classic video games.

## Project direction

Classic Retro is **multi-platform from the foundation**. It is not a GBA project that may later expand to other consoles.

The architecture is designed for classic systems including, but not limited to:

- Game Boy / Game Boy Color
- Game Boy Advance
- NES / Famicom
- SNES / Super Famicom
- Mega Drive / Genesis
- PlayStation
- Nintendo 64
- other classic systems when a verified adapter is added

No platform is the architectural center of the project.

The core model is:

```text
Platform -> Engine / Family -> Game Adapter
```

Reusable Arabic localization logic stays in the core. Platform, engine, and game-specific behavior stays in adapters.

## Core principles

- Research the exact game revision before editing anything.
- Prefer an existing source-matching decompilation/disassembly when appropriate.
- Do not assume two games on the same console use the same text engine.
- Do not assume one console is the default or primary platform.
- Keep Arabic shaping, bidi/RTL handling, tokenization, wrapping, and glyph mapping reusable.
- Keep game-specific offsets, pointers, compression, control codes, and rendering behavior outside the core.
- Build reproducibly from a verified original game image supplied by the user.
- Never commit copyrighted ROM/disc images to this repository.
- Produce patches/build outputs, not redistributed commercial game images.
- Validate every supported revision by hashes and automated checks.
- Document discoveries before turning them into assumptions.

## Initial pipeline

```text
Verified Game Image
   |
Platform + Game / Revision Detection
   |
Research + Engine Identification
   |
Extractor
   |-- text
   |-- control codes
   |-- pointers / references
   |-- fonts / graphics metadata
   |
Translation Source (UTF-8 Arabic)
   |
Arabic Pipeline
   |-- tokenization
   |-- shaping
   |-- bidi / RTL
   |-- wrapping
   |-- glyph mapping
   |
Rebuild
   |-- relocation
   |-- reference repair
   |-- compression
   |-- font build
   |-- platform-specific finalization
   |
Validation
   |
Patch / Build Artifact
```

## Repository status

**Foundation toolkit with a playable FireRed Rev 1 reference patch.**

The first end-to-end example translates the 13 Professor OAK speech strings in
the new-game intro. This is a renderer/font test, not a complete game translation.
Other platforms currently have detection or foundation components; they do not
all have playable Arabic adapters.

Install with `python -m pip install -e ".[dev]"`, run `pytest`, and identify your
own input with `classic-retro detect "path/to/game.gba"`.

See [the Arabic FireRed testing guide](docs/FIRERED_ARABIC_TEST_AR.md) for applying
the reference BPS patch, the exact supported ROM, and the current limits.

The second reference target is **The Legend of Zelda: The Minish Cap (USA)** through the
zeldaret/tmc decompilation: a right-to-left renderer, a 16px Arabic font page, and the
whole new-game opening (26 messages) in Arabic. Because that decompilation extracts its
assets from the original ROM, CI checks and compiles the overlay while the BPS patch is
built locally. See [the Minish Cap testing guide](docs/MINISH_CAP_ARABIC_TEST_AR.md) and
[the renderer notes](docs/TMC_ARABIC_RENDERER.md).

The third reference target is **Final Fantasy VI Advance (USA)**, which has no
decompilation: a binary ROM overlay adds Thumb hooks for right-to-left drawing, a 16px
Arabic font and a rebuilt dialogue bank, and ships as a BPS patch built locally from your
own ROM. The whole new-game opening (19 messages: the narration, the cliff above Narshe
and the way to the mines) is in Arabic. See [the FF6 Advance testing guide](docs/FF6A_ARABIC_TEST_AR.md)
and [the renderer notes](docs/FF6A_ARABIC_RENDERER.md).

The fourth reference target is **Golden Sun (USA, Europe)**. Its disassembly (gsret/goldensun)
rebuilds the ROM but cannot relocate data yet, so a binary overlay patches your own ROM: the
translated strings get their own context-Huffman trees with 12-bit Arabic codes (the game's text
bank stays untouched), Thumb hooks mirror the game's sprite typewriter, and the player's name
stays a left-to-right island inside Arabic lines.
The whole storm-night opening (21 messages, both Yes/No branches) is in Arabic. See
[the Golden Sun testing guide](docs/GOLDEN_SUN_ARABIC_TEST_AR.md) and
[the renderer notes](docs/GOLDEN_SUN_ARABIC_RENDERER.md).

The fifth reference target is **Fire Emblem: The Sacred Stones (USA, Australia)**. The
fireemblem8u decompilation rebuilds the ROM and gave every address, but most of its data is
still binary, so a binary overlay patches your own ROM inside the image's own padding (it
stays 16 MiB): translated messages are stored uncompressed next to the Huffman bank, and
Thumb hooks switch the game's talk engine to right-to-left for them, in dialogue bubbles and
in the world map's narration box. The opening legend (seven images, redrawn from HarfBuzz-shaped
Arabic in the original palette), the world map's narration of Magvel and the throne-room scene
of the prologue (5 messages) are in Arabic. See
[the Fire Emblem testing guide](docs/FIRE_EMBLEM_ARABIC_TEST_AR.md) and
[the renderer notes](docs/FIRE_EMBLEM_ARABIC_RENDERER.md).

The sixth reference target is **Pokémon Mystery Dungeon: Red Rescue Team (USA, Australia)**.
The pret/pmd-red decompilation rebuilds the ROM and gave every address, but its data is still
extracted from the original, so a binary overlay patches your own ROM inside its own padding (it
stays 32 MiB): Arabic glyphs join the game's charmap under unused two-byte codes and carry a
right-to-left flag, and Thumb hooks draw such glyphs at the mirrored position of the game's cursor,
so its floating text, dialogue box, key arrow and menus (cursor included) turn right-to-left. The
whole personality test a new game starts with is in Arabic: the intro, all 56 questions with their
answers and the gender question (158 strings). See
[the Mystery Dungeon testing guide](docs/PMD_RED_ARABIC_TEST_AR.md) and
[the renderer notes](docs/PMD_RED_ARABIC_RENDERER.md).

The seventh reference target is **Mega Man Battle Network (USA)**. The Silenthal/bn1 disassembly
matches the ROM and gave every address, but its assets are extracted from the original, so a binary
overlay patches your own ROM inside its padding (it stays 8 MiB). The game draws text in monospace
8x16 cells, which Arabic cannot use one letter at a time: every translated line is shaped with
HarfBuzz and drawn ahead of time, each page's cells become a glyph bank of their own, and two Thumb
hooks pick the page's bank by the address of its text and fill its lines from the right edge of the
box (Latin words such as PET keep the game's glyphs). Lan's first morning, from a new game to the
school gate, is in Arabic: waking up, the PET, the house (Mom, breakfast, the rooms' objects,
MegaMan's L Button advice) and the walk to school (50 script sections). See
[the Mega Man testing guide](docs/MMBN_ARABIC_TEST_AR.md) and
[the renderer notes](docs/MMBN_ARABIC_RENDERER.md).

The eighth reference target is **Mario & Luigi: Superstar Saga (USA)**. The jellees/mlss
decompilation builds the ROM, but its data is extracted from the original, so a binary overlay
patches your own ROM inside its zero padding (it stays 16 MiB). The game's printer takes up to six
fonts per font list, selected by a prefix byte, and the USA image leaves five slots empty: a 16x12
Arabic font drawn from the reference font becomes font 1 of every list, so the game's own measuring
sizes the speech bubbles and centres the subtitles, and one Thumb hook draws its glyphs at the
mirrored pen position, from the right edge of the box. The opening up to the first battle is in
Arabic: the castle subtitles, the Toad's run to the Mario Bros.' house and his search for Mario, and
Bowser's taunt (12 messages). See [the Mario & Luigi testing guide](docs/MLSS_ARABIC_TEST_AR.md) and
[the renderer notes](docs/MLSS_ARABIC_RENDERER.md).

See [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md).
