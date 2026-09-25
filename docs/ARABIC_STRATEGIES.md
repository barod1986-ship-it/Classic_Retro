# Arabic Rendering Strategies

Version: 1

The twelve reference targets put Arabic on screen with three rendering strategies.
They are a starting set, not a closed list. Engines on other platforms will need
other methods, and the registry (`classic_retro.localization.strategies`) accepts
them the same way it holds these three:

```text
classic-retro targets strategies    # every registered strategy and the targets that use it
```

A strategy says how Arabic glyphs reach the screen. Around it, each target also
chooses how its renderer runs right to left, how right-to-left text is marked, where
the glyphs get their codes, and how runtime names are handled. These choices are
listed below with the targets that made them, so the next target can start from what
already worked.

## The strategies

### `glyph-font`: right-to-left glyph font (proven)

Used by: `firered`, `minish-cap`, `ff6a`, `golden-sun`, `fire-emblem` (dialogue),
`pmd-red`, `mlss`, `advance-wars`, `metroid-fusion`, `tactics-ogre`.

Every contextual form of the letters (the 133 presentation forms of
`arabic/repertoire.py`) is drawn from the reference font into the game's own font
format. Translated text is shaped, run through bidi, and stored as those glyphs in
right-to-left paint order (`arabic/paint.py`): the first glyph of a line is its
rightmost one. The renderer then places the glyphs from the right edge of the line.

- The engine needs glyphs of their own width (a proportional font, or cells the
  forms fit), spare character codes or a way to add a font next to the game's, and
  one place that decides where a glyph is drawn.
- It is small: one glyph per form, and text stays text. The game's own measuring
  keeps sizing boxes and centring lines.
- There are no ligatures (lam and alef stay separate forms) and no kerning. A
  retro font may not hold the ligature glyphs (see [ARABIC_PIPELINE.md](ARABIC_PIPELINE.md)).
  A target whose font can hold them may opt in.

### `line-cells`: pre-drawn line cells (proven)

Used by: `mmbn`, `fomt`.

The engine draws fixed-width cells (a monospace 8x16 font), which Arabic cannot use
one letter per cell. Every translated line is shaped with HarfBuzz
(`font/shaped_text.py`), drawn whole with the reference font, and cut into the
engine's cells from its right end. The cells get codes of their own and a hook draws
cell *n* of a line in the mirrored column.

- The engine needs fixed-width cells, enough codes and tile memory for the distinct
  cells, and one place that decides a character's column.
- You get full HarfBuzz shaping: ligatures, kerning, and letters joined across
  cells.
- The text is fixed at build time. A runtime name is an island drawn with the game's
  own glyphs.
- Each distinct cell costs ROM space and a code. Mega Man Battle Network gives
  every page its own bank. Harvest Moon uses one bank for the whole script, with
  room for 2079 cells.

### `text-images`: pre-drawn text images (proven)

Used by: `fire-emblem` (the seven images of the opening legend).

Text the game shows as pictures (subtitles, title cards, legends) is shaped with
HarfBuzz and redrawn in the game's own image format and palette.

- No hook is needed: the new images replace the originals through the game's image
  table.
- Every image must fit the original's budget: its size, colours and VRAM.

## Turning the renderer right to left

| Way | How | Targets |
|-----|-----|---------|
| Mirrored draw | The game's pen keeps advancing left to right. Only where a glyph (or cell) is drawn moves to the mirror of the pen inside the line: `draw_x = left + right - pen - width`, or column `27 - x` for 28-column cells | `minish-cap`, `ff6a`, `golden-sun`, `fire-emblem`, `pmd-red`, `mlss`, `mmbn`, `fomt`, `metroid-fusion`, `tactics-ogre` |
| Mirrored tilemap | The game draws the line left to right into its tiles as usual; each tile column goes into the tilemap at its mirror inside the text area, with the hardware's horizontal flip, and the glyphs are stored flipped | `advance-wars` |
| Reversed pen | The pen starts at the line's right edge and subtracts each advance before drawing. Newline, page clear and scroll restore the right edge | `firered` |

Mirrored draw became the default. It changes one point of the renderer, and the
game's measuring, wrapping, centring, choices, typewriter and scrolling keep their
meaning, so the typewriter reveals Arabic from the right with no further change.
Where the game's routine composes a glyph in a scratch column and writes whole
columns (Tactics Ogre), a mirrored glyph cannot share its columns: the hook takes
every glyph of a right-to-left message, the space included, ORs it into the
cleared tiles at its mirrored place and moves the game's pen as the routine would.
Reversed pen needs control over every place that moves or resets the pen. FireRed
had that through its decompilation. Mirrored tilemap suits a printer that draws a whole
line into a strip of tiles, where no single point places a glyph (Advance Wars): the
tilemap write is that point, and the flip keeps the glyphs' pixels untouched. All three
are valid. A renderer that allows neither
may need a third way, and that should be recorded here when it appears.

Things that sit outside the text also need mirroring. Examples are a menu cursor
(`pmd-red` moves it to the window's right edge, flipped), a key or page arrow
(`firered` and `pmd-red` place it left of the text, `metroid-fusion` at the other end
of the bottom line), a typing cursor (`metroid-fusion` keeps it left of the text), an
effect tied to the pen's tiles (`metroid-fusion` fades each tile of a monologue page
in at its mirrored column) and a choice between options (`metroid-fusion` puts the
cursor at each Arabic option and swaps the left and right keys).

## How right-to-left text is marked

| Marker | Targets |
|--------|---------|
| Direction control codes the source overlay adds (`FC 19 xx` / `FC 1A`, `04 16` / `04 17`) | `firered`, `minish-cap` |
| The first code of a message (`0x5FF`, `0x0B`, `0x1E`) | `ff6a`, `golden-sun`, `fire-emblem` |
| The glyph itself: a charmap flag, or a glyph of the right-to-left font | `pmd-red`, `mlss`, `metroid-fusion` (where a glyph is drawn) |
| The text's own codes or address: cell codes, a bank table sorted by text address, or the address range of the Arabic bank | `fomt`, `mmbn`, `advance-wars`, `metroid-fusion` (its cursors, arrow and fade), `tactics-ogre` |

English text never carries the marker, so untranslated messages keep the original
path. When a whole block of messages must move to reach the bank (Tactics Ogre finds a
message by a 16-bit offset from its scene's block), the copy keeps the untranslated
messages in English outside the bank.

## Where Arabic glyphs get their codes

- A free range of an existing code page: `F9 40..CF` in FireRed's extra-symbol page.
- A font of its own, selected in right-to-left mode: FF6 Advance (a second `FONT`),
  Fire Emblem (a second glyph table), Minish Cap (a font page), Advance Wars (256 codes
  of its own, drawn by the overlay's routine for text of the Arabic bank).
- Codes above the game's glyph range that the decoder is taught to keep: Golden Sun
  (`0x100 + slot`, with its own Huffman trees for the translated strings).
- Codes whose glyph, by the game's own address formula, falls in the padding at the end
  of the image: Metroid Fusion (`0xB040` up; the game reads glyph `c` at
  `sheet + 32 * c`, so only the widths need a hook). Every routine that will draw them
  must read them as glyphs: the briefings read `0x9xxx` as sounds, so the first
  build's `0x9000` had to move.
- Unused two-byte codes added to the charmap: Pokémon Mystery Dungeon.
- An empty font slot the game already selects with a prefix byte: Mario & Luigi
  (font 1 of every font list).
- Lead bytes the game pairs like Shift-JIS: Harvest Moon (`F0 40..FA FC`).
- Page banks chosen by the text's address: Mega Man Battle Network.
- The game's whole glyph range, read as a second font in text of the Arabic bank:
  Tactics Ogre (its routines read only `00..7F` as glyphs; codes 2 to 127 go to the
  forms the script uses, measured and drawn by the hooks from tables of their own).

## Runtime names inside Arabic lines

A name inserted at run time is Latin text, so it must read left to right inside the
right-to-left line.

- Expand it reversed: FireRed (`FC 1B` expands a placeholder reversed by glyph
  units), Golden Sun (a hook reverses a copied name in right-to-left messages),
  Harvest Moon (the expanders hand the name over reversed, one game glyph per
  character), Advance Wars (a hook reverses the name in place while it is drawn and
  flips each of the game's letters for the mirrored tilemap).
- Reverse the variable buffers once when a dialogue changes direction: Minish Cap.
- Static Latin words as islands in the game's glyphs: Mega Man Battle Network.
- Refused for now, with the reason in each target's notes: FF6 Advance, Fire Emblem,
  Pokémon Mystery Dungeon, Mario & Luigi.

A fixed name the game inserts from a list of its own (a character's name, not the
player's) can be Arabic instead: Tactics Ogre keeps the command (`87xx`) in the
translation and writes the script's Arabic name out in its place at build time, so the
name is shaped with the line and the list stays English for the rest of the game.

## Fitting the reference font to the game

The reference font is Noto Kufi Arabic SemiBold, with its SHA-256 pinned.

- Use the largest size whose forms fit the game's rows around its baseline:
  - 10 px for FF6 Advance, Golden Sun, Mario & Luigi, Harvest Moon and Advance Wars
  - 9 px for Pokémon Mystery Dungeon
  - 11 px for Mega Man Battle Network, Metroid Fusion and Tactics Ogre
- Draw marks that vanish at that size by hand:
  - hamza or madda over alef (Mario & Luigi, Pokémon Mystery Dungeon, Metroid Fusion)
  - hamza on a carrier (Harvest Moon)
- Or keep a dot that stays just under the ink level: its strongest pixel becomes ink
  (`draw_form(..., mark_level=...)`; Metroid Fusion's medial beh).
- Adjust a form that does not fit: raise final yeh, or split a 13-pixel seen into
  two glyphs (Advance Wars splits every form wider than its 8-pixel glyphs).
- When only the forms a script uses get codes (Tactics Ogre), choose the size over the
  whole repertoire anyway, so a new word never changes the size of the others.
- Medial and final forms end at their last ink column, so joins touch the glyph
  painted before them. An isolated form whose ink fills its advance gets one more
  pixel, so it never touches the next word. This rule lives in
  `font/glyph_raster.py`; FireRed, the first target, keeps its own older rule.
- Shadows follow the game's own. Golden Sun keeps each glyph's shadow inside its
  advance. Harvest Moon shades the whole line, so the shadow crosses cell edges.
  Metroid Fusion outlines each glyph on its eight sides, like its Latin letters, and
  leaves the outline out on a joining side, where the neighbour's ink goes on.
  Advance Wars, Mario & Luigi and Tactics Ogre draw the grey around the strokes as a
  second ink value, like their letters; Tactics Ogre leaves out the grey beyond a
  glyph's advance, since its hook ORs neighbours together.

## The shared core

What the targets do alike lives in the core. An engine's Arabic module keeps only
what is its own: cell size, baseline, limits, pixel format, shadow colours and
commands.

| Module | What it gives | Used by |
|--------|---------------|---------|
| `arabic/logical.py` | The checks on logical text: no direction controls, no presentation forms, no vowel marks where the renderer has none. Also the missing-glyph errors | Every target and the translation files |
| `arabic/glyph_codes.py` | `GlyphCodes`: the codes each form takes, in order. A form drawn as two glyphs takes two | `glyph-font` |
| `arabic/paint.py` | Right-to-left paint order. It refuses combining marks, mirrored brackets and raw newlines | `glyph-font` |
| `font/glyph_raster.py` | The largest size that fits the cell. A form drawn at a coverage threshold from its first ink column, with the joining advance. Hand-drawn marks, hamza or madda over alef, a form raised by a row, shadows inside the advance, 2-bit pixel rows | `glyph-font`, and `fomt` for its shadow |
| `font/tiles.py` | 4bpp tiles, stored row by row or column by column | `minish-cap`, `mmbn`, `fomt`, the Fire Emblem legend |
| `font/shaped_text.py` | Whole lines shaped with HarfBuzz and drawn with the reference font | `line-cells`, `text-images` |
| `font/previews.py` | The glyph atlas, a message's boxes side by side, and preview sheets | The review images of every target but `firered` |
| `text/commands.py` | Command tokens that carry their codes, and the check that a translation keeps the original's commands | Every rom overlay |

`tests/test_arabic_core.py` checks these pieces with a font drawn in the test.

## Adding a strategy

1. Describe it as a `RenderingStrategy`: an id, a title, a summary, what it needs
   from the engine, the core modules it uses, and its trade-offs. It starts as
   `experimental`.
2. Register it. In this repository, add it to `builtin_strategies()`. From another
   package, use the `classic_retro.strategies.v1` entry point group, where the
   object or a zero-argument callable returns it:

   ```toml
   [project.entry-points."classic_retro.strategies.v1"]
   texture-font = "my_package.strategies:TEXTURE_FONT"
   ```

3. Put reusable pieces in the core (`arabic/`, `font/`, `layout/`, `text/`), not in
   the target. Start from [the shared core](#the-shared-core), and list the modules
   the strategy uses in its `core` field.
4. It becomes `proven` when a target ships with it: the target is built from its
   pinned image, checked in an emulator, and its reference patch hash is recorded.

## Candidates for other platforms (not implemented)

None of these has been built or tested. They are research notes for engines the
twelve targets did not cover, and each becomes an `experimental` strategy together
with its first target.

- **Tile-composed variable-width text.** Many NES, Game Boy and SNES engines put
  one 8x8 tile per character. A hook would compose glyphs into a row of tiles at run
  time. It works like `line-cells`, but because composition happens at run time it
  can also handle names and numbers. It needs RAM for the line and free tiles in
  video memory.
- **Runtime shaping.** For text assembled at run time (names the player types,
  item lists), the game would choose the contextual form from the neighbouring
  letters while it draws, instead of receiving pre-shaped glyphs.
- **Texture or sprite fonts.** PlayStation and Nintendo 64 games often draw text
  from texture pages or sprites. The glyph set would go into the texture with the
  game's own format and palette limits. It would be `glyph-font` with another font
  format, or `text-images` for fixed screens.
- **Per-screen tile streaming.** For engines with tiny tile memory (NES CHR banks),
  `line-cells` would load only one screen's cells at a time.
