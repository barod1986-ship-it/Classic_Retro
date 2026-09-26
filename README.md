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

## Localization targets

Each supported game revision is a **localization target**: the game, the way its
renderer is made to draw Arabic, its documents, and the checks and builds the toolkit
runs the same way for every target.

| Target | Game | Kind | Rendering strategy |
|--------|------|------|--------------------|
| `firered` | Pokémon FireRed Version (USA, Europe) (Rev 1) | source overlay | `glyph-font` |
| `minish-cap` | The Legend of Zelda: The Minish Cap (USA) | source overlay | `glyph-font` |
| `ff6a` | Final Fantasy VI Advance (USA) | ROM overlay | `glyph-font` |
| `golden-sun` | Golden Sun (USA, Europe) | ROM overlay | `glyph-font` |
| `fire-emblem` | Fire Emblem: The Sacred Stones (USA, Australia) | ROM overlay | `glyph-font`, `text-images` |
| `pmd-red` | Pokémon Mystery Dungeon: Red Rescue Team (USA, Australia) | ROM overlay | `glyph-font` |
| `mmbn` | Mega Man Battle Network (USA) | ROM overlay | `line-cells` |
| `mlss` | Mario & Luigi: Superstar Saga (USA) | ROM overlay | `glyph-font` |
| `fomt` | Harvest Moon: Friends of Mineral Town (USA) | ROM overlay | `line-cells` |
| `advance-wars` | Advance Wars (USA, Rev 1) | ROM overlay | `glyph-font` |
| `metroid-fusion` | Metroid Fusion (USA) | ROM overlay | `glyph-font` |
| `tactics-ogre` | Tactics Ogre: The Knight of Lodis (USA) | ROM overlay | `glyph-font` |
| `nsmb` | New Super Mario Bros. (USA), Nintendo DS | ROM overlay | `glyph-font` |

```text
classic-retro targets list                          # every target, its documents and operations
classic-retro targets strategies                    # the ways of drawing Arabic, and who uses them
classic-retro targets check-hooks [TARGET ...]      # re-assemble hook code, compare with stored bytes
classic-retro targets check-translations TARGET --font FONT [--preview-dir DIR]
classic-retro targets build TARGET ROM --font FONT --out-dir DIR [--write-rom NAME]
classic-retro targets prepare TARGET SOURCE --font FONT      # source overlays: patch a checkout
classic-retro targets extract TARGET INPUT [--out FILE]      # a translator's workspace
classic-retro targets strip WORKSPACE [--out FILE]           # the workspace, ready to commit
```

`targets build` also reports whether the patch matches the target's recorded
reference patch. Every game keeps its own command group too (`classic-retro fomt ...`).

### Translating

The Arabic of every target lives in `src/classic_retro/translations/<target>.json`:
entries by stable id, a note on the target's notation, and a glossary, with no text of
the game. A translator works in a local workspace that adds each entry's original from
their own copy, checks and builds from it, then strips it for review:

```text
classic-retro targets extract fomt "path/to/game.gba"      # writes fomt.workspace.json (stays local)
classic-retro targets check-translations fomt --translations fomt.workspace.json --font FONT
classic-retro targets build fomt "path/to/game.gba" --font FONT --out-dir build \
  --translations fomt.workspace.json
classic-retro targets strip fomt.workspace.json --out fomt.json
```

Every check and build holds a translations file against the originals pinned in the
target's code. See [the translator's guide](docs/TRANSLATING_AR.md) (in Arabic).

The three rendering strategies are what the thirteen targets proved, not the only ones
possible. Games on other platforms will need other methods, and the strategy and
target registries accept them from this repository or from other packages through
entry points. See [the rendering strategies](docs/ARABIC_STRATEGIES.md) and
[adding a target](docs/ADDING_A_TARGET.md).

## Research tools

A new game is studied before it becomes a target. The `research` commands run it under
an emulator from a script, and scan its image:

```text
classic-retro research run game.gba reach-the-scene.txt --out-dir shots   # mGBA, with breakpoints
classic-retro research run game.sfc script.txt --core snes9x_libretro.so  # any libretro core
classic-retro research run game.nds script.txt --core desmume_libretro.so # a DS game
classic-retro research free-space game.gba
classic-retro research pointers game.gba --to 0x08123456
classic-retro research pointer-tables game.gba
classic-retro research text game.gba --table game.tbl
classic-retro research relative-search game.gba WORD
classic-retro research disasm game.gba 0x08012345
```

A script holds commands such as `run 300`, `tap START`, `shot menu.png`,
`save menu.state`, `watch write 0x03001234` and `break 0x08012345 5 r0 16`. See
[the research tools](docs/RESEARCH_TOOLS.md).

## Repository status

**Localization platform with thirteen reference targets: twelve on the Game Boy Advance and the
first on the Nintendo DS.**

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

The ninth reference target is **Harvest Moon: Friends of Mineral Town (USA)**, which has no
decompilation: a binary overlay patches your own ROM inside its padding (it stays 8 MiB). The game
draws fixed 8x16 cells, so every translated line is shaped with HarfBuzz and drawn ahead of time,
its cells joining one bank under two-byte codes the game treats like Shift-JIS; Thumb hooks copy a
cell where the game would unpack a glyph and draw it at the mirrored column, so lines fill from the
right edge of the box. The player's name keeps the game's glyphs and reads left to right inside the
Arabic line (the character expanders hand it over reversed), and the flashback's speaker names get
16-pixel cells of their own. The whole opening is in Arabic: Thomas on the farm, the flashback of
the summer at the old man's farm and the first morning (33 strings and 5 name tags). See
[the Harvest Moon testing guide](docs/FOMT_ARABIC_TEST_AR.md) and
[the renderer notes](docs/FOMT_ARABIC_RENDERER.md).

The tenth reference target is **Advance Wars (USA, Rev 1)**, which has no decompilation: a
binary overlay patches your own ROM inside its padding (it stays 4 MiB). The game's printer draws
a whole line left to right into a strip of 8x16 tile columns, so the overlay leaves the pen alone
and mirrors the result: thirteen small Thumb hooks put each tile column into the tilemap at its
mirror with the hardware's horizontal flip, draw Arabic glyphs stored flipped from a font of their
own, drop the one-pixel gap between letters, and lay out the Yes/No answers and cursor right to
left. The player's name keeps the game's letters (reversed in place while drawn, each one flipped)
and reads left to right inside the Arabic line. Nell's whole opening is in Arabic, with both
answers to both of her questions (14 messages). See
[the Advance Wars testing guide](docs/ADVANCE_WARS_ARABIC_TEST_AR.md) and
[the renderer notes](docs/ADVANCE_WARS_ARABIC_RENDERER.md).

The eleventh reference target is **Metroid Fusion (USA)**. Its decompilation names the code but
takes its data from the original, so a binary overlay patches your own ROM inside its padding (it
stays 8 MiB). The text routines of the intro and of the briefings on the map keep their pen; Thumb
hooks mirror where each Arabic glyph lands on the 224-pixel line, fade a monologue page's tiles in
from the right, and move the next-page arrow and the typing cursors to the other side. The
briefing's question shows its options the other way round, and the arrow keys follow them. The
padding is 7 MiB from the code, beyond a BL's reach, so the hooks are called through veneers
written over an unused function. Arabic glyph codes start at 0xB040, where the game's own glyph
address formula lands in the padding and no routine reads a command: the glyphs are outlined like
the game's letters and up to 16 pixels wide. The opening is in Arabic: Samus's narration from
SR388 to her new mission on the B.S.L station (12 monologues), then the first two briefings on
the station's map with their names in colour and the two questions. See
[the Metroid Fusion testing guide](docs/METROID_FUSION_ARABIC_TEST_AR.md) and
[the renderer notes](docs/METROID_FUSION_ARABIC_RENDERER.md).

The twelfth reference target is **Tactics Ogre: The Knight of Lodis (USA)**. Its disassembly
builds the image but takes its data from the original, so a binary overlay patches your own ROM
in the zeros after its data (it stays 8 MiB). The dialogue draws a glyph at a time into columns of
tiles and writes whole columns, so the draw hook takes every glyph of an Arabic message: it ORs the
glyph into the window's cleared tiles at the mirror of the pen on the window's line, and moves the
game's pen on; a second hook gives the Arabic widths, so the window is sized to the Arabic lines.
Only the 128 bytes below the commands are glyphs to the game, so in a message of the Arabic bank
they are the glyphs of a right-to-left font of up to 16x16 pixels, given only to the forms the
script uses. The scene's block is copied with its untranslated messages kept in English, and a
character's name from the game's list is written out in Arabic at build time. The opening scene
in the harbour town is in Arabic, up to the name screen (15 messages). See
[the Tactics Ogre testing guide](docs/TACTICS_OGRE_ARABIC_TEST_AR.md) and
[the renderer notes](docs/TACTICS_OGRE_ARABIC_RENDERER.md).

The thirteenth reference target, and the first on the Nintendo DS, is **New Super Mario Bros.
(USA)**. The DS platform comes with it: detection from the header's checksums, the NitroFS file
system and NARC archives, BMG message files, NFTR fonts, and the backward LZ that packs the ARM9
binary. The game centres every line of its menus and prompts on its own and draws it at once, so
the Arabic needs no hook at all: each line is stored in visual order, its glyphs from the leftmost
to the rightmost, and the game draws it as it is. The Arabic forms take the place of the kana in
the game's font, which sits in a NARC inside the ARM9; the ARM9 is packed again like the original,
keeping its compressed bytes wherever the code did not change, so the patch (about 8 KB) carries
the new font and texts and not the game's code. The file select, the world map's menu, the pause
menu, the save and quit prompts and the Star Coin gates are in Arabic (42 messages). See
[the New Super Mario Bros. testing guide](docs/NSMB_ARABIC_TEST_AR.md) and
[the renderer notes](docs/NSMB_ARABIC_RENDERER.md).

See [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md).
