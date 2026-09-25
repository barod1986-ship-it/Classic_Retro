# Final Fantasy VI Advance Arabic Renderer / Font v1

Target: *Final Fantasy VI Advance* (USA). There is no source-matching
decompilation, so this is a binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `e9a2a58bc56ace26cb56d0cf5cdad1a10aa5dedf` |
| SHA-256 | `1310f2ad3c13f5446cf6c43d01d48aad640d6b8a4fbba2b92c776f4f6d90e6ff` |
| Game code | `BZ6E` |
| Output | 16 MiB image, shipped as BPS |

## Engine facts the overlay relies on

Found by disassembling the event text renderer and tracing it in mGBA.

- Dialogue is one `TEXT` bank at `0x08174454`: `0`, `"TEXT"`,
  `(6114 << 8) | 1`, end offset, then 6114 u32 offsets relative to the bank. A
  message ends where the next begins. The bank round-trips byte for byte.
- A message is a stream of codes in a UTF-8-like form (reader `0x081509B8`):
  bytes below `0x80` are one code, lead bytes `0x80..0xDF` add one byte,
  `0xE0..0xEF` add two. Codes `0x000..0x10C` are glyphs of the dialogue `FONT`
  (`0x08162CCC`, frequency ordered: `0` space, `1` e, `2` t, ...); larger codes
  are commands. The renderer skips commands it does not know.
- Commands used by the opening: `10E` newline, `10F` end, `13A n` pause
  `(n - 0x144) * 15` frames, `13E` page (the following newline is skipped),
  `138` page after a key press, `140` centre the line, `142` narration,
  `136 n` timed close, `137` close. Messages end with `10F` and a `0E` byte.
- `FONT`: `0`, `"FONT"`, height, flags, glyph count, 128 ASCII-to-glyph
  entries, one u32 offset per glyph. A glyph is advance, row size in bytes
  (1..4), then `height` rows of 2-bit pixels (1 ink, 2 shadow), least
  significant pixel first. The blitter (`0x0815075C`) ORs non-zero pixels.
- The renderer (`0x0815115C`) keeps its state at `0x03002518`: `+22` left
  margin (0, or 40 with a portrait), `+24/+25` cursor x/y, `+0x3A/+0x3B` line
  limit and count. Reader 0 (the top-level message) is at `0x03002464`, its
  message pointer at `0x03002468`. Glyphs are drawn into a 256x64 4bpp canvas
  at `0x02022500`, whose dirty tile rows are copied to VRAM.
- The canvas is shown through a per-scanline BG table: 47 lines for a window
  (canvas row 0 at line 5), 63 lines for the window-less narration.
- `140` centres with `x = ((240 - width) >> 1) - 8`, so a dialogue line and a
  centred line share one axis: the text area is canvas x 0..224.

## ROM layout

| Address | Content |
|---------|---------|
| `0x08800000` | Thumb hooks (`src/classic_retro/rom/ff6a_arabic_hooks.s`, 392 bytes) |
| `0x08801000` | Arabic `FONT` (134 glyphs, 16 rows) |
| `0x08804000` | Rebuilt dialogue `TEXT` bank, translated messages in place |

The five references to the dialogue bank (`0x08108A88`, `0x0810A0C8`,
`0x08150B00`, `0x0815FFD8`, `0x0815FFEC`) point to the rebuilt bank. The
original bank stays untouched. The image is filled with `0xFF` up to 16 MiB.

## Right-to-left mode

A message is right-to-left when its first code is `0x5FF` (bytes `D7 BF`).
The hooks test reader 0, so a runtime sub-message keeps the mode of its parent,
and English messages (battle results, untranslated text) are unaffected.

Text is stored in paint order: the first glyph of a line is its rightmost one.
The cursor still advances left to right, so centring and paging keep their
meaning; only the glyph pixels move to the mirrored position:

```text
draw_x = margin + 224 - cursor_x - advance
```

A left-aligned line becomes right-aligned at canvas x 224; a centred line stays
centred. The typewriter reveals Arabic from right to left.

Arabic glyphs are codes `0x600 + slot` drawn from the Arabic font. In
right-to-left messages lines are 16 pixels apart, so a window holds two lines,
and the narration band is raised from 63 to 72 scanlines for four lines.

## Hooks

Each site becomes `ldr rN, [pc]; bx rN; .word hook` (a `nop` pads an unaligned
site); hooks return with an absolute branch. The overlay checks the original
bytes before writing.

| Site | Original | Hook |
|------|----------|------|
| `0x081514AC` | `86 20 40 00 84 42 1D D8` | glyph or command: Arabic glyph codes, mirrored draw position |
| `0x08150F5C` | `9E 20 40 00 81 42 6B D0` | line width for centring counts Arabic glyphs |
| `0x08151652` | `B0 7D 30 76 70 7E 0C 30 70 76` | newline: 16-pixel step |
| `0x08151628` | `B0 7D 30 76 70 7E 0C 30` | newline, second window path |
| `0x08151A04` | `71 7E 0C 31 0A 1C 02 40` | canvas rows copied after drawing |
| `0x0813BFAC` | `3F 21 08 91 61 26 02 4A` | narration band: 72 scanlines |

`classic-retro ff6a check-hooks` re-assembles the source with GNU binutils and
compares the result with the bytes stored in `ff6a_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 133 presentation forms from the shared repertoire plus a 4-pixel word space.
- Size is the largest whose ink fits rows 0..14: 10 px for the reference font.
  Row 15 only takes the shadow. The baseline (row 10) is the Latin font's, so
  the game's own `.` `!` `:` digits sit correctly inside Arabic lines.
- The game's drop shadow (right, below, below-right) is kept inside each
  glyph's advance: the glyph on the right is painted first and must keep its
  joining stroke. Medial and final forms end at their last ink column.

## Translations

The script (`src/classic_retro/translations/ff6a.json`; its originals are pinned in
`src/classic_retro/rom/ff6a_arabic_script.py`) stays logical Unicode Arabic, with the
engine's commands by name (`{PAGE}`, `{PAUSE 14C}`, `{+KEY_PAGE}`). For each message:

1. the original's SHA-256 and command skeleton are pinned; the ROM build
   refuses a different script;
2. the Arabic commands must equal the original's, except layout commands
   (newline, centre) and inserted pages: a timed `PAUSE, PAGE` in the automatic
   cliff scene, a `KEY_PAGE` in button dialogue;
3. every line is measured (at most 224 px, 184 px after a portrait) and every
   page holds at most two lines in a window, four in the narration band.

Messages 1–9 and 11–20: the narration (6–9), the cliff scene (1–5) and the way
through Narshe to the mines (11–20). Message 9 is drawn in the top band without
a window frame, which has a window's height.

## Runtime verification

With mGBA 0.10.2 (headless, scripted input) on the patched reference build:

- new game through the narration (6–9) and the whole cliff scene (1–5),
  including the inserted page of message 3;
- in Narshe: messages 11, 13, 15 and 18 in play, top and bottom windows,
  English battle messages afterwards;
- messages 12, 14, 16, 17, 19 and 20 (the mines, not reached by the scripted
  route) rendered in a window through a test image that shows each of them in
  place of message 1.

The BPS writer was checked against Flips in both directions (Flips applies our
patch; we apply a Flips patch); CI repeats this on synthetic data.

## Commands

```sh
classic-retro ff6a check-translations --font NotoKufiArabic-SemiBold.ttf
classic-retro ff6a build-arabic original.gba --font NotoKufiArabic-SemiBold.ttf --out-dir out
classic-retro ff6a encode-arabic "صباح الخير" --font NotoKufiArabic-SemiBold.ttf
classic-retro ff6a check-hooks
```

## v1 boundary

- Combining harakat and mirrored brackets are rejected, not silently changed.
- Runtime names, numbers and item names are rejected inside Arabic messages:
  a Latin name would be drawn glyph by glyph in mirrored positions.
- Choices (`139`) are rejected: the cursor positions are not mirrored.
- A centred line after a portrait would be mirrored around the portrait axis.
- Menus, battle text, the save-point tutorial (message 10) and name entry are
  still English.
