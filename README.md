# Classic Retro Arabic Translation Toolkit

A clean-room toolkit for researching, extracting, translating, rebuilding, and validating Arabic localizations for classic video games.

## Project direction

Classic Retro is **multi-platform from the foundation**. It is not a GBA project that may later expand to other consoles.

The architecture is designed for classic systems including, but not limited to:

- Game Boy / Game Boy Color
- Game Boy Advance
- Nintendo DS
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
- Keep Arabic shaping, bidi/RTL handling, the token model, glyph drawing and glyph codes reusable.
- Keep game-specific offsets, pointers, compression, control codes, and rendering behavior outside the core.
- Build reproducibly from a verified original game image supplied by the user.
- Never commit copyrighted ROM/disc images to this repository.
- Produce patches/build outputs, not redistributed commercial game images.
- Validate every supported revision by hashes and automated checks.
- Document discoveries before turning them into assumptions.

## How a target works

```text
Your own game image (or decompilation checkout)
   |
detect: platform, exact revision by SHA-256            adapters, platforms, games, media
   |
research: text engine, font, renderer, free space      research
   |
the target: pinned originals, notation, strategy       localization, engines
   |
translations/<target>.json: the Arabic, by entry id    localization.translations
   |
Arabic: logical-text checks, shaping, bidi,            arabic, font, text
  glyphs drawn from the reference font, paint order
   |
overlay: font, text, hooks, references,                rom or source, patching, cpu, rebuild
  compression, read back and verified
   |
BPS patch (or a patched source tree) + build report
```

There is one pipeline: a target's checks, builds and translator tools all run through
`classic-retro targets`. [MASTER_SPEC.md](docs/MASTER_SPEC.md) (§3) maps the packages.

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
| `platinum` | Pokémon Platinum Version (USA, Rev 0), Nintendo DS | ROM overlay | `glyph-font` |
| `phantom-hourglass` | The Legend of Zelda: Phantom Hourglass (USA), Nintendo DS | ROM overlay | `glyph-font` |
| `sotn` | Castlevania: Symphony of the Night (USA), PlayStation | ROM overlay | `composed-lines` |
| `gran-turismo` | Gran Turismo (USA) (Rev 1), PlayStation | ROM overlay | `glyph-font` |
| `ridge-racer` | Ridge Racer (USA), PlayStation | ROM overlay | `glyph-font` |
| `chrono-trigger` | Chrono Trigger (USA), Super NES | ROM overlay | `glyph-font` |
| `link-to-the-past` | The Legend of Zelda: A Link to the Past (USA), Super NES | ROM overlay | `glyph-font` |
| `shining-force-2` | Shining Force II (USA), Mega Drive | ROM overlay | `glyph-font` |
| `final-fantasy-ii` | Final Fantasy II (USA, Rev 1), Super NES | ROM overlay | `glyph-font` |
| `final-fantasy-iii` | Final Fantasy III (USA), Super NES | ROM overlay | `glyph-font` |

```text
classic-retro targets list                          # every target, its documents and operations
classic-retro targets strategies                    # the ways of drawing Arabic, and who uses them
classic-retro targets check-hooks [TARGET ...]      # re-assemble hook code, compare with stored bytes
classic-retro targets check-translations TARGET [--font FONT] [--preview-dir DIR] [--check-digests | --update-digests]
classic-retro targets build TARGET ROM --font FONT --out-dir DIR [--write-rom NAME]
classic-retro targets prepare TARGET SOURCE --font FONT      # source overlays: patch a checkout
classic-retro targets extract TARGET INPUT [--out FILE]      # a translator's workspace
classic-retro targets strip WORKSPACE [--out FILE]           # the workspace, ready to commit
```

`targets build` also reports whether the patch matches the target's recorded
reference patch. Every target has `check-translations`, the source overlays too;
with `--check-digests` it holds the report and the previews to the digests recorded
in `src/classic_retro/localization/digests.json`, as CI does for each target. A
game's own command group holds only its engine's tools:
`encode-arabic` (a line in the game's encoding, for example
`classic-retro fomt encode-arabic TEXT --font FONT`) and `source-check` for the source
overlays.

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

The four rendering strategies are what the twenty-three targets proved, not the only ones
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
classic-retro research run game.cue script.txt --core mednafen_psx_libretro.so --system-dir bios
classic-retro research free-space game.gba
classic-retro research pointers game.gba --to 0x08123456
classic-retro research pointer-tables game.gba
classic-retro research text game.gba --table game.tbl
classic-retro research relative-search game.gba WORD
classic-retro research disasm game.gba 0x08012345
```

A script holds commands such as `run 300`, `tap START`, `touch 128 272`, `shot menu.png`,
`save menu.state`, `watch write 0x03001234` and `break 0x08012345 5 r0 16`. See
[the research tools](docs/RESEARCH_TOOLS.md).

## Repository status

**Localization platform with twenty-three reference targets: twelve on the Game Boy Advance,
three on the Nintendo DS, three on the PlayStation, four on the Super NES and one on the
Mega Drive.**

Every target translates one scene or a few strings chosen to prove its renderer, not
a whole game; the paragraphs below say what each covers. The Game Boy and Game Boy
Color, the NES and the Nintendo 64 are detected but have no target yet.

Install with `python -m pip install -e ".[dev]" -c constraints.txt` (the pinned
raster stack: the reference patch hashes are reproducible only with it), run `pytest`,
and identify your own input with `classic-retro detect "path/to/game.gba"`.

The first reference target is **Pokémon FireRed Version (USA, Europe) (Rev 1)**, through
the pret/pokefirered decompilation: the 13 Professor Oak speech strings of the new-game
intro, a renderer and font test. See [the Arabic FireRed testing guide](docs/FIRERED_ARABIC_TEST_AR.md)
for applying the reference BPS patch, the exact supported ROM, and the current limits.

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

The ninth reference target is **Harvest Moon: Friends of Mineral Town (USA)**. Its decompilation
(StanHash/fomt) takes its data from the original, so a binary overlay patches your own ROM inside
its padding (it stays 8 MiB). The game
draws fixed 8x16 cells, so every translated line is shaped with HarfBuzz and drawn ahead of time,
its cells joining one bank under two-byte codes the game treats like Shift-JIS; Thumb hooks copy a
cell where the game would unpack a glyph and draw it at the mirrored column, so lines fill from the
right edge of the box. The player's name keeps the game's glyphs and reads left to right inside the
Arabic line (the character expanders hand it over reversed), and the flashback's speaker names get
16-pixel cells of their own. The whole opening is in Arabic: Thomas on the farm, the flashback of
the summer at the old man's farm and the first morning (33 strings and 5 name tags). See
[the Harvest Moon testing guide](docs/FOMT_ARABIC_TEST_AR.md) and
[the renderer notes](docs/FOMT_ARABIC_RENDERER.md).

The tenth reference target is **Advance Wars (USA, Rev 1)**, read from the image's own code (the
ketsuban/advancewars decompilation covers a USA image not yet checked against this one): a
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

The fourteenth reference target, and the second on the Nintendo DS, is **Pokémon Platinum
Version (USA, Rev 0)**, which the pret/pokeplatinum decompilation builds byte for byte. Professor
Rowan's new-game intro is in Arabic, from his first words to his comment on the television before
the game starts (38 strings): the dialogue typed from the right, the info pages, the menus with
their cursor on the right, and the questions answered on the touch screen. The game's printer
still lays every line out from the left; five hooks, which the overlay adds to the ARM9's
instruction TCM by growing its autoload block, draw a line that holds Arabic at its mirror, a name
or a Latin word inside it left to right as a block, and turn menus, their cursor and the
touch-screen icon around. The Arabic glyphs follow the 509 of the game's two fonts, and the files
and the ARM9 go back into the image through the DS module New Super Mario Bros. brought
(`patching.nitro`), which now also reads the ARM9's autoload blocks and moves its overlay table.
Research scripts can touch the screen (`touch X Y`) on a libretro core that reads a pointer, such
as DeSmuME's. See [the Pokémon Platinum testing guide](docs/PLATINUM_ARABIC_TEST_AR.md) and
[the renderer notes](docs/PLATINUM_ARABIC_RENDERER.md).

The fifteenth reference target, and the third on the Nintendo DS, is **The Legend of Zelda:
Phantom Hourglass (USA)**, the image the zeldaret/ph decompilation targets. Its prologue is in
Arabic: the story told with paper cutouts before the game starts, from the sea to the pirates
setting sail (7 messages, 21 pages), typed from the right with the names in blue. The Arabic
forms take the place of the kana in the game's message font, and one hook, 112 bytes of ARM code
written over a routine of the C++ runtime that nothing calls, takes the printer's glyph call: a
glyph of the Arabic range is drawn at the mirror of its place on the canvas, from the call's own
arguments, so the hook keeps no state and every English text of the game is drawn as before. The
ARM9 is packed again like the original, and the patch is about 7 KB. The research tools gained
what this needed: libretro cores get a log callback, so a DeSmuME core built from its current
source runs, and that core's `system_ram` region lets a script read and patch the DS's memory.
See [the Phantom Hourglass testing guide](docs/PHANTOM_HOURGLASS_ARABIC_TEST_AR.md) and
[the renderer notes](docs/PHANTOM_HOURGLASS_ARABIC_RENDERER.md).

The sixteenth reference target, and the first on the PlayStation, is **Castlevania: Symphony of
the Night (USA)**, whose addresses come from the sotn-decomp decompilation. The prologue's
dialogue is in Arabic: Richter and Dracula in the throne room of 1792, up to the last battle (6
messages), with both names. The game types a line by copying fixed 8x8 cells of its font into an
image of the line in video memory, too small for Arabic letters, so the Arabic takes a fourth
rendering strategy, `composed-lines`: two MIPS hooks take the glyph and name calls, compose each
Arabic glyph (up to 16 pixels wide) into an image of the line in RAM at a pen that starts at the
line's right edge, and send the line to video memory; the lines are 16 rows apart, three to the
box, as in the game's PSP version. The prologue's stage file grows past its sectors, so the overlay
writes a new one to the empty sectors at the end of the data track, every sector with its EDC and
ECC (`patching.cdrom`), and points the game's table of stages and the ISO 9660 record at it; the
CUE sheet and the audio track stay as they are, and the data track's patch is about 10 KB. The
research tools run the game in Beetle PSX from its CUE sheet. See
[the Symphony of the Night testing guide](docs/SOTN_ARABIC_TEST_AR.md) and
[the renderer notes](docs/SOTN_ARABIC_RENDERER.md).

The seventeenth reference target, and the second on the PlayStation, is **Gran Turismo (USA)
(Rev 1)**, which no decompilation covers: its formats and addresses were read from the disc and
from the race program's code in memory. Three license test briefings are in Arabic, chosen to be
unlike (B-1, B-3 and B-8: a number with a thousands comma, the longest body, the widest title);
the other 21 stay in English. The game draws a briefing with its own proportional fonts, so the
Arabic takes the `glyph-font` strategy: its glyphs take the Latin-1 codes of the two fonts the
briefings use, drawn into the fonts' shared page over the Latin-1 letters the US game never
draws, white with a black outline, 10 pixels for the paragraphs and 18 for the title; at 10
pixels merged dots are drawn apart. One MIPS hook, written over the layout's word loop, draws a
word whose first glyph is Arabic at the mirror of the place the game gives it, so the game still
breaks, indents and justifies the lines and English text is drawn as before. The race program
is packed with PSLZ and the font page with GT-ZIP (both in `rebuild`); each is packed again in
its original's place, keeping the original's bytes wherever nothing changed, so every file keeps
its sectors and the patch is about 45 KB. See
[the Gran Turismo testing guide](docs/GRAN_TURISMO_ARABIC_TEST_AR.md) and
[the renderer notes](docs/GRAN_TURISMO_ARABIC_RENDERER.md).

The eighteenth reference target, and the third on the PlayStation, is **Ridge Racer (USA)**,
which no decompilation covers either. Three strings of its program are in Arabic, chosen to be
unlike: the title screen's prompt, the main menu's help line with the pad's buttons and the
shadow the game draws under it, and the memory card screen's title in the large chrome font;
every other string stays in English. The game draws a string a character at a time, a fixed
cell apart, from fonts of capitals whose pages are full, so the Arabic takes the `glyph-font`
strategy with fonts of its own. One MIPS hook takes both text routines: a string whose first
byte is a placement (centred on the English, or ending at its mirror) is drawn from glyphs of
any width, and any other string goes to the game as before. The glyphs, 11 pixels in the
text's colour with every stroke two pixels wide like the game's capitals, and 18 pixels in the
large font's chrome with a black outline, go to a corner of VRAM the game leaves free, uploaded
once. The hook and the glyphs live in zeros of the program's data that nothing uses, so the
program keeps its size and its sectors and the patch is under 4 KB. See
[the Ridge Racer testing guide](docs/RIDGE_RACER_ARABIC_TEST_AR.md) and
[the renderer notes](docs/RIDGE_RACER_ARABIC_RENDERER.md).

The nineteenth reference target, and the first on the Super NES, is **Chrono Trigger (USA)**.
Its text engine was read from the ROM, its 65C816 code and the game running, then checked
against the [dscotton/ct_disassembly](https://github.com/dscotton/ct_disassembly) disassembly,
which names the same routines and tables. The game keeps its dialogue in fifteen string
tables, one for a run of its locations, and the translation takes them table by table:
three are in Arabic, 2058 messages of Crono's house and Truce in both eras, Truce Canyon,
Lab 32, the Proto Dome, the Sun Keep, the Geno Dome, Leene Square with the Millennial Fair,
the trial, the castle's cellars, Melchior's hut, the Tyrano Lair, the Lavos crater, Zeal,
Death Peak, Castle Guardia in 600 and 1000, the domes of 2300 A.D., Medina, the End of Time,
Ozzie's and Magus's scenes and the Blackbird, with their choices, pauses and the boxes that
go on without the button. The game
draws its dialogue with a variable-width font of 12x12 pixels into a buffer of tiles, so the
Arabic takes the `glyph-font` strategy with a font of its own, white with the game's shadow,
9 pixels. The ROM's 4 MiB are full, so the overlay grows it to a 6 MiB ExHiROM, the upper
half of each added bank mirroring the ROM's first banks as the console read them before, and
keeps its font, its tables and the Arabic in the lower halves. Four 65C816 hooks, assembled
with cc65, send a translated message to its Arabic through a list of the translated tables,
draw each Arabic glyph at the mirror of the pen and a name the game writes as a block left
to right, and put the choice cursor at the box's right; the English messages stay as they
were. The research tools run the game in snes9x. See
[the Chrono Trigger testing guide](docs/CHRONO_TRIGGER_ARABIC_TEST_AR.md) and
[the renderer notes](docs/CHRONO_TRIGGER_ARABIC_RENDERER.md).

The twentieth reference target, and the second on the Super NES, is **The Legend of Zelda: A
Link to the Past (USA)**. Its text engine was read from the
[spannerisms/usdasm](https://github.com/spannerisms/usdasm) disassembly, which assembles to
this ROM, checked against the ROM's bytes and run in snes9x. Three messages of the opening are
in Arabic, chosen to be unlike: Zelda's call, six pages that wait and scroll in the window
without a frame; the uncle's words, which start with the name the player gave; and the lamp's,
an item's. The game draws its dialogue with a variable-width font of 8x16 pixels into three
lines of tiles, so the Arabic takes the `glyph-font` strategy with a font of its own, 16x16,
white strokes with the game's dark outline, 11 pixels. The ROM is full, so the overlay adds a
second MiB for the font and the messages. Four 65C816 hooks in free bytes of the engine's bank,
assembled with cc65, parse a translated message from its Arabic, draw each glyph at the mirror
of the pen and the name as a block left to right, and move the lines against the window's right
side; the English messages stay as they were, and the patch is about 4 KB. See
[the A Link to the Past testing guide](docs/ALTTP_ARABIC_TEST_AR.md) and
[the renderer notes](docs/ALTTP_ARABIC_RENDERER.md).

The twenty-first reference target, and the first on the Mega Drive, is **Shining Force II
(USA)**. Its text engine was read from the
[ShiningForceCentral/SF2DISASM](https://github.com/ShiningForceCentral/SF2DISASM)
disassembly, which assembles back into this ROM, checked against the ROM's bytes and run in
Genesis Plus GX. Three strings of the witch who starts a new game are in Arabic, chosen to be
unlike: her greeting, which clears the window and waits; her question, three English lines
laid out again as two; and her word on the name the player gave, which starts with it. The
game decodes its strings from Huffman code a symbol at a time and draws them with a
variable-width font of 15 rows, a bit a pixel, so the Arabic takes the `glyph-font` strategy
with a font of its own in the same format, one colour, 10 pixels, and strings stored
uncompressed. Four 68000 hooks, assembled with GNU binutils, in the free bytes at the end of
the section that holds the text, send a translated string to its Arabic, draw each glyph at
the mirror of the pen and a name as a block left to right, and move the waiting arrow to the
window's left; the English strings stay as they were, the ROM keeps its size, and the patch
is about 2 KB. See [the Shining Force II testing guide](docs/SF2_ARABIC_TEST_AR.md) and
[the renderer notes](docs/SF2_ARABIC_RENDERER.md).

The twenty-second reference target, and the third on the Super NES, is **Final Fantasy II
(USA, Rev 1)**. Its text engine was read from the ROM's own 65C816 code, checked against the
[everything8215/ff4](https://github.com/everything8215/ff4) disassembly, which rebuilds this
revision and names its routines, and run in snes9x. Six messages of the opening on the deck of
the Red Wings' airship are in Arabic, with the fourteen characters' names the game writes in
them: short exchanges that write the captain's name, and Cecil's answer over four pages. The
game writes each code of a message straight into the tilemap as a tile of its 256-tile font,
26 tiles a row under a blank row, so the Arabic takes the `glyph-font` strategy with forms
drawn into cells of 8x16 pixels, 12 pixels, white on the window's blue, each cell's halves
tiles of their own among 146 free codes: the pair codes, blank in the font, and the letters'
codes, whose Arabic tiles a hook loads over the Latin letters while an Arabic page shows. The
overlay adds a second MiB for the hooks, the tiles and the messages. Seven 65C816 hooks in the
added bank, assembled with cc65, read a translated message from its Arabic, take a pair code
as a glyph's half, mirror each row whole when a page is decoded (the game's icons and digits
turned back), write a character's name from the translation's own, and swap the letters'
tiles by DMA; the English messages stay as they were, and the patch is about 4 KB. See
[the Final Fantasy II testing guide](docs/FF4_ARABIC_TEST_AR.md) and
[the renderer notes](docs/FF4_ARABIC_RENDERER.md).

The twenty-third reference target, and the fourth on the Super NES, is **Final Fantasy III
(USA)**, the Super NES release of Final Fantasy VI. Its text engine was read from the
[everything8215/ff6](https://github.com/everything8215/ff6) disassembly, which rebuilds this
ROM and names its routines, checked byte by byte against the ROM and run in snes9x. It is
the first target translated chapter by chapter to a whole game: the dialogue's 3077 messages,
the opening through the ending in eleven chapters, are in Arabic, with the
fourteen characters' names the game writes in them: the dialogue on the cliffs, the centred
narration over the Magitek walk, Narshe's town and mines, Arvis's house, Kefka's and the
Empire's scenes, Locke and the Moogles, then Figaro Castle and its dive under the sand, South
Figaro, Mt. Kolts and Sabin, the Returners' hideout and Banon, the raft's three-way prompts,
and the three scenarios (Locke and Celes, Banon's party, Sabin's road through Doma, the
Phantom Train, the Veldt and Nikeah), the beginner's classroom, the battle for Narshe and
Terra's flight, then Kohlingen, Jidoor, Zozo and Ramuh, the Opera House with its arias and
Setzer's coin, then Vector, the Magitek Research Facility with Ifrit, Shiva, Cid and Kefka,
the escape on the airship and Maduin's story, then Narshe's plan, the sealed gate, the
Espers' rush on Vector, the Emperor's banquet and Albrook, then the voyage to Thamasa, Strago
and Relm, the Espers, Leo's death and the Floating Continent, then the world of ruin: Celes's
island, Mobliz, Nikeah, Figaro Castle and the Ancient Castle, the Colosseum, Daryl's tomb (its
letter puzzle made a word puzzle), Cyan's letters, Gogo and the Phoenix, Narshe's Tritoch, Jidoor's
auction, Owzer and Relm, Cyan's dream, Gau's father, Thamasa and Hidon, Kefka's tower, his speech
and the ending. Three messages that write an item, a spell or a sum with the game's own letters
stay English. The game draws
a letter a frame with a variable-width font into cells of 16x16 pixels sent to the text's
tiles in the vertical blank, so the Arabic takes the `glyph-font` strategy with a font of the
overlay's own: forms of 16x15 pixels, 12 pixels, white with a black shadow on the window's
blue, each stored in nine pre-shifted variants so a hook draws at any pixel without shifting.
The overlay adds a fourth MiB: a table with an entry for each of the game's 3084 messages,
two banks of glyphs and thirteen of Arabic text, room for the whole dialogue. Eight 65C816
hooks in the added bank, assembled with cc65, read a translated message from its Arabic
through the table, lay each line out whole from the box's right edge into a buffer of tile
columns the first time the engine reaches it and send it by DMA in the vertical blank, while
the engine keeps walking the line's codes so its pauses, button waits, pages and choices work
as before; each choice's cursor takes the cell the layout kept for it, so two choices may
share a line, and a character's name comes from the translation's own table. The English
messages stay as they were, and the patch is about 195 KB. See
[the Final Fantasy III testing guide](docs/FF6_ARABIC_TEST_AR.md) and
[the renderer notes](docs/FF6_ARABIC_RENDERER.md).

See [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md).
