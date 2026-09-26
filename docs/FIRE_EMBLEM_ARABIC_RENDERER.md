# Fire Emblem: The Sacred Stones Arabic Renderer / Font v1

Target: *Fire Emblem: The Sacred Stones* (USA, Australia). The decompilation
[FireEmblemUniverse/fireemblem8u](https://github.com/FireEmblemUniverse/fireemblem8u)
(commit `ecc6798b68fc7d0d164b2b6dd96a9fee4306cadb`) builds this exact image and was
used to find everything below, but most of its data is still binary, so this is a
binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 16777216 bytes |
| SHA-1 | `c25b145e37456171ada4b0d440bf88a19f4d509f` |
| SHA-256 | `638cda9d9b72657220fbf7e7a500cd3b64d9686c36e8a56fca69d26d13886f2f` |
| Game code | `BE8E` |
| Output | 16 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Messages.** `gMsgTable` (`0x0815D48C`) holds 3404 pointers.
  `GetStringFromIndex` calls `CallARM_DecompText` (`0x08002BA4`), which runs the
  ARM `DecodeString` copied to IWRAM: it walks the node array `gMsgHuffmanTable`
  (`0x0815A72C`) from the root that `gMsgHuffmanTableRoot` (`0x0815D488`) points
  to, reading bits least significant first. A node is a u32: two u16 child indices
  (bit 0, bit 1), or with bit 31 set a leaf holding one or two bytes. The codec in
  `engines/fire_emblem.py` reproduces all 3404 messages; the whole buffer holds
  0x1000 bytes (the longest English message uses 4000).
- **Commands.** Bytes below `0x20` are commands (`[X]` 0, `[LF]` 1, `[CR]` 2,
  `[A]` 3, speaker slots 8..15, `[LoadFace]` 16 plus two bytes...), `0x80 nn` is an
  extended command and `0x81 0x40` a tab. `[.]` (0x1F) is a zero-width empty
  glyph that paces the typewriter. In the world map's box `[CR]` also skips the
  byte after it (the script always writes `[CR][LF]`).
- **Talk.** One engine (`scene.c`) draws dialogue bubbles (BG0 text strips, 30
  tiles, cursor from 0) and the world map's narration box (sprite text, 32 tiles,
  28 shown, cursor from 4). Each step, `Talk_OnIdle` calls
  `Text_DrawCharacter(line, str)`: English mode draws `glyphs[byte]` through the
  font's `drawGlyph` (`DrawTextGlyph` or `DrawSpriteTextGlyph`), which ORs a 16x16
  2-bit glyph into the line at the cursor and advances it by the glyph's width.
  Any byte the interpreter does not handle is drawn as a glyph.
- **Bubble width.** `GetStrTalkLen` measures the widest line of the current
  speaker with `GetCharTextLen`, plus 12 pixels per `[A]` for the key arrow; the
  bubble is `(width + 7) / 8 + 2` tiles and its window clips text to
  `(activeWidth - 2) * 8` pixels. The key arrow is placed at the cursor + 4.
- **Talk glyphs** (`TextGlyphs_Talk`, `0x0858F6F4`): 256 pointers to
  `{next, sjis byte, width, pad, 16 rows of 16 two-bit pixels}` (72 bytes). The
  font uses value 3 for ink and 2 for a light shade right of its strokes;
  English uses codes `0x20..0x7E` plus three high codes (curly quotes, é).
- **Free space.** The linker filled `0x08EFB2E0..0x08FE0000` with `0xFF`.

## ROM layout

| Address | Content |
|---------|---------|
| `0x08F00000` | Thumb hooks (`src/classic_retro/rom/fire_emblem_arabic_hooks.s`, 276 bytes) |
| `0x08F01000` | Right-to-left glyph table: 256 pointers, then the glyphs (72 bytes each) |
| `0x08F08000` | Translated messages, uncompressed, each on a word boundary |
| `0x08F10000` | Legend images: LZ77 tiles and LZ77 tile map per image (about 11.6 KB for all seven) |
| `0x08003ABC` | Four 16-byte ARM veneers over `sub_8003ABC`, a debug routine that nothing calls or points to |
| `0x08206FE4` | `gOpSubtitleGfxLut`: the seven `{tiles, tile map}` pointers now point at the Arabic images; display times unchanged |

The overlay checks that `0x08F00000..0x08F20000` is still `0xFF`, and every
original byte it replaces, before writing. The Huffman bank and the game's own
legend images are untouched: a translated message's table entry gets bit 31 and
points at its bytes, and the legend table points at the new images.

## Right-to-left mode

A message is right-to-left when its first byte is `0x1E` (never the first byte of
an English message, and not a command). When a talk starts with it, the talk skips
the byte and sets bit 15 of its flags (`sTalkState->config`, reset to 0 by every
talk start). While the bit is set:

- widths and bitmaps come from the right-to-left table: the game's talk glyphs
  `0x21..0x7E` moved three rows up onto the Arabic baseline (those that keep their
  ink), a 4-pixel space, the zero-width `[.]`, and the Arabic presentation forms at
  `0x82 + slot`; `0x80`/`0x81` stay command prefixes, `?` is the fallback;
- text is stored in paint order (the first glyph of a line is its rightmost one);
  the cursor still advances left to right and each glyph is drawn at the mirror:

```text
draw_x = axis - cursor - width
axis   = (activeWidth - 2) * 8    in a bubble (the window's text width)
axis   = 220                      in the world map's box
```

In a bubble the text then ends on the window's right edge, as English starts on
its left edge. The world map's box shows 28 tiles but the game clears only 27 of
each line (English never reaches the last), so Arabic ends at pixel 216 (screen
x 224, a 16-pixel margin against English's 12). The key arrow ends 4 pixels left
of the text. Glyph pixels never leave their own width, so ORed neighbours never
overlap. The typewriter reveals Arabic from right to left.

## Hooks

| Site | Original | Kind | Hook |
|------|----------|------|------|
| `0x08002BA4` | `00 B5 03 4A` ... (`CallARM_DecompText`) | jump | `hook_decomp`: copy messages whose pointer has bit 31, else tail-call `DecodeString` |
| `0x080069F2` | `02 F0 A7 F8` (`StartTalkExt` → `GetStrTalkLen`) | `BL` veneer 0 | `hook_start`: skip the marker, set the flag, then measure |
| `0x08008EFA` | `FB F7 1F F8` (`GetStrTalkLen` → `GetCharTextLen`) | `BL` veneer 1 | `hook_width`: right-to-left widths |
| `0x08006D08` | `FD F7 3A FA` (`Talk_OnIdle` → `Text_DrawCharacter`) | `BL` veneer 2 | `hook_draw`: right-to-left glyph at the mirrored cursor |
| `0x08007328` | `FC F7 92 FD` (`TalkInterpret` `[A]` → `Text_GetCursor`) | `BL` veneer 3 | `hook_arrow`: key arrow left of the text |

`BL` cannot reach `0x08F00000` from the talk code, so each site calls a veneer
(`bx pc; nop; ldr ip, [pc]; bx ip; .word hook`) in the unused routine. The jump
at `0x08002BA4` is `ldr r2, [pc]; bx r2; .word hook_decomp`. Without the flag
every hook runs the original function, so English text is untouched.

`classic-retro targets check-hooks fire-emblem` re-assembles the source with GNU binutils
and compares the result with the bytes stored in `fire_emblem_arabic.py` (run in
CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 123 forms: the shared repertoire without Arabic-Indic digits (no codes left;
  translations use 0-9). Size is the largest whose ink fits rows 1..15 around the
  row-11 anchor: 10 px for the reference font, letters ending on row 10.
- Ink is value 3; value 2 shades the pixel right of each stroke, as in the game's
  font, but never beyond the glyph's width. Medial and final forms end at their
  last ink column, so joins touch the glyph painted before them.
- At 10 px the font draws `،` and `؛` as two pixels; they are drawn as slanted
  Kufi commas four rows high instead.

## Translations

The script (`src/classic_retro/translations/fire-emblem.json`; its originals are pinned
in `src/classic_retro/rom/fire_emblem_arabic_script.py`) is logical Unicode Arabic in
bracket notation (`[OpenMidLeft]`, `[LoadFace 51 01]`, `[A]`,
`[LF]`, `[.]`...). For each message:

1. the SHA-256 of the original decoded bytes and its command skeleton are pinned;
   the ROM build refuses a different script;
2. the Arabic commands must equal the original's; only `[LF]` and `[.]` may move,
   and `[CR][LF]` stays one unit;
3. every line is measured with the key arrow's 12 pixels: at most 208 pixels in a
   bubble (26 tiles, on screen whatever the speaker's slot) and 216 in the world
   map's box.

Messages: `0x8DB` (the world map's narration of Magvel: 22 key waits, and 18
`[BreakTalk]` pauses where the event script moves the map)
and `0x903`..`0x906` (the throne room of Castle Renais, from the soldier's report to
King Fado's last words).

## Legend images

Before a new game, `StartIntroMonologue` shows the legend of the Sacred Stones as
seven 240x160 images (`gOpSubtitleGfxLut`, `0x08206FE4`: LZ77 4bpp tiles, LZ77 tile
map, display frames). They are drawn on palette 3: index 0 transparent, 1..13 a
ramp from cream to dark brown for anti-aliased edges; lines are centred, 24 pixels
apart. The tile map is `width - 1`, `height - 1` and u16 entries bottom row first
(`TmApplyTsa`); the game adds the tile base and palette. Images 3..5 are also put
on BG1 with a dark palette, 3 pixels off, as a shadow over the stone background.

- **VRAM.** Tiles are decompressed at `0x06001000`, up to the tile map at
  `0x06006000`; image 2 ("The Sacred Stones") goes to `0x06005000` while the stone
  background fills the tiles below, so it may use 128 tiles. The Arabic images use
  25..164 tiles (budget 128 for image 2, 512 for the others).
- **Drawing.** Each line is shaped with HarfBuzz (right to left: contextual forms,
  lam-alef ligatures, kerning) and rasterized by Pillow glyph by glyph through a
  private-use cmap on an in-memory copy of the user's font, so no system shaping
  library is needed. The size makes the font's alef as tall as the English
  capitals (10 pixels: 13 px for the reference font). Coverage maps linearly onto
  the ramp (below 40 of 255 is transparent). The reference font has no Latin
  punctuation; `.`, `!` and `:` get square dots as wide as its alef stroke.
- **Encoding.** Unique tiles (tile 0 blank), the full-screen tile map, and VRAM-safe
  LZ77 (`rebuild/lz77.py`, never a distance of 1 because VRAM is written 16 bits at a
  time). The build decompresses both back from the output image and compares the
  decoded pixels with the drawing.
- **Lines** (`fire_emblem_arabic_legend()` in the script): Arabic letters, spaces
  and punctuation only (no bidi runs to reorder, no marks), at most five lines of
  at most 224 pixels.

## Runtime verification

With mGBA 0.10.2 (libmgba, headless, scripted input) on the patched build, from a
new game (Easy mode):

- the whole narration and throne room in Arabic, over 150 screenshots: every line
  right-aligned, joined and shaped, the key arrow left of the text, no leftovers
  after `[CR]`, the scrolling of both boxes intact, and message `0x907` (the next
  scene) in English;
- a build translating only the narration, loaded from a state in the middle of the
  English narration: 60 screenshots through the rest of the narration and the
  English throne room are pixel-identical to the original game;
- a build translating only the throne room, from the menus: the English narration
  (75 screenshots) is pixel-identical to the original game;
- the legend from the main menu (128 screenshots): all seven Arabic images with the
  game's fades, the stone background and its shadow layer, at the positions of the
  English ones; Start still skips to the Arabic narration.

## Commands

```sh
classic-retro targets check-translations fire-emblem --font NotoKufiArabic-SemiBold.ttf --preview-dir previews
classic-retro targets build fire-emblem original.gba --font NotoKufiArabic-SemiBold.ttf --out-dir out
classic-retro fire-emblem encode-arabic "مولاي، ماذا نفعل؟[A]" --font NotoKufiArabic-SemiBold.ttf
classic-retro targets check-hooks fire-emblem
```

## v1 boundary

- Combining harakat, mirrored brackets and Arabic-Indic digits are rejected.
- Runtime text (`[G]` numbers, `[Tact]`, unit and item names) and the Yes/No and
  shop choices are rejected inside Arabic messages.
- The chapter title and battle animations are images not redrawn yet; the
  location label ("Renais Castle"), menus and help boxes use other text systems.
  All of these stay English, as does every message after `0x906`.
- Battle quotes use a fixed 20-tile bubble; Arabic ones would need a third axis.
