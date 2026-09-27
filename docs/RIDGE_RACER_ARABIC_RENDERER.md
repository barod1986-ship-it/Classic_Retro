# Ridge Racer Arabic Renderer v1

Target: *Ridge Racer* (USA, SCUS-94300), the third PlayStation target. No decompilation
exists; the facts below come from the disc and from the program's code, read in memory, in
VRAM and on screen in Beetle PSX with the [research tools](RESEARCH_TOOLS.md). The overlay
patches the user's disc image and ships as a BPS patch of its data track.

| Item | Value |
|------|-------|
| Redump | *Ridge Racer (USA)*: a CUE sheet, a data track and 13 audio tracks |
| Track 01 | 3683232 bytes (1566 sectors of 2352 bytes, Mode 2): CRC32 `0DE7775B`, SHA-1 `5968ee90644e6536ddf544a45fc510a7cc64bb12`, SHA-256 `087896cebcc2892be651a2f3e59d963daa35e2f861e25ab46e8ecfaf7c8e1c68` |
| Boot | `SYSTEM.CNF` boots `SCUS-943.00`; `classic-retro detect` on the CUE names the game |
| Output | Track 01, the same size; the CUE sheet and the audio tracks stay as they are. Shipped as BPS |

## Engine facts the overlay relies on

- **The program.** `SCUS-943.00` (LBA 24, 438272 bytes) is a PS-X EXE, not packed: its
  0x6A800 bytes of code and data load at `0x80010000` and hold every string of the menus
  and messages, zero-ended and padded with zeros to the next word. The textures come from
  `TEX0.TMS` to `TEX4.TMS`, which the game opens by name.
- **Two text routines.** Both take (x, y, string, palette) and draw a sprite a character
  from the character's code, from the space (`20`), which is not drawn but moves the pen:

  | Routine | Font | Page (VRAM) | Cells | Step | Ordering table | Callers |
  |---------|------|-------------|-------|------|----------------|---------|
  | `0x80027ED4` | small | (320, 0), 4 bits | `0x8005CDB8`: column and row of 8x8 cells | 8 | entry 2924 (bytes) | 67 |
  | `0x8003E230` | large | (832, 256), 4 bits | `0x800740E8`: column and row of 16x16 cells | 16 | entry 2920 | 12 |

  Each takes the next free primitive from `0x1F800000` (the scratchpad), adds its sprites
  (raw texture) to its entry of the frame's ordering table (`*0x80130EA4`), then a draw mode
  for its page with the texture window at `0x80079F88`, and leaves the next free primitive
  at `0x1F800000` and in v0. The palette is `(palette / 16 + 480) << 6 | palette & 15`,
  VRAM row 480 on; the large routine's palette −1 colours each character from six palettes
  (`0x80074168`) by its code less 32, modulo 6. A third routine (`0x80028058`) draws the
  small font faded, from two calls; the hook leaves it alone.
- **The fonts.** The small font's letters are capitals seven rows tall, strokes two pixels
  wide, in the palette's colour 1 (the rest clear); the lowercase `a`, `b` and `d` draw
  the pad's triangle, square and circle, and `c` the NeGcon's II. The large font's letters
  are chrome: a black outline (colour 2) round a fill in colours 5 to 12, bright on the top
  row and dark in the middle, lighter on the strokes' top and left edges.
- **Free VRAM.** The pages are nearly full. No TIM of the five texture files and nothing
  the game draws touches (976, 192) to (1023, 255): 48 halfwords, 192 pixels of 4 bits, by
  64 rows of the texture page at (960, 0) (the only TIM beside it is TEX0's at (960, 192),
  10 halfwords wide). It stays as uploaded through the title, the menus, a race, the game
  over, the rankings and the attract demo (checked in savestates' VRAM).
- **Free RAM.** `0x80068A00` to `0x8006AF00` (9472 bytes) of the program's data are zeros
  that belong to no object: no `lui` pair, word or `gp` offset of the program points into
  them (the last initialised byte before is `0x800689A9`), and a mark written there stayed
  through the boot, the title, the menus, the options and a race.

## Right-to-left text

The hook (`rom/ridge_racer_arabic_hooks.s`) takes the first two words of each text
routine: a jump to its entry and a nop. An entry reads the string's first byte: 1
(`CENTRE`) or 2 (`MIRROR`) makes it Arabic, and anything else goes on through the game's
routine (the entry does the routine's first two instructions and jumps to its third), so
every English string of the game is drawn as before. An Arabic string is:

```text
[mode] [parameter] [glyph codes in visual order, left to right, from 20] [00]
```

- **`CENTRE`, n:** the text is centred on the English it replaces, n characters of the
  font's step: the pen starts at x + (n × step − width) / 2. A shadow the game draws a pixel
  right and down (the menu's help line) stays a pixel right and down.
- **`MIRROR`, 128 + d:** the text ends at the mirror of the English's left edge, 320 − x,
  moved d pixels: a title left-aligned in English is right-aligned in Arabic.

The hook measures the glyphs, places the pen, and draws each glyph as a sprite of its own
width and height from its font's table (eight bytes a code from `20`: u, v, width, height,
the row offset from y), in the palette the game would give the string and in the
atlas's page, then adds a draw mode for that page as the routines do. A glyph of height 0
(the space) only moves the pen. The first Arabic string drawn uploads the atlas to VRAM
(`LoadImage`, `0x80041750`, then `DrawSync(0)`, `0x80041538`) and sets a flag; the game
never writes there, so once is enough.

## Glyphs and the atlas

The reference font is Noto Kufi Arabic SemiBold. Coverage from 128 of 255 is ink, and a
dot that stays between 60 and 128 keeps its strongest pixel. Each font's size is the
largest at which every form of the repertoire and the digits fits its cell:

| Font | Cell | Size | Glyphs |
|------|------|------|--------|
| small | 15 rows from 4 above y, the letters on the row under the English capitals | 11 px | colour 1; every stroke two pixels wide (`font.glyph_raster.emboldened`) |
| large | 26 rows from 4 above y, the letters on the English letters' baseline | 18 px | chrome as the English: fill by the row (`SHADES`), top edge 12, left edge 10; outline 2 all round but on the joining sides |

`emboldened` widens every stroke one pixel wide to two, as the game's capitals are drawn,
to the right or else to the left, inside the glyph's box so its advance does not change;
it never closes a one-pixel gap in a row nor touches another group of ink, so counters stay
open and the dots stay apart from the letter and from each other. Dots (groups under three
pixels) keep their size. The two- and three-dot letters whose dots merge are drawn apart
first (`separated_dots`), as for Gran Turismo.

The pad's buttons (△ □ ○ Ⅱ) are drawn by hand for the small font, seven rows on the
English letters' rows, and so are `.`, `:`, `!`, `-`, `،`, `؛` and `؟` (small) and `.`, `:`,
`!`, `-` (large); the digits and the other forms come from the font. The space is a blank
glyph: 4 pixels in the small font, 7 in the large.

Both fonts share the codes, `20` to `9F` (128), in the order of the characters: the space,
the buttons, the punctuation, the digits, the forms, as many as the strings use. The
glyphs of both fonts go on shelves, the tallest first, in the atlas: (976, 192) in VRAM,
u 64 to 255 and v 192 to 255 of the page at (960, 0).

## Program layout

Everything the overlay adds lives in the free RAM, so the program keeps its size and its
sectors:

| Address | Content |
|---------|---------|
| `0x80068A00` | the hook, 704 bytes (`small_entry` at `+0`, `large_entry` at `+0x30`) |
| `0x80068D00` | the upload's flag, then its RECT: (976, 192, 48, the atlas's rows) |
| `0x80068D0C` | a descriptor a font: its table, its ordering table entry, the atlas's texture page (15), its step, whether −1 cycles |
| `0x80068D30`, `0x80069130` | the small and large fonts' tables, 128 entries of 8 bytes |
| `0x80069540` | the atlas's pixels, 96 bytes a row |

| Site | Original | Arabic |
|------|----------|--------|
| `0x80027ED4` | `addiu sp,-64`; `sw ra,60(sp)` | `j small_entry`; `nop` |
| `0x8003E230` | `addiu sp,-80`; `sw ra,76(sp)` | `j large_entry`; `nop` |
| A translated string's room | the English | the Arabic string and zeros |

Anchors checked before any change: the program (SHA-256) and its header; both routines'
third words and every step the hook repeats (the scratchpad pointer, the palette formula,
the ordering table entries, the draw mode's arguments, the six palettes and the division
by 6); LoadImage and DrawSync, each naming itself to libgpu's debug print; AddPrim and
SetDrawMode; the calls that draw each translated string (x, y, the string, the routine,
the palette); the free RAM, zeros; each string's room (SHA-256). The stored hook jumps to
exactly the routines it names (`cpu.mips.jump_targets`). The program is written back to
its own sectors, each with its subheader, EDC and ECC; the build reads it back and checks
that no other sector changed.

## Translations

`rom/ridge_racer_arabic_script.py` pins three strings by address, room and SHA-256 of the
room, each with its routine, its mode and where the game draws it. The Arabic is in
`translations/ridge-racer.json`. The three were chosen to be unlike:

| Entry | String | Font | Placement | Call |
|-------|--------|------|-----------|------|
| `title.start` | `0x80010188`, room 20 | small | `CENTRE` 17 | (96, 144), palette 100, blinking |
| `menu.exit_pad` | `0x8001027C`, room 20 | small, △ and □ | `CENTRE` 18 | (88, 208) palette 100, then (89, 209) palette 285: a shadow |
| `card.load_title` | `0x80010614`, room 20 | large | `MIRROR` 128 | (32, 32), palette 124 |

The main menu shows the pad's help line when a pad is plugged in and the NeGcon's
(`0x80010268`) with a NeGcon; the Option screen draws another copy of each
(`0x80010850`, `0x80010864`), which stays English. A room holds 17 glyphs: the three take
13, 13 and 16 (16, 16 and 19 bytes with the header and the zero). They use 30 codes
(`20..3D`), 19 glyphs in the small font and 15 in the large; the atlas takes 28 rows.

## Verification

With the reference font the build matches the reference patch (3821 bytes; 6 sectors of
the program change). In Beetle PSX (`mednafen_psx_libretro`, a US BIOS in the system
directory), from power-on with the patched track, the original audio tracks and no memory
card: the title's prompt in Arabic, blinking as before; the main menu's help line in
Arabic with its buttons and its shadow; the memory card screen's title in the large chrome
font, ending on the right, in the game's cyan palette; the copyright lines, the Option
screen's help line and every other string in English as before. After a race, the game
over, the rankings and the attract demo the menu's line is still Arabic, and the atlas in
VRAM is byte for byte the one uploaded. The script, inputs only:

```text
# Core: mednafen_psx_libretro, --system-dir holding a US BIOS.
run 2400
shot title.png
# The main menu.
tap START
run 240
shot menu.png
# Option, Fastest Laps, then LOAD.
tap RIGHT
run 60
tap RIGHT
run 60
tap B
run 240
tap B
run 300
tap RIGHT
run 60
tap B
run 600
shot card.png
```

The RetroPad's B is the PlayStation's cross.

## Limits

- Three strings of the program are in Arabic; every other string stays English.
- An Arabic string keeps to its English's room: 17 glyphs in a room of 20 bytes.
- 128 glyph codes for all the strings of both fonts; the atlas holds 192x64 pixels.
- The buttons are the small font's only; Arabic text holds no Latin letters.
- The small font is 11 pixels and the large 18; no vowel marks, lam and alef stay two
  glyphs.
