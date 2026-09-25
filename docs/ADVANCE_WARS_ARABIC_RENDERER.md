# Advance Wars Arabic Renderer v1

Target: *Advance Wars* (USA, Rev 1). No decompilation of this game is known: every
fact below comes from the image's own code, found with the
[research tools](RESEARCH_TOOLS.md) (text and pointer scans, `disasm`, and mGBA runs with
breakpoints and watchpoints on the text being drawn). This is a binary ROM overlay built
from the user's image.

| Item | Value |
|------|-------|
| ROM size | 4194304 bytes |
| SHA-1 | `15053499d5b3f49128a941d7f2d84876f5424d0c` |
| SHA-256 | `4dd4bd22441f29b22ca5af554f30bf0eb7d2b1a5daff0e2cd071a43e11383305` |
| Game code | `AWRE` (`ADVANCEWARS`), header revision 1 |
| Output | 4 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Messages.** ASCII, one byte a character, ended by `00`. Control codes: `0D` new
  line, `0F` wait for a key and clear the box, `15` the player's name (the RAM string
  at `0x0201226C`), `16`/`17`/`14` a Yes/No question (`17` with No first), `09 xx` an
  icon, `0A xx` and `0B` printer options (`0B` takes a parameter only when it is
  `0x80`..`0x89`), `0C` clear, `0E` pause, `80`..`83` the text colour. Every other byte
  is a glyph. The interpreter is `0x08011D00` (a jump table for codes `00`..`17`).
- **Scripts.** Event scripts are commands of four words; command `0x19` shows the
  message its second word points to. Its handler (`0x08017928`) opens the dialogue box
  with `0x080123A8`: text from tile column 7, row 1 of the box's map (a RAM copy at
  `0x02014B40`), tiles from `0x100`. It first scans the message with `0x08011C80`, which
  steps two bytes over each glyph, looking for code `14`.
- **Printer.** `0x08012078` draws one character a frame. Its state: +32 text, +36 the
  text to go back to after the name, +40 the map, +44 the tiles' palette bits, +46 the
  colour, +48/+49 the text area's first column and row, +50/+51 the current column and
  row, +52 the current tile, +64 the pen's pixel inside the tile column. Before each
  glyph but the first of a line it moves the pen one pixel (`0x08012C7C`), then draws
  the glyph (`0x08052230`) into the current pair of 4bpp tiles, the top and bottom
  halves of an 8x16 column, spilling into the next pair, and writes the pair into the
  map when the pen reaches it (`0x08012064`). A line end skips to a new column pair on
  the next row; `0F` puts the key arrow in the column after the pen's (tiles `0x174`
  and `0xA1C9`).
- **Font.** 256 glyphs, with a pointer each at `0x083097F0` and a width each at
  `0x08309BF0`: 16 rows of (width + 1) / 2 bytes, two pixels a byte (the left one in the
  low nibble), at most 8 pixels wide. Pixel `0xA` takes the text colour; `4`..`7` are
  the greys around the strokes. The letters end on row 12.
- **Yes/No.** Codes `14`/`16`/`17` start a task (`0x08281CE8`) that draws the English
  answers (the string at `0x082EA088`) with another printer, and the cursor (tiles
  `0xA1CA`, `0xA1CB`) at its place or four columns to the right (`0x0801862C`). Right or
  B picks No, Left picks Yes.
- **Free space.** The image ends with 33420 bytes of `0xFF` from `0x083F7D74`.

## Right-to-left text

The printer cannot draw from the right: its pen, its tiles and its map all advance
left to right. The overlay leaves all of that alone and mirrors the result instead,
with the hardware's horizontal flip:

1. For a state whose text lies in the Arabic bank (or whose name insertion returns to
   it), `hook_column` writes each tile column into the map at its mirror inside the
   22 columns of the text area, with the flip bit (`0x400`):

   ```text
   column' = 2 * left + 21 - column
   ```

   A line then starts at the right edge of the box (x = 231) and grows leftwards, and
   the typewriter reveals it from the right.
2. The glyphs of the right-to-left font are stored flipped, so the flip shows them the
   right way round. `hook_draw` draws them with the overlay's own routine (the game's
   routine and font table stay as they are): 16 rows of 8 pixels, cleared only when a
   glyph starts a tile pair, since Arabic glyphs touch.
3. `hook_gap` drops the printer's one-pixel gap: Arabic letters join, and every glyph
   carries its own spacing.
4. A translated message holds these glyphs in right-to-left paint order: the first
   glyph of a line is its rightmost one.
5. `hook_arrow` puts the key arrow in the column left of the line, mirrored.
6. The player's name (`15`) stays Latin: `hook_name` reverses the string in place while
   it is drawn and `hook_name_end` restores it; `hook_draw` draws each letter from the
   game's own font, flipped, after a free column, so the name reads left to right
   inside the Arabic line.
7. A question (`16`) gets its answers `نعم` and `لا` on its own line, typed with the
   message: the encoder places each a pixel past its cursor's tile. `hook_choice`
   stores the cursor's mirrored place with bit 0 set; for such a place `hook_labels`
   skips the English answers, `hook_cursor` draws the flipped cursor at the mirrored
   places (No four columns to the left), and `hook_keys_back` / `hook_keys_next` swap
   Left and Right.
8. Any other text keeps the game's own path: every hook first checks the bank.

## ROM layout

| Address | Content |
|---------|---------|
| `0x083F8000` | Thumb hooks (`src/classic_retro/rom/advance_wars_arabic_hooks.s`, 756 bytes) |
| `0x083F8800` | Right-to-left font: 256 pointers, 256 widths, 186 glyphs of 64 bytes (13184 bytes) |
| `0x083FC000` | The Arabic bank: the 14 translated messages (1860 bytes), up to `0x08400000` |
| 14 script commands | Their message pointer, now the Arabic message |

A stored message ends with at least two zeros, so the scan of the message command
stops on one whichever byte it steps on. The overlay checks the input hash, the code
at every site, the bytes the hooks rely on (the font tables' literals, the name's
address, the dialogue box's column, row and map, the Yes/No task's registers), that the
padding is still `0xFF`, and for every translated message its script command, its
SHA-256 and its control codes. After writing it reads back every site, the font and
every message.

## Hooks

Each site is replaced by a `BL` to its hook (all within `BL` range of the padding).

| Site | Original | Hook |
|------|----------|------|
| `0x080121AA` | `bl 0x08012C7C` (the gap) | `hook_gap` |
| `0x080121CC` | `bl 0x08052230` (the glyph) | `hook_draw` |
| `0x080121E2`, `0x080121FE` | `bl 0x08012064` (the tile column) | `hook_column` |
| `0x08011E30` | 18 bytes of code `0F` (the key arrow) | `hook_arrow`, then `b 0x08011E42` |
| `0x08011DAE` | `ldr r0, =0x0201226C; str r0, [r5, #32]` (code `15`) | `hook_name` |
| `0x08011DA2` | `str r0, [r5, #32]; movs r0, #0; str r0, [r5, #36]` (end of the name) | `hook_name_end`, `nop` |
| `0x08011DCE` | `adds r0, r6, #2; str r0, [r4, #24]` (the cursor's place) | `hook_choice` |
| `0x08018692` | `bl 0x08012A68` (the answers) | `hook_labels` |
| `0x08018698`, `0x080186E8` | `bl 0x0801862C` (the cursor) | `hook_cursor` |
| `0x080186C0`, `0x080186D8` | `movs r0, #0x20` / `#0x12`; `ldrh r1, [r1, #12]` (the keys) | `hook_keys_back`, `hook_keys_next` |

`classic-retro advance-wars check-hooks` re-assembles the source with GNU binutils and
compares the result with the bytes stored in `advance_wars_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 186 glyphs, codes `0x18`..`0xD5` (never a control code, a colour or zero): the game's
  space (3 pixels), a 1-pixel space to place the answers, 14 copies of the game's
  glyphs (`.`, `!`, `:`, `-`, `0`..`9`, at their own codes, each with a free column
  after its ink) and the 133 forms of the shared repertoire.
- Size 10 on the game's baseline (the letters end on row 12), the largest size whose
  forms fit 16 rows once final and isolated yeh are raised by a row (their dots reach
  row 16), the final one keeping a pixel on the joining row.
- A glyph is at most 8 pixels wide, as in the game's font. The 37 forms wider than that
  at the reference size (seen, sheen, sad, dad, tah and zah in all four forms; feh,
  qaf, alef maksura, yeh and yeh with hamza isolated and final; kaf isolated; heh
  initial and medial) take two codes each, the right part painted first.
- Coverage from 140 of 255 is ink (`0xA`), from 60 the grey (`4`). Medial and final
  forms end at their last ink column, touching the glyph painted before them.

## Translations

The script (`src/classic_retro/translations/advance-wars.json`; its originals are
pinned in `src/classic_retro/rom/advance_wars_arabic_script.py`) covers Nell's
opening, from a new game to the first Field Training lesson: 14 messages.

- The welcome, the name prompt and its confirmation (a question), Nell's greeting with
  the player's name, and her question about playing for the first time.
- Yes: her overview of the modes (12 pages) and the first lesson.
- No: her offer of a quicker way and a second question (8 pages); then either her
  advice on the Mode Select menu and the first lesson, or the modes and the last Field
  Training mission.

For each message its script pointer, its address, its SHA-256 and its control codes
are pinned; the Arabic keeps every control code in order (line ends after text may
move). The game's names are transliterated (أدفانس وورز, نيل, جيم بوي أدفانس) and its
terms translated (التدريب الميداني, نمط المواجهة, نمط الربط, النجمة البرتقالية,
أوامر القوات, ضباب الحرب); Nell speaks as a woman to the player.

## Verification

In mGBA, with the patch built from the reference font, from a fresh boot: the welcome,
the name prompt over the name entry screen, the confirmation with its answers (the
cursor moves left to No and back with Left and Right), the greeting with the name
(`AA`, and `Ab1` written into the name's RAM string, which reads left to right and is
back in order afterwards), both answers to both questions and every page of both
overviews, each line revealed from the right with the key arrow on its left. With the
same input from power-on, the title screen, the name entry screen and three pages of
the first lesson's English briefing (the same printer and box) are pixel-identical to
the original image's.

## Limits

- Only Nell's opening is in Arabic; Field Training and the rest of the game are in
  English.
- The Arabic dialogue box is the one the message command opens (column 7, 22 columns);
  other boxes would need their own geometry.
- Arabic messages cannot hold Latin letters other than the player's name (the
  right-to-left font has digits and punctuation only), colour codes or icons.
- No vowel marks, one font size, and no lam-alef ligature (lam and alef are separate
  forms).
