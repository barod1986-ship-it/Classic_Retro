# Pokémon Mystery Dungeon: Red Rescue Team Arabic Renderer / Font v1

Target: *Pokémon Mystery Dungeon: Red Rescue Team* (USA, Australia). The
decompilation [pret/pmd-red](https://github.com/pret/pmd-red) (commit
`89c65d9c152b9aab37abe660c14e4505e9bd941a`) builds this exact image and was used to
find everything below, but its data is still extracted from the original image, so
this is a binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 33554432 bytes |
| SHA-1 | `9f4cfc5b5f4859d17169a485462e977c7aac2b89` |
| SHA-256 | `ad316814c77ed083734d816ebcde2ece390efae8d15bcb6c66d7c2862d82eb68` |
| Game code | `B24E` (`POKE DUNGEON`) |
| Output | 32 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Strings.** NUL-terminated, uncompressed, reached through plain pointers: the
  personality test's floating messages from ground-script commands (`0x37`,
  pointer at +12), each question from its `PersonalityQuestion` (`{text,
  answers, effects}`, table `gPersonalityQuestionPointerTable` at `0x080F2624`),
  each answer from its `MenuItem` (`{text, action}`). `#` starts a format command
  (`#+` centre, `#W` wait for a key, `#P` new box, `#C` + byte colour...), `$` a
  placeholder filled by `FormatString`, `~XX` a character by hex code (the script
  writes `,` and `'` this way), `0x81..0x84` and `0x87` two-byte characters;
  `engines/pmd.py` decodes all of it.
- **Typewriter.** `DrawDialogueBoxString_Async` prints one glyph per frame through
  `DrawCharOnWindow`: the cursor starts at x = 4, `\n` goes back to 4 and 11 pixels
  down, and a box holds three lines. `#+` sets the cursor to
  `(window.width * 8 - GetStringLineWidth(rest)) / 2`. `#W` places the key arrow
  at `window.x * 8 + x - 2`. The personality test's floating text is the same
  typewriter in a borderless window (26 tiles at column 2, row 8) whose arrow is
  fixed at (112, 120).
- **Menus.** A dialogue menu (the answers) is a window `widest / 8 + 2` tiles wide,
  right-aligned at column 28; `sub_8012EBC` prints each item at x = 8 after a
  `#C` colour prefix, and the cursor is a sprite at `window.x * 8 + unk4`.
- **Glyphs.** `DrawCharOnWindowInternal(windows, x, y, chr, color, windowId)` looks
  the code up with `GetCharacter` (a binary search in the current charmap), ORs
  `gCharHeight` rows (11) of 12 four-bit pixels into the window's tiles and returns
  the glyph's width. In a plain glyph an ink pixel is `0xF`; the colour comes from
  `gUnknown_80B853C[color]`, and style bit 1 adds a drop shadow right and
  down-right of each ink pixel in the colour of `gTextShadowMask` (8, dark grey, in
  floating text; 3, black, in boxes). Nothing else draws text glyphs: the three
  calls of `DrawCharOnWindowInternal` (in `DrawCharOnWindow` and twice in
  `DrawStringInternal`) are the only ones, and no pointer to it exists.
- **Charmap.** `LoadCharmaps` opens `kanji_a` in the system archive: a `SIRO`
  header (`0x0830F66C`) points to `{473, entries}` (`0x083191B0`); entries
  (`0x08317B84`) are `{bitmap, code, width, byte 8, style}` sorted by code;
  bitmaps are 72 bytes (12 rows, three halfwords each). Byte 8 is 0 in every
  glyph and read by no code. Codes `0x84XX` other than `0x8486`/`0x8487` are free.
- **Free space.** The code and its IWRAM copy end at `0x08272B3C`; `0xFF` padding
  follows up to the data at `0x08300000` (566 KB, within `BL` range of all code).

## ROM layout

| Address | Content |
|---------|---------|
| `0x08272C00` | Thumb hooks (`src/classic_retro/rom/pmd_arabic_hooks.s`, 308 bytes) |
| `0x08273000` | New charmap: `{625, entries}`, the 473 original entries unchanged plus 152 right-to-left ones (sorted), then the right-to-left bitmaps |
| `0x08280000` | Translated strings, each on a word boundary |
| `0x0830F670` | `kanji_a`'s `SIRO` data pointer, now `0x08273000` |

The overlay checks that `0x08272B3C..0x08300000` is still `0xFF`, the charmap, the
game's widths of the copied punctuation, and every original byte it replaces,
before writing. The English strings stay where they were; only the pointers to
them change (a scan of the image finds no other pointer to any of them).

## Right-to-left mode

A right-to-left glyph is a charmap entry whose byte 8 is 1. The translated strings
use only such glyphs, spaces included, stored in paint order (the first glyph of a
line is its rightmost one). The game's cursor still advances left to right; when
it draws a right-to-left glyph, `hook_draw` moves it to the mirror of the cursor
inside the glyph's own window:

```text
draw_x = window.width * 8 - x - glyph.width
```

The game's left margin (4) becomes a right margin, a line end returns to the right
edge, and `#+`'s centring stays centred. For these glyphs `hook_draw` also:

- draws 12 rows instead of `gCharHeight`'s 11 (the Arabic letters need them);
- limits the shadow to the bits of the ink colour. The game ORs pixels, and joined
  letters touch: a shadow falling on the neighbour's stroke must not change its
  colour (white 7 | grey 8 would give 15, light blue). In boxes the shadow stays
  black (3); on the floating text's black background there is none.

`hook_draw` also records in the padding byte at `0x47` of the window whether the
last glyph drawn there was right-to-left. After right-to-left text the `#W` arrow
goes to the left of the last glyph (`window.x * 8 + window.width * 8 - x - 14`: the
16-pixel arrow has ink in columns 3..13), and a right-to-left menu's cursor goes
to its right edge (`window.x * 8 + window.width * 8 - 8`), flipped to point left.
English text never sets the byte, so everything else is drawn as before.

## Hooks

| Site | Original | Hook |
|------|----------|------|
| `0x08007454` | `00 F0 08 F8` (`DrawCharOnWindow` → `DrawCharOnWindowInternal`) | `hook_draw` |
| `0x080090D0` | `FE F7 CA F9` (`DrawStringInternal` → `DrawCharOnWindowInternal`) | `hook_draw` |
| `0x0800911A` | `FE F7 A5 F9` (`DrawStringInternal`, spaced digits) | `hook_draw` |
| `0x0800931A` | 16 bytes computing `arrowSpritePosX` (`HandleCharFormatInternal`, `#W`) | `BL hook_wait_arrow`, `B 0x0800932A` |
| `0x08013690` | 12 bytes computing `cursorArrowPos.x` (`UpdateMenuCursorSpriteCoords`) | `BL hook_cursor_x`, `B 0x0801369C` |
| `0x080132D2` | `F1 F7 ED FE` (`AddMenuCursorSprite_` → `AddSprite`) | `hook_cursor_sprite` (sets the sprite's horizontal flip) |

`classic-retro pmd check-hooks` re-assembles the source with GNU binutils and
compares the result with the bytes stored in `pmd_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 152 glyphs under `0x8440..0x84DF`: a 4-pixel space, the game's own `.`, `!`,
  `:`, `-` and `0`..`9` moved one row up onto the Arabic baseline, and the 133 forms
  of the shared repertoire (Arabic-Indic digits included), with two codes for the
  final and isolated seen and sheen.
- Size is the largest whose forms fit the 12x12 cell around the row-8 anchor
  (letters end on row 7): 9 px for the reference font. At that size hamza and
  madda above alef reach above the cell or touch the alef, so these four forms are
  the font's alef cut one row below a small drawn hamza (rows 0-1) or madda (row
  0). Seen and sheen (final and isolated) are 13 pixels wide: each is drawn as its
  right 12 pixels, then the rest. `،` and `؛` are drawn as slanted Kufi commas.
- Medial and final forms end at their last ink column, so joins touch the glyph
  painted before them; glyph pixels never leave a glyph's own width otherwise.

## Translations

The script (`src/classic_retro/translations/pmd-red.json`; its originals are pinned in
`src/classic_retro/rom/pmd_arabic_script.py`) covers the whole personality test that a
new game starts with: the six floating messages (from the welcome to the start of
the interview), all 56 questions (55 drawn at random, eight per
game, plus the second half of the alien invasion) with their answers, and the
gender question: 158 strings behind 206 pointers (the yes and no answers are shared by
most questions). For each string:

1. its ROM address, the SHA-256 of its bytes and its command skeleton are pinned,
   with every pointer to it; the ROM build refuses a different script;
2. the Arabic commands (`{CENTER_ALIGN}`, `{WAIT_PRESS}`, `{EXTRA_MSG}`) must equal
   the original's, in order; only line ends may move;
3. every line is measured: at most 200 pixels in the floating text and the
   dialogue box (26 tiles with 4-pixel margins), 160 in a menu, and three lines per
   box.

## Verification

In mGBA, with the patch built from the reference font: the six floating messages
(centred, no shadow on black), every question forced in turn with all its pages
and its menu, the `#W` arrows left of the text, the alien invasion's second
question after answering "Fight", and the gender question. The main menu and the
Adventure Log (English) are pixel-identical to the original image with the same
input.

## Limits

- Placeholders (names, numbers, items), colour commands and brackets are refused in
  Arabic text: a runtime name would be drawn left-to-right over the mirrored text.
- No harakat; one font size (9 px) in a cell whose lines are 11 pixels apart, so
  a final yeh's dots may touch a hamza on the line below.
- Everything after the gender question (the personality reveal, the partner, the
  story) and the game's menus are still English.
