# Pokémon Platinum Arabic Renderer v1

Target: *Pokémon Platinum Version* (USA, Rev 0), the second Nintendo DS target. The
[pret/pokeplatinum](https://github.com/pret/pokeplatinum) decompilation (commit
`c248fb3f8cc9934ded800e489567c5c0eeee92eb`, `ROM_REVISION=0`) builds this image byte for
byte, and a local build gave every symbol and address below (`main.nef`, `main.nef.xMAP`).
The translation patches the user's own image, so this is a binary ROM overlay shipped as a
BPS patch. The facts were checked in the image and in DeSmuME with the
[research tools](RESEARCH_TOOLS.md) (`research run` with the `touch` command).

| Item | Value |
|------|-------|
| ROM size | 134217728 bytes (128 MiB) |
| No-Intro Rev 0 | SHA-1 `ce81046eda7d232513069519cb2085349896dec7`, SHA-256 `ede62292aa7f7014ff27d42097e769753380531739889c29b968b67b80f80678` |
| Also accepted | The same image with the header's reserved bytes `0x378..0x3A0` and `0xF80..0x1000` cleared: SHA-1 `c5072bf51a5ecc51ade99d3506c023f5bac3eeb3`, SHA-256 `67de86a1bc8e7eb6479dbbbd6e8f5edfc2fa160576a38e40e06d2180ed63b110` |
| Game code | `CPUE` (`POKEMON PL`), maker `01`, header revision 0 |
| Output | 128 MiB image (same size), shipped as BPS; one reference patch per accepted image |

## Engine facts the overlay relies on

- **Text banks.** `msgdata/pl_msg.narc` (file 404) holds 724 banks, one a NARC member. A
  bank is a count and a seed, then an offset and a length for each string, both XORed
  with `seed * 765 * (index + 1)` (16 bits, in both halves), then the strings: 16-bit
  characters XORed with a key that starts at `(index + 1) * 596947` and grows by 18749 a
  character. Rowan's intro is bank 389 (`TEXT_BANK_ROWAN_INTRO`, 45 strings) and the
  television's comment bank 607 (`TEXT_BANK_ROWAN_INTRO_TV_APP`, one string). Every bank
  rebuilds byte for byte (`engines/pokemon_gen4.py`); 885 strings of other banks are
  packed in 9-bit codes (`F100`) and are not read.
- **Characters.** `0001..01FD` are the fonts' glyphs (`0121` the digits, `012B` and `0145`
  the Latin letters, `01DE` the space); `E000` ends a line, `25BC` waits for A and clears
  the window, `25BD` waits and scrolls it up a row, `FFFE` starts a command (its type, the
  count of arguments, the arguments): `01xx` inserts a string variable (the player's and
  the rival's names), `0200` shows the touch-screen icon. The game's character set puts
  the Korean glyphs from `0400`.
- **Fonts.** `graphic/pl_font.narc` (file 371) holds the NFGR fonts. The system font (0)
  and the message font (1) are the same file: 509 glyphs of 16x16 pixels, 2 bits a pixel
  (0 transparent, 1 the text colour, 2 its shadow, 3 the background), a width each.
  Glyph `n` draws code `n + 1`; `FontManager` takes the count from the file, and a code
  past the last glyph draws `?`. The intro's menus and info pages use font 0, its
  dialogue font 1. `sFontWork` (`0x02101D48`) holds the managers at `+0x94`; a
  manager's width function is at `+0x70`, called with the glyph's index.
- **The printer.** `RenderText` draws a glyph at a time at the printer's pen: the line's
  start at `+0x0A`, the pen at `+0x0C` and `+0x0E`, the letter spacing at `+0x10`, the
  font at `+0x20` (bits 0-3), the string after the current character at `+0x00`. A glyph
  goes to `Window_CopyGlyph(window, gfx, width, height, x, y, table)` (`bl` at
  `0x02002692`, `r4` the printer), then the pen moves by its width. A line end takes the
  pen back to the line's start. The printer's bytes `+0x23..+0x25` are zeroed for every
  printer and never read by the game.
- **The touch-screen icon.** `{YESNO 0}` (`0200`) makes `RenderText` call
  `Text_RenderScreenIndicator(printer, x, y, icon)` (`bl` at `0x0200252E`) with the
  printer's pen: a 24x32 icon right after the text.
- **Menus.** A list menu prints its entries with `PrintEntry(menu, string, x, y)` (`bl`
  at `0x02001702` in `PrintEntries`), 12 pixels in, draws its cursor with
  `ColoredArrow_Print(arrow, window, x, y)` (`0x02001772` in `PrintCursor`) and erases it
  with `Window_FillRectWithColor(window, colour, x, y, 8, 16)` (`0x020017D8` in
  `EraseCursor`). The arrow is a one-character string of the system font. A window's
  width in tiles is at `+0x07`.
- **The intro's windows** (overlay 73, `rowan_intro`, loaded at `0x021D0D80`, 0x2D80
  bytes): the message box, 27 tiles wide and 2 rows; the adventure pages, 24 tiles; the
  control pages' window (`sControlInfoTextWindow` at `0x021D37E4`), from tile 8 and 24
  tiles wide, which reaches the screen's right edge; the menus. The television's comment
  (`tv_app.c`) is centred on the top screen as a block.
- **The ARM9.** At `0x4000`, `0x1023F8` bytes, not compressed, with its NitroSDK footer
  (module parameters at `0xBA0`). Two autoload blocks: ITCM (`0x01FF8000`, `0x660` bytes,
  no BSS) and DTCM (`0x027E0000`, `0x60` bytes, `0x20` of BSS). Overlay 3 is a 32-byte
  dummy at `0x01FF8660` that nothing loads; no other overlay loads into ITCM, whose 32 KiB
  end at `0x02000000`. The ARM9 overlay table (122 entries) follows the ARM9 at
  `0x106600`, `0x1FC` bytes after its footer.

## Right-to-left text

The printer keeps its pen and lays a line out from the left. On a right-to-left line the
glyph hook draws each glyph at the mirror of its pen on the window's width:

    x' = width - x - glyph's width

where `width` is the window's width in pixels. A line then starts at the window's right
edge and grows leftwards; the typewriter reveals it from the right. Pages, scrolls,
waiting for A, the typewriter's speed and pressing A to hurry it keep working unchanged.

- **Direction by line.** At a line's first glyph (the pen at the line's start) the hook
  scans the rest of the line, up to a line end, a new page, a scroll or the string's end
  and skipping commands, for a right-to-left glyph (a code from `01FE` up to `0400`). A
  line with one is right to left; a line without is drawn as the game draws it, so every
  English text of the game is unchanged. The direction is kept in the printer's byte
  `+0x23`.
- **Runs of the game's glyphs.** A name the string inserts, or a Latin word, is a run of
  the game's own glyphs inside a right-to-left line. At the run's first glyph the hook
  measures it with the font manager's widths and the letter spacing (`R`), and draws the
  run left to right as a block at its mirror: each glyph at `width - 2 * x0 - R + x`,
  where `x0` is the run's start. The encoder keeps these runs in reading order, and the
  Arabic around them uses the Arabic font's spaces and punctuation, so a name never
  joins the text beside it. The run's base is kept in the printer's bytes `+0x24..+0x25`.
- **The touch-screen icon** goes to the window's left edge on a right-to-left line (the
  icon hook blits it at x = 0 with `Window_BlitBitmapRect`, loading its graphics as the
  game would). The lines of a page that shows it hold 24 pixels less.
- **Menus.** When a menu's first entry holds a right-to-left glyph, every entry is printed
  right to left (the English rival names too, which then end at the menu's right side),
  and the menu's window is remembered. Its cursor becomes the left arrow (code `01FE`, a
  right-to-left glyph drawn by hand), which the glyph hook mirrors to the right of the
  entries, and the cursor's erase rectangle is mirrored too (`x' = width - x - 8`).
- **The control pages' window** is narrowed from 24 to 22 tiles in overlay 73: it reached
  the screen's right edge, and right-aligned lines would touch it. Its rows face the
  pictures of the buttons, so the translation keeps the original's rows, blank ones
  included.

## Glyph codes

The glyphs are added to fonts 0 and 1 after their 509: codes from `01FE`, which the
English game never uses (they draw `?`), up to `0400`, where the Korean codes start: 514
codes. Only the characters the script uses get codes, in a fixed order: the menus' left
arrow first (always `01FE`), then the space, `.`, `!`, `:` and the forms by code point.
The intro uses 105 (`01FE..0266`). A code the script does not use is a blank glyph with
no width.

## Hooks

The hooks (`rom/platinum_arabic_hooks.s`, ARM946E-S Thumb, 564 bytes) are linked at
`0x01FF8680`, after overlay 3's slot. The overlay grows the ARM9's ITCM autoload block by
32 zero bytes (the slot) and the hooks, so the start-up code copies them to ITCM at boot,
where they stay whatever the game loads; the block is now `0x8B4` bytes, and the DTCM
block's data and the autoload table move up with the module parameters' pointers. Their
two variables (the forced direction of a menu's entries and the window of the last
right-to-left menu) sit in the same block.

| Site | Original | Hook |
|------|----------|------|
| `0x02002692` in `RenderText` | `bl Window_CopyGlyph` | `hook_glyph`: the line's direction at its first glyph; the mirrored `x` of a right-to-left glyph or of a run of the game's glyphs |
| `0x0200252E` in `RenderText` | `bl Text_RenderScreenIndicator` | `hook_icon`: the icon at the window's left edge on a right-to-left line |
| `0x02001702` in `PrintEntries` | `bl PrintEntry` | `hook_entry`: a menu whose first entry is right to left prints every entry so, and its window is remembered |
| `0x02001772` in `PrintCursor` | `bl ColoredArrow_Print` | `hook_cursor`: the left arrow in a remembered window |
| `0x020017D8` in `EraseCursor` | `bl Window_FillRectWithColor` | `hook_erase`: the erased rectangle at its mirror in a remembered window |

Anchors checked before any change: `RenderText`'s glyph path (the printer in `r4`, its
font and pen, the pen moved by the width) and its icon call; the entries, cursor and erase
calls; the first bytes of every routine the hooks call; `Window_GetWidth` (`+0x07`); the
font managers (`Font_TryLoadGlyph`'s literal `0x02101D48`) and a manager's width function
at `+0x70`; the ITCM block (address, size, no BSS); overlay 3 below `0x01FF8680` and no
other overlay in ITCM; overlay 73 (its load address, size and the window template); the two
fonts (SHA-256); the two banks (SHA-256 and string counts) and every translated original
(SHA-256 and commands).

## Image layout

The files and the ARM9 are written back through `patching.nitro`, shared with New Super
Mario Bros.:

| Part | Original | Arabic image |
|------|----------|--------------|
| ARM9 | `0x4000`, `0x1023F8` bytes | `0x4000`, `0x10264C` bytes (the ITCM block `+0x254`) |
| ARM9 overlay table | `0x106600` | `0x63C3200`, past the used area (`move_arm9_overlay_table`) |
| `graphic/pl_font.narc` (file 371) | `0x3DEB800..0x3E0C824` | `0x63C4200..0x63F8A14`: it grew, so it moved past the used area |
| `msgdata/pl_msg.narc` (file 404) | `0x162DE00..0x1A54358` | In place: the Arabic banks fit where the English ones were |
| Overlay 73 (file 73) | `0x347000..0x349D80` | In place, one byte changed (the window's width) |
| Used size | `0x63C303C` | `0x63F8A14` |

The header's secure area CRC (`0x6C`) follows the changed calls, which lie in the secure
area's unencrypted part (`secure_area_crc`), and the header CRC comes last.

## Font

The reference font is Noto Kufi Arabic SemiBold, drawn at 11 pixels, the largest size at
which every form of the repertoire (not only those the script uses) fits a glyph of 16x16
pixels off the top row, with the baseline on row 12 like the game's letters. Coverage from
110 of 255 is ink (value 1); the game's one-pixel shadow (value 2) goes right, below and on
the diagonal of the ink, inside the glyph's advance, so it never covers the neighbour on
the right, which is painted first. Final and isolated meem and yeh are raised, a row at a
time up to two rows, when their tails would leave the glyph. The space is 4 pixels; `.`,
`!`, `:` and the menus' left arrow are drawn by hand; the Arabic comma and question mark
come from the font. Lam and alef stay two glyphs.

## Translations

`rom/platinum_arabic_script.py` pins 38 strings in the order the game shows them: strings
0 to 36 of bank 389 and the television's string, each by its bank, index, SHA-256 and
commands, with the window it is shown in:

| Window | Width | Rows | Strings |
|--------|-------|------|---------|
| The message box | 216 px (192 beside the icon) | 2, typed; `\r` a new page, `\f` a scroll from the last row | Rowan's dialogue |
| The control pages | 176 px | up to 12, shown at once; 2 and 3 keep the original's rows, blank ones included | 2 to 5 |
| The adventure pages | 192 px | up to 12, shown at once | 10 to 15 |
| The info menu | 128 px, from 12 | one | 31 to 33 |
| Yes and No | 48 px, from 12 | one | 34, 35 |
| The rival's names | 112 px, from 12 | one | 36 |
| The television | 256 px | shown at once, centred | bank 607's string |

The Arabic is in `translations/platinum.json`, in the engine's notation. A translation
keeps every command in order (`\r`, `\f`, `{STRVAR_1 3, 0, 0}` the player's name,
`{STRVAR_1 3, 1, 0}` the rival's, `{YESNO 0}`); line ends after text may move. A name
takes 48 pixels in the measure. String 6 is the icon alone: its translation adds an
Arabic space, so the line is right to left and the icon sits at the box's left edge like
the other Arabic messages. The rival's ready names (strings 37 to 44) stay English: the
one chosen is his name for the rest of the game.

## Verification

With the reference font the build matches the reference patch of each accepted image
(13412-byte patches). In DeSmuME (libretro, `desmume_cpu_mode=interpreter`, the pointer as
the touch screen), from power-on with the patched image:

- every dialogue page, both scrolls and every new page, typed from the right;
- the info menu, right-aligned with the left arrow on the right, the arrow erased where it
  was when it moves; the four control pages beside their buttons and the six adventure
  pages;
- the question answered on the touch screen and the Poké Ball's button, touched, with the
  icon at the box's left edge;
- the boy or girl choice, the naming keyboard (the game's own font) and the name inside
  the Arabic confirmation, left to right; the rival's menu with the English names
  right-aligned, and his name inside Arabic lines;
- Rowan's farewell, the television's comment centred in white, then the player's room in
  English, from the left.

A script for `classic-retro research run` that reaches every screen, inputs only (the
frame holds both screens, 256x384; the touch screen is its lower half):

```text
# Core: desmume_libretro with --option desmume_cpu_mode=interpreter
# --option desmume_pointer_mouse=enable --option desmume_pointer_type=touch.
run 1500
tap START 4 60
run 200
tap A 4 60
run 400
shot 01-hello.png
tap A 4 60
run 100
shot 02-welcome.png
tap A 4 200
shot 03-my-name.png
tap A 4 100
tap A 4 100
shot 04-professor.png
tap A 4 100
tap A 4 100
shot 05-first-adventure.png
tap A 4 150
tap DOWN 4 30
tap UP 4 30
tap A 4 200
shot 06-info-menu.png
# Control info: four pages, then the question answered on the touch screen.
tap A 4 150
shot 07-control-buttons.png
tap A 4 150
shot 08-control-xy.png
tap A 4 150
shot 09-control-touch-screen.png
tap A 4 150
run 120
shot 10-control-mark.png
tap A 4 150
shot 11-understood.png
tap A 4 200
shot 12-use-touch-screen.png
run 60
touch 128 272 6 60
run 400
shot 13-anything-else.png
# Adventure info: six pages.
tap A 4 200
tap DOWN 4 30
shot 14-adventure-choice.png
tap A 4 200
shot 15-adventure-world.png
tap A 4 150
shot 16-adventure-speak.png
tap A 4 150
shot 17-adventure-paths.png
tap A 4 150
shot 18-adventure-battles.png
tap A 4 150
shot 19-adventure-power.png
tap A 4 150
shot 20-adventure-growth.png
tap A 4 250
# No info needed: Pokémon, and the Poké Ball on the touch screen.
tap A 4 200
tap DOWN 4 20
tap DOWN 4 20
shot 21-no-info.png
tap A 4 200
tap A 4 200
shot 22-widely-inhabited.png
tap A 4 150
shot 23-poke-ball.png
tap A 4 150
touch 128 292 6 120
run 300
shot 24-touch-the-ball.png
touch 128 292 6 30
run 400
shot 25-live-alongside.png
tap A 4 150
shot 26-play-together.png
tap A 4 150
shot 27-work-together.png
tap A 4 150
shot 28-battle.png
tap A 4 150
shot 29-bonds.png
tap A 4 150
shot 30-what-do-i-do.png
tap A 4 150
shot 31-research.png
tap A 4 150
shot 32-about-yourself.png
# The player: a boy, named on the keyboard.
tap A 4 150
tap A 4 200
shot 33-boy-or-girl.png
tap A 4 250
tap A 4 200
tap A 4 150
shot 34-confirm-boy.png
tap A 4 100
shot 35-yes-no.png
tap A 4 250
shot 36-your-name.png
tap A 4 300
tap A 4 30
tap RIGHT 4 20
tap A 4 30
tap RIGHT 4 20
tap A 4 30
tap START 4 30
tap A 4 300
run 200
shot 37-confirm-name.png
# The rival: Barry from the menu.
tap A 4 100
tap A 4 250
shot 38-so-you-are.png
tap A 4 150
tap A 4 150
tap A 4 150
tap A 4 250
shot 39-rival-names.png
tap DOWN 4 30
tap A 4 250
shot 40-confirm-rival.png
tap A 4 150
tap A 4 300
shot 41-farewell.png
tap A 4 150
tap A 4 150
shot 42-journey.png
tap A 4 150
tap A 4 150
shot 43-discover.png
tap A 4 150
tap A 4 150
shot 44-leap.png
tap A 4 150
tap A 4 400
run 600
shot 45-television.png
tap A 4 300
tap A 4 300
shot 46-room.png
```

DeSmuME's clock is the host's, so a run may differ from another by a few frames late in
the intro (a page arrow's bob, one letter of the typewriter).

## Limits

- Only the new-game intro is in Arabic; the naming keyboard, the touch screen's YES and
  NO buttons (pictures), the rival's ready names and the rest of the game stay English.
- A name the player types is Latin, drawn left to right inside the Arabic lines.
- 514 glyph codes for the whole script (the intro uses 105).
- No vowel marks, no ligatures, one size.
- Commands other than line breaks, names and the touch-screen icon (colours, sizes,
  cursor moves) are refused in Arabic text.
