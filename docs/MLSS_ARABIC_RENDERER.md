# Mario & Luigi: Superstar Saga Arabic Renderer v1

Target: *Mario & Luigi: Superstar Saga* (USA). The decompilation
[jellees/mlss](https://github.com/jellees/mlss) (commit
`b03634c2c700a3ae78f39e576cc88a45c3a724fd`) builds this exact image, but most of its
code is still raw disassembly and its data is extracted from the original. The text
engine facts below come from the image's own code, checked in mGBA;
[Yoshi Magic](https://github.com/CaptainSwag101/YoshiMagic) (commit
`d0c80ed32481048e1259190e9e51d0e5707ec71c`) confirmed the command lengths. This is a
binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 16777216 bytes |
| SHA-1 | `7c303cdde5061ee329296948060b875cb50ba410` |
| SHA-256 | `af9066e7eacdab919e92987db8856d038e4b75d4ed011259c893702085a886be` |
| Game code | `A88E` (`MARIO&LUIGIU`) |
| Output | 16 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Story text table.** `0x084E8898` holds 2434 groups of five pointers, one message
  per language (English, French, German, Italian, Spanish: the USA image carries them
  all). The game picks one by the language byte of its state (`0x080E9310`), English
  in the USA game.
- **Messages.** Two header bytes, then the text, then zeros up to a word boundary:
  bytes are characters of the printer's font, `0xFF` starts a command of two bytes, or
  three for `FF 01` and `FF 0B`..`FF 11` (`FF 00` new line, `FF 01 00` new page,
  `FF 0A` end, `FF 0B 01` page start, `FF 0C nn` wait, `FF 11 01` wait for a key,
  `FF 2n` colour, `FF 3n` double height/width, `FF 34`..`FF 36` left/centre/right,
  `FF 4n` font list, `FF 5n` space width, `FF 6x`..`FF 9x` pen moves). The measuring
  pass stops at the first zero, so a stored message is always followed by one.
- **Header.** The width of the widest line and the height of the tallest page, in
  tiles; the game sizes the speech bubble or the subtitle box from them. A line is as
  tall as its tallest glyph (12 pixels, 24 doubled) and pages end at `FF 01`: this rule
  (`engines.mlss.measure_text`) gives the header of 2392 of the 2434 English messages,
  and the build checks it on every message it replaces.
- **Glyph printer.** `0x08199624` prints one character per call into a 4bpp tile
  buffer, through blitters copied to IWRAM (one per glyph width, 8, 12 or 16 pixels,
  and per doubling). Its state: +0 buffer, +4 font list, +8 text pointer, +12 pen x,
  +13 pen y, +14 left margin, +15 right margin, +18 flags (bit 0 double height, bit 1
  double width, bits 2-3 alignment, bit 4 proportional), +19 box width in tiles. At a
  line start it measures the line (`0x08199A28`) to centre or right-align it.
- **Font lists.** Each printer has a list of six fonts; a byte `0xFA`..`0xFE` before a
  character selects font 5..1, any other character uses font 0. The three lists of
  the USA image (`0x0851F9A0` for the speech bubbles, `0x0851F9B8` for the subtitles
  after `FF 41`, `0x0851F9D0`) have only font 0; all the measuring passes select fonts
  the same way, and no English message uses a byte above `0x7F`.
- **Fonts.** A word whose low byte gives the cell (bits 4-7 width, bits 0-3 height, in
  4-pixel units), 256 width nibbles, then 256 glyphs of two bitplanes: for each group
  of four rows, a word per plane where nibble `x` is column `x` and bit `k` row `k`;
  columns 8 to 15 come after the first eight. Plane 0 takes the text colour, both
  planes the colour after it: ink and light grey in a bubble, white and blue in the
  subtitles. The game's fonts are 8x12.
- **Free space.** The ROM holds 2.5 MB of zeros from `0x08CDD2E8` up to the embedded
  Mario Bros. image at `0x08F50000`.

## Right-to-left text

1. `engines/mlss_arabic.py` builds a **right-to-left font** of 16x12 cells: every
   contextual form of the shared repertoire, drawn from the reference font, plus
   copies of the game's own punctuation and digits. It becomes font 1 of the three
   lists, so a translated character is `FE xx`, and the game's measuring passes, the
   bubble sizes, the headers and the centring of the subtitles count it like any
   glyph.
2. A translated message holds only these glyphs, its own space included, in
   right-to-left paint order: the first glyph of a line is its rightmost one.
3. `hook_draw_x` replaces the code of the printer that computes where a glyph is
   drawn. For a glyph of the right-to-left font it mirrors the pen inside the text
   area:

   ```text
   draw_x = box_width * 8 + left_margin - right_margin - pen_x - drawn_width
   ```

   The pen still advances left to right: the typewriter reveals a line from the
   right, a left-aligned line starts at the right margin, a centred line (`FF 35`,
   every subtitle) stays centred, and doubled glyphs (`FF 31`, `FF 33`) mirror with
   their doubled width.
4. Every other glyph is drawn exactly where it was (the hook computes the original
   value), so English text is unchanged.

## ROM layout

| Address | Content |
|---------|---------|
| `0x08D00000` | Thumb hook (`src/classic_retro/rom/mlss_arabic_hooks.s`, 72 bytes) |
| `0x08D00100` | Right-to-left font: header `0x43`, widths, 256 glyphs of 48 bytes (12420 bytes) |
| `0x08D04000` | The 12 translated messages (996 bytes) |
| `0x0851F9A4`, `0x0851F9BC`, `0x0851F9D4` | Font 1 of the three lists, now `0x08D00100` |
| 12 story groups | Their English pointer, now the Arabic message |

The overlay checks the input hash, the printer's code at the hook site, the three font
lists (font 0, then five empty slots), the three game fonts' headers, that the padding
is still zero, and for every translated message its group, the SHA-256 of the original
and its command skeleton, and that the game's header rule gives its header. After
writing it reads the font and every message back, measures every message with each
font list as the game would, and checks that the other four languages of every group
keep their pointers.

## Hook

| Site | Original | Patch |
|------|----------|-------|
| `0x0819975C` | 16 bytes of the printer's pen-x code (`ldrb r4, [r5, #12]` ...) | `bl` to a veneer, `b 0x0819977A`, `nop`, then the veneer: `ldr r0, =hook_draw_x; bx r0` |

The hook area is out of `BL` range from the printer, hence the veneer inside the
replaced code. `classic-retro mlss check-hooks` re-assembles the source with GNU
binutils and compares the result with the bytes stored in `mlss_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 150 glyphs, `FE 21`..`FE B6`: a 4-pixel space, 16 copies of the game's glyphs and the
  133 forms of the shared repertoire (Arabic-Indic digits, `،`, `؛` and `؟` included).
- Size 10 on a baseline at row 9, so the letters end on row 8 like the game's; that is
  the largest size whose forms fit 12 rows once two of them are adjusted: hamza above
  alef (`أ` isolated and final) is the font's alef cut one row below a small drawn
  hamza, and final and isolated yeh are raised by a row (their dots reach row 12), the
  final one keeping a pixel on the joining row.
- Coverage from 140 of 255 is ink (plane 0), from 60 the next colour (both planes).
  Medial and final forms end at their last ink column, touching the glyph painted
  before them; nothing is drawn past a glyph's advance.
- The copies (`.`, `!`, `:`, `-`, `0`..`9`, `«`, `»`) are the speech bubbles' glyphs,
  widened so that a column stays free after their ink (the game's glyphs keep theirs on
  the left). The guillemets are swapped: in right-to-left text the opening one is
  painted first, on the right, pointing right.

## Translations

The script (`src/classic_retro/translations/mlss.json`; its originals are pinned in
`src/classic_retro/rom/mlss_arabic_script.py`) covers the opening, from a
new game to the first battle: 12 messages.

- Princess Peach's castle, subtitles: the Beanbean ambassador arrives, her wish and
  her gift, and her laugh (4 messages, 6 pages).
- The Mario Bros.' house, speech bubbles: the Toad's news for Luigi, the call for
  Mario, the line when the player tries to take the Toad out of the house, the humming
  at the bathroom door, the scream and the stammered news (7 messages).
- The castle again: Bowser's taunt before the battle (1 message).

For each message its group, its address, its SHA-256 and its command skeleton are
pinned; the Arabic keeps every command in order (line ends after text may move, the
empty first line of every subtitle page stays). The Beanbean Kingdom is
"مملكة الفاصولياء" and Queen Bean "ملكة الفاصولياء"; the Kingdom Courier is rendered as
the kingdom's newspaper, and Bowser's "Super Coward Bros." as "الجبانان الخارقان".

## Verification

In mGBA, with the patch built from the reference font, from a fresh boot: New Game, all
six subtitle pages (centred on the black bar, shown whole), the three bubbles before the
house (double-height and double-size text), the Toad's line at the front door, the
walk to the bathroom (humming, the scream, the two stammered lines), and Bowser's three
lines, each revealed from the right. The title screen, the file select screen and the
battle tutorial that follows (English bubbles, a Yes/No choice, coloured words, button
icons, the battle menus) are pixel-identical to the original image with the same input
(108 frames compared).

## Limits

- Only the opening up to the first battle is in Arabic; the battle tutorial, the menus
  and the rest of the game are in English.
- Arabic messages cannot hold Latin letters (the right-to-left font has digits and
  punctuation only) or names printed at run time.
- No vowel marks, one font size, and no lam-alef ligature (lam and alef are separate
  forms).
- The bubble's key arrow stays in its bottom-right corner.
