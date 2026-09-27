# Chrono Trigger Arabic Renderer v1

Target: *Chrono Trigger* (USA, SNS-ACTE-USA), the first Super NES target. The
[dscotton/ct_disassembly](https://github.com/dscotton/ct_disassembly) disassembly (commit
`eeae27acdb6565e96d1d796a3d60792c250c0aa1`) matches this ROM and names its code, but it
takes the ROM's data from the user's ROM at fixed addresses, so this is a binary ROM
overlay: it patches the user's ROM and ships as a BPS patch of it. The target was built
from direct analysis of the ROM: its text engine's 65C816 code and the game running in
snes9x with the [research tools](RESEARCH_TOOLS.md). The disassembly served as a reference
to check it: every routine, table and variable below is where the disassembly has it, and
its name there is given in brackets.

| Item | Value |
|------|-------|
| No-Intro | *Chrono Trigger (USA)*: one ROM, no copier header |
| ROM | 4194304 bytes, HiROM FastROM (map `31`): CRC32 `2D206BF7`, SHA-1 `de5822f4f2f7a55acb8926d4c0eaa63d5d989312`, SHA-256 `06d1c2b06b716052c5596aaa0c2e5632a027fee1a9a28439e509f813c30829a9` |
| Header | `CHRONO TRIGGER` at `$FFC0`; `classic-retro detect` names the platform and the game |
| Output | The ROM, the same size, its header's checksum set again. Shipped as BPS |

## Engine facts the overlay relies on

- **Mapping.** HiROM: banks `$C0` to `$FF` are the ROM's 64 KiB banks in order, so
  `$F7:0000` is offset `0x370000`.
- **Strings.** A string table is a run of 16-bit pointers into its own bank; an event
  names a table (a 24-bit address) and a string by its number. A string ends with `00`.
  The opening's table is `$F7:0000` (456 strings); strings may share bytes (the first,
  which plays the opening with pauses, runs on through the next five).
- **Codes** (their routines' table at `$C2:5903` [`TextCtrlCodeTable`]). `01`-`02` and a
  byte: a two-byte character (the Japanese kanji's; unused in the US dialogue). `03` and a
  byte: a pause. `05` a new line, `06` a new line indented under a speaker's name; `0B` a
  new box, `0C` a new box indented; `07`-`0A` the same waiting for the button. `0D`-`0F` a
  number and `11` a character's name, from the event's values; `12` and a byte: a
  technique's or an enemy's name, or a word. `13`-`19` the party's names, `1A` Crono's
  again (from his name's own address), `1B`-`1D` the party in battle order, `1E` Nadia's,
  `1F` an item's, `20` the time machine's. `21`-`9F`: a word of the substring dictionary
  (`$DE:FA00` [`TextSubstringPtrs`]: 127 pointers into bank `$DE`, each to a length and
  that many characters: "the", "you", "CHANCELLOR:"...). `A0`-`FF`: the dialogue font's
  characters (capitals, small letters, digits, signs; `EF` the space, `F1` "…")
  ([`engines/chrono_trigger.py`](../src/classic_retro/engines/chrono_trigger.py)).
- **The text engine** (bank `$C2`, its direct page at `$0200`). A message's start
  (`$C2:57DF` [`Text_RenderString`]) takes the string's address from its table into
  `$31`-`$33` and the pen (`$34`) to 8. Each frame (`$C2:5823` [`Text_EngineTick`])
  first runs the engine's state (`$15`, from `$C2:584A` [`Text_DispatchState`]): a control
  code `00` or `04`-`0C` becomes that state, and a new line or box puts the pen at 8, or
  at 20 when indented. Then it runs the reading mode (`$30`, its table at `$C2:5842`): 0
  reads the string (`$C2:58B2` [`Text_DecodeLoop`]): a character is drawn, a dictionary
  word or a name becomes mode 1 (an expansion from `$37`-`$39`, `$3A` characters,
  `$C2:5BF5` [`Text_PlaySubstring`]), a number mode 2 or 3; a control code goes through
  its table.
- **The glyph routine** (`$C2:5DC4` [`Text_EmitGlyph`]). A glyph is 12x12 pixels of two
  bits: its left 8 pixels at `$FF:2060` + code x 24 (a row's two planes, then the next
  row), its right 4 in a nibble of `$FF:3860` + (code / 2) x 24; its width is at
  `$C2:60E6` + code - `A0` [`CharacterWidthStandardTable1`]. The glyph goes into the tile
  buffer (`$7E:F000`): rows 0-3 in the lower half of a line's first tile row, rows 4-11 in
  the second, each column's tile from a table: `$C2:5FE6` for tiles of 2 bits, window
  style 0 (`$C2:5E36` [`Text_DrawGlyph2bpp`]), or `$C2:6066` for tiles of 4 bits, the
  other styles (`$C2:5F07` [`Text_DrawGlyph4bpp`]), two tile rows `$100` or `$200` apart.
  The glyph's first byte is ORed, the ones on its right written over. The pen then moves
  on by the width. The whole line reaches VRAM as it is written: a pattern put at the
  right of the pen shows at once.
- **The font's look.** The letters are white (value 3) with a shadow a pixel right and
  below (1), darker in the corner (2), inside the glyph's width.

## Right-to-left text

The overlay's hooks (`rom/chrono_trigger_arabic_hooks.s`, 685 bytes) live at `$DB:8000`:
bank `$C2` has no room, so they are reached with long calls and jumps and leave through
the engine's own code and returns.

- **Arabic messages.** At a message's start (`$C2:57F7`), a string whose address is in the
  overlay's list is read from its Arabic text instead, in bank `$DB`. The English strings
  stay where they were, as they were; the hooks tell an Arabic message by its bank.
- **Glyphs.** In an Arabic message a byte from `21` is a glyph of the Arabic font (codes
  `21`-`FF`: 223), and a byte below keeps its meaning: line and box breaks, pauses, names.
- **Mirrored draw.** Each Arabic glyph is drawn at `256 - pen - width` while the pen moves
  on as the engine's does, so a line starts at the box's right side and the engine's
  indent (pen 20) falls on the right. Its bytes are ORed into the tile buffer, in both
  layouts: the glyph on the right shares a byte with it, which the engine's own routine
  would write over.
- **Names and numbers.** A name, or a number, the engine expands is drawn whole, left to
  right, as a block that ends at the mirror of the pen (its width from the font's widths),
  and the engine is told that its last character is done. So `{Lucca}` in an Arabic line
  shows the name the player gave, in Latin letters, the right way round.

## Glyphs

The reference font is Noto Kufi Arabic SemiBold. The glyphs come from a cell of 12x12
pixels, the letters on row 8 (the row under the English capitals), at 9 pixels: the
largest size at which every form of the repertoire and every digit fits the cell with its
shadow (from 13 down; at 10 seen and sheen are 13 and 14 pixels wide). Coverage from 128 of
255 is ink, and a dot between 60 and 128 keeps its strongest pixel. The merged dots of two-
and three-dot letters are drawn apart (`separated_dots`); hamza above alef is drawn by hand
over the font's alef (`alef_with_mark`), and final and isolated yeh are raised a row
(`raised_form`). `.`, `,`, `:`, `!`, `-`, `…`, `،`, `؛` and `؟` are drawn by hand. Every
glyph is white with the game's shadow, all of it inside its width; a form that joins the
glyph on its right runs to its edge, any other keeps a free column. The space is 4 pixels,
as the English's.

## Layout

The encoder lays each box out itself, a word at a time: a line runs from the pen at 8 (or
20, indented) to 240, as the English's widest lines do, and a box shows four lines. A
message that starts with the speaker's name and a colon (`الأم: `) has its other lines and
boxes indented, as the English does (`06`, `0C`). A name counts 55 pixels, the widest five
letters of the name screen. The glyphs of a line are stored in reading order: the first
is drawn at the right.

## The overlay's room

| Address | Content |
|---------|---------|
| `$DB:8000` | the hooks: `setup_hook` at `+0`, `reader_hook` at `+$3D`, `glyph_hook` at `+$D1` |
| `$DB:8400` | the list: 6 bytes a message (the English's address, the Arabic's); a zero bank ends it |
| `$DB:8800` | a width a glyph, from code `21` |
| `$DB:8900` | 48 bytes a glyph: 24 of its left 8 pixels, 24 of its right 4 (high nibble) |
| `$DB:B400` | the Arabic messages |

The room is zeros at the end of bank `$DB` (`$DB:7FF4` to `$DB:C00F`); the overlay uses
`$DB:8000` to `$DB:BFFF` and checks that it is empty.

| Site | Original | Arabic |
|------|----------|--------|
| `$C2:57F7`, in `Text_RenderString` | `LDA $0F`; `STA $33` | `JSL setup_hook` |
| `$C2:58B2`, `Text_DecodeLoop` | `LDA [$31]`; `REP #$20` | `JML reader_hook` |
| `$C2:5DC4`, `Text_EmitGlyph` | `REP #$20`; `LDA $35` | `JML glyph_hook` |

Anchors checked before any change: the ROM (SHA-256); the message start's direct page and
table read; where the hooks go back (a character drawn; `LDA #$10; STA $15; RTS`; the
dictionary; the control codes' table; the glyph routine after its site and its end); the
font's addresses and bank and its widths' address in the glyph routine; the two tile
layouts' steps and column tables; the room, zeros; each translated message (its table's
pointer and the SHA-256 of its bytes). The build then sets the header's checksum and checks
that nothing but the sites, the room and the checksum changed.

## Translations

`rom/chrono_trigger_arabic_script.py` pins three messages of the opening's table. The
Arabic is in `translations/chrono-trigger.json`, a line a box, `{line}` where a line of the
box must end. The three were chosen to be unlike:

| Entry | Message | What it tries |
|-------|---------|---------------|
| `opening.get_up` | 6: his mother wakes Crono | two lines under her name, the second indented |
| `opening.the_fair` | 8: the fair, and behaving | a long line the encoder wraps, a second box indented |
| `opening.lucca` | 11: Lucca's invitation | the name the player gave Lucca, drawn left to right in an Arabic line |

They use 55 glyphs (`21..57`) and 181 bytes of Arabic.

## Verification

With the reference font the build matches the reference patch (2019 bytes). In snes9x
(`snes9x_libretro`), from power-on with the patched ROM: the Battle Mode and name screens
and the first box ("Crono…", "Crono!", "Good morning, Crono!") in English as before;
message 6 in Arabic from the right, its second line indented on the right; message 7 in
English; message 8 in Arabic, typed from the right, over two lines and a second box. Message
11 is said downstairs; a research build that sends message 7 to its Arabic shows it in the
game: "Lucca" left to right after «صحيح،», the "!" on its left. The script, inputs only:

```text
# Core: snes9x_libretro.
run 2340
tap START
run 120
# New Game, the battle mode, then the name.
tap A
run 180
tap A
run 180
tap A
run 1500
tap START
run 60
tap START
run 3840
# The opening's boxes: A for each.
tap A
run 150
tap A
run 150
tap A
run 150
tap A
run 150
shot mother.png
```

The RetroPad's A is the Super NES's A.

## Limits

- Three messages are in Arabic; every other message, the menus and the rest of the game
  stay English.
- 223 glyph codes for all the Arabic; a message holds no Latin letters, and a name is the
  player's, in Latin letters.
- A box shows four lines of 232 pixels (220 indented); the encoder refuses more.
- The font is 9 pixels; no vowel marks, lam and alef stay two glyphs.
- The hooks tell an Arabic message by its bank: no dialogue table of the game lies in
  bank `$DB`.
