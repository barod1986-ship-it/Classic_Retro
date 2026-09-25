# The Minish Cap Arabic Renderer / Font v1

Target: *The Legend of Zelda: The Minish Cap* (USA), through the
[zeldaret/tmc](https://github.com/zeldaret/tmc) decompilation pinned at
commit `d92d4581e202ae531bdcc206a7d6a90ddb8fd907`.

| Item | Value |
|------|-------|
| ROM size | 16777216 bytes |
| SHA-1 | `b4bd50e4131b027c334547b4524e2dbbd4227130` |
| SHA-256 | `bedc74df62755f705398273de8ed3bc59be610cf55760d0b9aa277f1f5035e73` |
| Game code | `BZME` |

The decompilation extracts its assets from that exact image (`baserom.gba`),
so the ROM is required to build and is never part of this repository.

## Engine facts the overlay relies on

- Glyphs are 8x16, 4 bits per pixel, stored row by row. Row 0 is the width
  marker: leading `F` nibbles are skipped columns, the following non-`F` nibbles
  are drawn columns. Pages 5 and above use two halves (16 px).
- `GetCharacter` turns ordinary bytes into page 1 glyphs and prefix bytes into
  other font pages; control codes `00`..`0F` return small command numbers.
- The dialogue canvas is one 416 px strip: line 1 is x 0..0xD0, line 2 is
  x 0xD0..0x1A0 (26 tiles per line). Two lines make a page.
- `ShowTextBox` (storybook prologue, some menus) renders whole lines at once and
  centres each measured line when `right_align` is set.
- The USA script never uses `04` sub-codes above `15`.

## New text commands

| Bytes | tmc_strings | Meaning |
|-------|-------------|---------|
| `04 16` | `{04:16}` | right-to-left painting on |
| `04 17` | `{04:17}` | right-to-left painting off |
| `04 18 xx` | `{04:18:xx}` | Arabic glyph `xx` from font page 9 |

`GetFontStrWith` treats the two direction commands as non-glyphs, so line
measurement and centring are unchanged. The stylized-font remap skips page 9.

## Right-to-left painting

Text is stored in paint order: the first glyph of a line is its rightmost one.
The engine keeps advancing its normal left-to-right cursor, so line bounds,
centring and choice positions keep their meaning; `sub_0805F7DC` only places
the pixels of each glyph at the mirrored position inside the current line
extent:

```text
drawX = left + right - cursor - glyphWidth
```

- Dialogue lines: `right = unk4`, `left = unk4 - 0xD0`.
- Text boxes: `ShowTextBox` records the measured extent of the line it is about
  to draw in `gClassicRetroArabicRtl` (EWRAM `0x0203FFF0`, above every symbol
  the game uses and cleared at boot).
- A cursor outside the extent falls back to the original left-to-right path.

The typewriter therefore reveals Arabic from right to left.

### Runtime variables

`{Player}` and the number variables are Latin runs inside Arabic lines. When a
dialogue switches direction, `ClassicRetroArabicSetVariableOrder` reverses the
bytes of those buffers once and records it in a spare `WStruct` bit.
`TextRender._66` is not free: a six-letter player name writes its terminator
into `_66[0]` (covered by a native regression test).

Text boxes do not reverse variables in v1.

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), pinned by SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`, the same
  file as the FireRed reference build. Another Arabic TTF/OTF can be passed.
- 133 presentation forms (shared repertoire with the FireRed engine) plus
  `. ! :` drawn on the Arabic baseline, because the reference font has no such
  marks and the game's Latin marks sit three rows lower.
- Size is the largest that keeps every form within rows 1..15: 10 px for the
  reference font (tallest `أ`, deepest final `ي`). Row 0 stays ink-free.
- Baseline: the Latin baseline (14) when descenders allow it, otherwise as high
  as needed; the reference font uses 11.
- Glyphs start at their first ink column. Medial and final forms end exactly at
  their last ink column so they meet the right-hand neighbour; other forms keep
  the font's advance as the gap towards it.
- Output: `data/classic_retro/arabic_font.4bpp` (128 bytes per glyph, placed
  after the last ROM section) and an inspection atlas
  `data/classic_retro/arabic_font_preview.png`.

## Translations

Translations stay logical Unicode Arabic in
`src/classic_retro/translations/minish-cap.json`, in the decompilation's text notation;
`source/tmc_arabic.py` keeps where each one goes. Before a string replaces its English
original in `translations/USA.json`:

1. its engine commands (sounds, window position, player name, continued texts)
   must match the English string in order; colours and line breaks may move;
2. the shared shaper and bidi step run per segment between ordered tokens;
3. every line is measured against its box (208 px dialogue, 240 or 120 px
   prologue), with the player name counted at 6 x 8 px;
4. `{04:17}` is emitted before any `{07:tt:ii}` continuation, so a following
   English text keeps its normal direction.

The v1 reference covers the whole new-game opening: the storybook prologue
(`0F01`..`0F07`), the Smith house scene (`1001`..`100E`, `0534`), the walk to
town (`1010`..`1014`) and the arrival at the festival (`2501`, `2502`).

## Build and ROM layout

The overlay changes C code and the string table, so the build uses
`make CUSTOM=1` and everything after `message.o` moves. That shift was checked
three ways before release:

- relocation scan: no unrelocated pointers were found in blobs after a forced
  0x40-byte shift;
- 60,000 frames of identical random input on the original ROM and on a shifted
  build with English text: every sampled frame identical, audio different only
  by sub-frame timing of a few effects;
- a directed run of the Arabic build from a new file to player control in Hyrule
  Town, including English messages after Arabic ones.

## Commands

```sh
classic-retro tmc source-check /path/to/tmc --font NotoKufiArabic-SemiBold.ttf
classic-retro tmc prepare-arabic-source /path/to/tmc --font NotoKufiArabic-SemiBold.ttf
make -C /path/to/tmc CUSTOM=1
classic-retro tmc encode-arabic "صباح الخير" --font NotoKufiArabic-SemiBold.ttf
```

## v1 boundary

- Combining harakat and mirrored brackets are rejected, not silently changed.
- One Arabic font style; the stylized location-name font has no Arabic page.
- Key icons and symbols inside Arabic lines are not measured yet.
- Left-aligned text boxes stay left-aligned in right-to-left mode.
- Menus, item names, the save screens and name entry are still English/Latin.
