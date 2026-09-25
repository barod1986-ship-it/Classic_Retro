# Tactics Ogre Arabic Renderer v1

Target: *Tactics Ogre: The Knight of Lodis* (USA). The
[jiangzhengwenjz/totkol](https://github.com/jiangzhengwenjz/totkol) disassembly
builds this image and gives the code's boundaries and addresses, but its data is
taken from the original and it cannot be shifted, so this is a binary ROM overlay
built from the user's image. The disassembly names almost nothing: the facts below
come from its listing and the image's own code, checked with the
[research tools](RESEARCH_TOOLS.md) (`relative-search`, `pointers`, `disasm`,
`free-space`, and mGBA runs with breakpoints and watchpoints).

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `85a46320a31f16f5c6dda27fc094edd078dbe43d` |
| SHA-256 | `c5b439c2530331f38e7a6e16857f58c554f270019641f825ac060f4e7866bae4` |
| Game code | `ATOE` (`TACTICSOGRE`), maker `EB`, header revision 0 |
| Output | 8 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Scenes.** The table at `0x08784298` has 70 entries, each a block's offset from the
  table; a scene's script reads its entry (`0x081222EC`, through the scenario's index),
  and several entries can share a block. A new game reads entry 1; entry 0 points to
  the same block, at `0x087843B0`.
- **Blocks.** A block starts with a table of 16-bit offsets from the block's start,
  one per message, ended by `FFFF`. The first scene's block has 35 messages: the
  harbour-town dialogue, eight unused ones and a later narration.
- **Messages.** A 16-bit header (bits 4 and 5: the lines of a page, the speaker's name
  line included; 3 or 2 here), then bytes up to `FF`, stored on halfwords:
  - `00..7F` are glyphs: `A..Z` from `00`, `a..z` from `1A`, `0..9` from `34`, then
    `!?.,:&_%'()<>+-*/=` from `3E`, `"` at `51` and an ellipsis at `52`;
  - `88` ends a line and `89` is a space of 6 pixels (drawn as the blank glyph `56`);
  - `8A` starts a new page, `8B` shows what follows at once and `8C` goes back to the
    typewriter (a message puts its speaker's name between them, on the first line),
    `8E` waits for A before the next page and `8D` at the end (`8D 8A FF` ends every
    message), and `8F..91` are flags;
  - `80xx` draws name `xx` from RAM (16 bytes each at `0x02002800`: the player's),
    `81xx` icon `xx`, `87xx` name `xx` of the characters' list at `0x086254D8`
    (name 5 is Rictor's), and `82`, `83`, `84`, `86` take a byte too;
  - `85` starts a choice whose options follow as texts of their own. The routines read
    no byte from `92` to `FE`: the counting routines stop on it forever.
- **Font.** 128 glyphs of 8x16 pixels at `0x0815DEC4`, 64 bytes each, a row of four
  bytes after another (two 8x8 tiles, top then bottom), with a width each at
  `0x0815DE6C`: 6 pixels for most letters, 3 to 8 for the others. Ink is value 1 (dark)
  and value 2 is the grey around the strokes. Letters stand on row 13; rows 0-3 are
  empty.
- **The dialogue** (`0x08015188`, called once a frame) draws one byte at a time into
  the window's tiles in VRAM, a column of two 8x8 tiles (64 bytes, a row every four)
  for every 8 pixels of the line. A glyph (a byte below `80`, or `89`) goes to
  `0x0801B0C8` (`bl` at `0x080158F0`, with `r0 = 0`, `r1` the glyph, `r2 = 1`,
  `r3 = 0`; `r4` is the text), which composes it at the pen in a scratch column and
  writes whole columns, then moves the pen by the glyph's width. It plays a typing
  sound for every glyph but codes 0 and 1.
  - The pen is at `0x030008C0`: `+0` the line's column where it starts, `+4` the pen's
    column, `+8` the pen in pixels from the start of that first column. A line starts
    with `0x0801BFA8(tiles, x)`, which sets them from the line's tiles and its start.
  - The window's data is at `[0x0200283C]`: its line's width in columns at `+0x1BA0`,
    where its lines start at `+0x1BC0` (0 unless the window centres them), its tiles at
    `+0xEE0` and `+0xEE4`, a line every `2 * [+0x1B8C]` bytes.
  - A page's tiles are cleared before it is drawn (`0x08015260`), rows x columns x 64
    bytes.
- **The window's width.** When a message opens, `0x08014D14` measures every line with
  `0x080143E0` (the widths of the font; 6 for a space; the English name for `87xx`) and
  sizes the window to the longest, rounded up to whole columns. A window with a portrait
  is at most 22 columns (176 pixels) wide; the widest English line of the scene is 170
  pixels. The first scene's windows show no arrow while they wait for A.
- **Free space.** The image's data ends at `0x087D6A30` (the disassembly's `rom_end`);
  169424 bytes of zeros follow to the end of the image, 7 MiB from the text code: out
  of a `BL`'s 4 MiB reach. `sub_0801C498` (708 bytes, a glyph routine next to the text
  code) is called by nothing and no word of the image points to it; an mGBA run of 8060
  frames through the title, the new game, the whole scene and the name screen never
  reached it.

## Right-to-left text

The dialogue keeps its pen and lays a line out from the left. For a message of the
Arabic bank, the hook draws each glyph at the mirror of its place on the window's line,
which is the window's width in whole columns:

    left' = columns * 8 - (start & ~7) - pen - width

where `start` is where the window's lines start and `pen` the game's pen from their
first column. The hook ORs the glyph's pixels into the line's tiles at `left'` (up to
three columns for a glyph of 16 pixels), then moves the game's pen and column by the
glyph's width as the game's routine does. A line then starts at the right edge of the
window's text and grows leftwards; the typewriter reveals it from the right, whether the
portrait is on the left or the right of the window. The glyphs are not flipped.

- The OR is safe because the page's tiles are cleared first and a glyph's pixels stay
  inside its advance: neighbours never overlap. The game's routine writes whole columns
  from its scratch column, so every glyph of an Arabic message, the space included, goes
  through the hook.
- The window is sized from the Arabic line widths: the width measure's hook gives the
  right-to-left widths for an Arabic message.
- The speaker's name (`8B` .. `8C`) is right-aligned like the text. Pages, waits, the
  typewriter, its sound and pressing A to hurry it keep working unchanged.

## How right-to-left text is marked

A message is right to left when it lies in the **Arabic bank**, from `0x087E0000` to the
end of the image: the width hook checks the byte it measures (`r4`), the draw hook the
byte being drawn (`r4`).

The scene's block is copied: its table and the messages left in English (the eight
unused ones and the narration) go to the block area at `0x087DC000`, below the bank, and
each translated message to the bank. Both scene entries of the block are repointed to
the copy; the original block stays where it was. A message is found by its 16-bit offset
from the copied block, so every message must lie within 64 KiB of it (the build checks).

## Glyph codes

Every byte from `00` to `7F` is a glyph to every routine that reads a message; no
other byte can be one (`80..91` are commands, `92..FE` stop the counting routines). In a
message of the Arabic bank these codes are the glyphs of the right-to-left font, which
the hooks measure and draw from tables of their own. Codes 0 and 1 are left out (they
make no typing sound): 126 codes, given to the characters the script uses only (the
space, the drawn punctuation, then the forms by code point). The opening uses 92. A
script that needs more than 126 is refused.

## Names of the list

`87xx` inserts name `xx` of the characters' list. The list's names are English, and the
code reads the list from 22 places (the measure, the counting routines and the dialogue
among them), which would each need a hook. Instead the translation keeps the command and the build writes the Arabic
name out in its place, from the script's entry for that name (`rictor`, pinned by its
index and the SHA-256 of the English name): the line then holds the name as Arabic
glyphs, shaped with the words around it. The list keeps its English names for the rest
of the game. A player's name (`80xx`) and an icon (`81xx`) are refused in Arabic text.

## Reaching the hooks

Both hooks are more than 4 MiB from their sites, so each site calls a veneer written
over `sub_0801C498` (its first 32 bytes are pinned by SHA-256):

| Veneer | Hook | Through |
|--------|------|---------|
| `0x0801C498` | `hook_draw` | `bx pc; nop; ldr ip, [pc]; bx ip`: the called routine may clobber ip |
| `0x0801C4A8` | `hook_width` | `ldr r1, [pc]; bx r1`: the measure sets r1 again after the site |

## ROM layout

| Range | Contents |
|-------|----------|
| `0x087D6A30..0x087D7000` | Zeros, left free |
| `0x087D7000..0x087D70E8` | Thumb hooks (`rom/tactics_ogre_arabic_hooks.s`, 232 bytes) |
| `0x087D7400..0x087D7480` | Right-to-left widths, one byte per code |
| `0x087D8000..0x087DC000` | Right-to-left glyphs, 128 bytes per code (two columns of 16 rows) |
| `0x087DC000..0x087E0000` | Copied blocks: tables and the messages left in English |
| `0x087E0000..0x08800000` | The Arabic bank: translated messages |

## Hooks

| Site | Original | Hook |
|------|----------|------|
| `0x08014560` in the width measure (`0x080143E0`) | `ldr r0, =widths; ldrb r1, [r4]; adds r1, r1, r0; ldrb r0, [r1]` | `hook_width`: a BL, two `nop`; `r0` = the width, of the right-to-left font in the bank |
| `0x080158F0` in the dialogue (`0x08015188`) | `bl 0x0801B0C8` | `hook_draw`: outside the bank the call goes on with its arguments; in it, the mirrored OR |

Anchors checked before any change: the measure's widths and what it does with the
width; the dialogue's glyph path (`r4` the text, the arguments); the window's pointer
and its fields (`+0x1BA0` as columns, `+0x1BC0` as the lines' start, a new line at its
first column); the page clear; the pen (`0x0801BFA8` and the game's own pen update at
`0x0801B5C8`); the two scene entries; the whole block (SHA-256); the veneer area
(SHA-256); zeros from `0x087D6A30` to the end.

## Font

The reference font is Noto Kufi Arabic SemiBold, drawn at 11 pixels, the largest size
at which every form of the repertoire (not only those the script uses, so a new word
never changes the size of the others) fits a glyph 16 pixels wide at most, off the top
row, with the baseline on row 12 (letters end on row 11). Coverage from 140 of 255 is
ink (value 1), from 60 the grey around it (value 2), like the game's letters; grey
beyond a glyph's advance is left out. Final and isolated yeh are raised a row when
their dots would leave the glyph. The space is 4 pixels, and `.`, `!` and `:` are drawn
by hand on the letters' last row (the reference font lacks them); the Arabic comma and
question mark come from the font. Lam and alef stay two glyphs.

## Translations

`rom/tactics_ogre_arabic_script.py` pins the 15 messages of the opening scene in the
order the game shows them (block messages 0 to 4, 13 to 15, 5 to 8 and 10 to 12), each
by its index, address, header, SHA-256 and commands, and name 5 of the list. The
Arabic is in `translations/tactics-ogre.json`; the speakers are the hero (not yet named:
the player names him at the end of the scene), Rictor, a mysterious woman who is the
fortune teller, and the fortune teller. A translation keeps every command in order;
line ends after text may move; a page holds its window's lines (the name's line
included), of at most 176 pixels. Speech has no quotation marks.

## Verification

With the reference font the build matches `reference_patch_sha256` (a 4605-byte
patch). In mGBA, from power-on with the patched image:

- all 15 messages, with every page, in Arabic from the right, windows with the portrait
  on either side; the speaker's name at once, the rest typed from the right; Rictor's
  name in Arabic in the text and as a speaker;
- pressing A while a page types, and the full stops and ellipses on the letters' row;
- the name screen, the birth date and the fortune-telling scene that follow, in English
  and unchanged;
- a local probe build that shows a narration message (left in English, in the block
  area) in the first window: English, from the left.

A script for `classic-retro research run` that reaches the first window (inputs only):

```text
run 1200
tap START
run 120
tap START
run 120
tap START
run 400
shot first-message.png
```

## Limits

- Only the first scene's dialogue is in Arabic; its narration, the name screen, the
  fortune-telling that follows, menus and battles stay in English.
- 126 glyph codes for the whole script; a larger script needs another bank of codes
  (for example one per block, chosen by the hooks from the text's block).
- A player's name (`80xx`), icons (`81xx`), choices (`85`) and the commands `82`,
  `83`, `84` and `86` are refused in Arabic text.
- No Latin letters inside Arabic text, no vowel marks, no ligatures, one size.
