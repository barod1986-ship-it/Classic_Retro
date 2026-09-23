# Golden Sun Arabic Renderer / Font v1

Target: *Golden Sun* (USA, Europe). The symbolized disassembly
[gsret/goldensun](https://github.com/gsret/goldensun) (commit
`0fa7b312199c10b96544e825be86cfc476493eb7`) assembles to this exact image and
was used to find everything below, but it cannot relocate data yet, so this is
a binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `5c4695205413df7db52b9a184815a07783999971` |
| SHA-256 | `c14f1151897e8d73f25ffdd67e21eebb6dc57973ff2458872ee89fa9060aaca1` |
| Game code | `AGSE` |
| Output | 16 MiB image, shipped as BPS |

## Engine facts the overlay relies on

- **Text bank.** All 10722 strings share one context Huffman model: a code is
  read with the tree of the previous code (`0` before the first); a string ends
  with `0`. Leaves hold 12-bit values and the tree pointer table has one
  `{trees, u16 offsets}` entry per 256 contexts. A tree is its leaf array
  (12-bit pairs, written backwards) followed by its pre-order topology, least
  significant bit first. Strings are grouped by 256 with one length byte each
  (`0xFF` continues). Tables: trees `0x0803842C` (referenced at `0x0801556C`,
  the literal pool of the ARM decoder that is copied to RAM, and `0x08019D08`),
  strings `0x080736B8` (referenced at `0x080155CC`). The codec reproduces
  every string of the original bank.
- **Decoding** (`Func_18038`, `0x08018038`) copies the ARM decoder (`0x08015430`,
  0x140 bytes, its tree table literal at +0x13C) to RAM, opens the string
  (`Func_19bac`: state `{previous code, data, bit buffer}`), turns the message
  into the 512-entry u16 ring at `[0x03001E8C] + 0xEB0`, expands names and
  items there (`Func_17e88`) and replaced every code above `0xFF` with `@`.
- **Page measure** (`Func_18850`, `Func_18a50`) sizes the window from the ring:
  space 5 px, other codes the font advance, 15 px per line, width in tiles
  `(widest + 19) >> 3`. Lines are justified by an extra width per space (at
  most 12 px, else 2 px).
- **Typewriter** (`Func_168f4`) draws one step per frame: two glyphs share a
  16x16 sprite (pool of 64) when their advances fit in 15 px. The cursor is
  8.8 fixed point. `Func_18cac` allocates the sprite and `Func_178b0` draws the
  pair: ink from row 2, shadow colour 1 one pixel right and down.
- **Font** `0x08032224`: 32 bytes per code `0x20..0x8F`, a u16 advance then
  14 rows of 1bpp pixels (u16, most significant bit leftmost).
- Codes `0x0B`–`0x0F`, `0x17`, `0x1C` and `0x1F` never occur in the script;
  `0x0B` is copied into the ring and skipped by the typewriter and both page
  measures.

## ROM layout

| Address | Content |
|---------|---------|
| `0x08074000` | Thumb hooks (`src/classic_retro/rom/golden_sun_arabic_hooks.s`, 684 bytes), inside the zero padding that aligns the `0x08077000` section, so the game reaches them with `BL` |
| `0x08800000` | Right-to-left glyph table: 512 advances, then 512 glyphs of 16 rows x 16 two-bit pixels |
| `0x08810000` | Arabic string store: a tree pointer table (two blocks), the index (`u16 string, u16 0, u32 data`, ended by `0xFFFF`), the trees, then each translated string on a word boundary |

The game's text bank and its references stay untouched, so the patch carries
no English text (about 13 KB). When the dialogue decoder opens a translated
string, `hook_init` points the decoder state at the store's data and the tree
table literal of the decoder's RAM copy at the store's trees; every other
string is decoded as before. The image is filled with `0xFF` up to 16 MiB.

## Right-to-left mode

A message is right-to-left when its first code is `0x0B`. Arabic glyphs are
codes `0x100 + slot`; the decoder keeps them because one branch no longer
replaces codes above `0xFF`.

While such a message is decoded, every name inserted at runtime is reversed in
the ring, and at the end every glyph gets the tag `0x200`. Text is stored in
paint order: the first glyph of a line is its rightmost one. The cursor still
advances left to right; each pair is drawn at the mirrored position:

```text
draw_x = window_width_tiles * 8 - 12 - cursor_x - pair_width
```

`window_width * 8 - 12` puts the right margin where left-to-right text has its
left margin. The first glyph of a pair is drawn on the right, so a joining
stroke meets the pair painted before it. Tagged spaces are not counted as
spaces by the page measure, so Arabic lines are never justified. The
typewriter reveals Arabic from right to left.

The runtime name is reversed as a whole (`Ab-12` stays `Ab-12`); static Latin
text and digits in a translation are resolved by the bidi step at build time.

## Hooks

| Site | Original | Kind | Hook |
|------|----------|------|------|
| `0x080180BE` | `01 F0 75 FD` | `BL` | opening a string: translated strings are read from the store with its trees |
| `0x080180D4` | `00 D9` | patch | `bls` becomes `b`: codes above `0xFF` survive decoding |
| `0x0801851A` | `06 1C 7A E0` | `BL` | after a name/item is copied: reverse it in right-to-left messages |
| `0x0801864A` | `EA F7 C5 FB` | `BL` | end of decoding: tag right-to-left glyphs, then free the decoder |
| `0x08016DFE` | `30 68 C2 8A` | `BL` | typewriter: right-to-left pairing and mirrored x |
| `0x08018DCA` | `FE F7 71 FD` | `BL` | sprite renderer: right-to-left pairs from the glyph table |
| `0x080188A8` | `54 4B 20 3A 52 01 9A 5A` | jump | page measure width (`lr` holds its jump table) |
| `0x08018AC4` | `20 3A 52 01 9A 5A 65 4B` | jump | second page measure (`lr` holds a pointer argument) |

A jump site is `ldr r3, [pc]; bx r3; .word hook`. The overlay checks every
original byte and that the hook region is still zero padding before writing.
The game's own pairs pack `code | next << 8`; right-to-left pairs reach the
renderer as `code | next << 16 | 1 << 31` so the two can never be confused.
The game's code treats `r4` as a scratch register; the hooks keep nothing in
it across a call into the game.

`classic-retro golden-sun check-hooks` re-assembles the source with GNU
binutils and compares the result with the bytes stored in
`golden_sun_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 133 presentation forms from the shared repertoire at codes `0x100 + slot`,
  the game's Latin glyphs copied from the user's image (moved up one row so
  their caps end on the Arabic baseline), and a 5 px space.
- Size is the largest whose ink fits rows 0..14 around the row-10 baseline:
  10 px for the reference font. Row 15 only takes the shadow. With the
  reference font the ink ends on row 13 and only alef with hamza reaches row 0,
  so lines 15 px apart do not touch.
- The shadow (right and down, as in the game) stays inside each glyph's
  advance: the glyph on the right is painted first and keeps its joining
  stroke. Medial and final forms end at their last ink column.

## Translations

The script (`src/classic_retro/rom/golden_sun_arabic_script.py`) stays logical
Unicode Arabic. For each string:

1. the SHA-256 of the original codes and its command skeleton are pinned; the
   ROM build refuses a different script;
2. the Arabic commands must equal the original's, except newlines, inserted
   `KEY_PAGE` pages and the em dash command (Arabic punctuation replaces it);
3. every line is measured (at most 176 px, the hero's name counted as 50 px)
   and every page holds at most three lines.

Strings 3666–3686: the storm night, including both answers to "Have you got
everything you need?" (3673, 3674) and to "You can find your way, can't you?"
(3685).

## Runtime verification

With mGBA 0.10.2 (libmgba, headless, scripted input) on the patched build:

- new game through all 21 strings, including both "No" branches;
- the hero renamed in RAM to `Ab-12` and `Mustafa`: the name stays one
  left-to-right unit and the window grows with it;
- a build that leaves strings 3667, 3671, 3677 and 3681 in English: over 80
  screenshots of the opening, those four messages (between Arabic ones, one
  of them justified) are pixel-identical to the original game, and every
  frame that differs shows an Arabic message; English text, pairing and
  justification are unchanged.

## Commands

```sh
classic-retro golden-sun check-translations --font NotoKufiArabic-SemiBold.ttf
classic-retro golden-sun build-arabic original.gba --font NotoKufiArabic-SemiBold.ttf --out-dir out
classic-retro golden-sun encode-arabic "صباح الخير" --font NotoKufiArabic-SemiBold.ttf
classic-retro golden-sun check-hooks
```

## v1 boundary

- Combining harakat and mirrored brackets are rejected, not silently changed.
- Runtime numbers, items, English grammar, button icons and the em dash are
  rejected inside Arabic messages; only character names are placed.
- Bold text mode (`[0xEAC]` 1 or 5) widens glyphs in the page measure only.
- The Yes/No menu, menus, battle text and name entry are still English.
