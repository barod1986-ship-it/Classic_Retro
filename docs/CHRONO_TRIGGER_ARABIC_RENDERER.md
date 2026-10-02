# Chrono Trigger Arabic Renderer v2

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
| Output | The ROM with a third and a fourth MiB (banks `$40`-`$5F` of an ExHiROM, map `35`, size code `0D`), its header's checksum set again, in the header and in its copy. Shipped as BPS |

## Engine facts the overlay relies on

- **Mapping.** HiROM: banks `$C0` to `$FF` are the ROM's 64 KiB banks in order, so
  `$F7:0000` is offset `0x370000`. Banks `$00` to `$3F` show the upper halves of the
  first banks (`$00:8000` is `$C0:8000`), and the game reads tables there: `$00:F300`,
  `$00:F800` (a sine table), `$00:FD00` (bit reversal), `$00:FE00` (random numbers),
  and its vectors point into `$00:FF00`, whose stubs jump long into the ROM.
- **Strings.** The dialogue is in string tables: a table is a run of 16-bit pointers into
  its own bank, its first pointing just past its last entry; an event names a table (a
  24-bit address, `EventCmd_SetDialogTable`) and a string by its number, and may name a
  table from its middle (a table of 456 strings is reached as two of 256 and 200). A
  string ends with `00`. Fifteen tables hold the dialogue (`$D8:D000`, `$D8:DD80`,
  `$DE:C000`, `$DE:E300`, `$F6:A000`, `$F6:B230`, `$F7:0000`, `$F7:4900`, `$F8:4650`,
  `$F9:B000`, `$FC:BA00`, `$FF:4460`, `$FF:5860`, `$FF:6B00`, `$FF:8400`): 4600 strings,
  186 KB. Strings may share bytes: the first table's first string, the opening played
  with pauses, runs on through the next five, each named from a pause of nothing.
- **Codes** (their routines' table at `$C2:5903` [`TextCtrlCodeTable`]). `01`-`02` and a
  byte: a two-byte character (the Japanese kanji's; unused in the US dialogue). `03` and
  a byte: a pause of fifteen frames that many times; `03 00` closes the box where it
  stands. `05` a new line, `06` a new line indented under a speaker's name; `0B` a new
  box, `0C` a new box indented, each after the player's button; `09` and `0A` a new box
  at once, without the button (after a pause, in a timed scene); `07` and `08` a new
  line after the player's button, the box kept, never used. `0D`-`0F` a number and `11` a character's name,
  from the event's values; `12` and a byte: a technique's or an enemy's name, or a word.
  `13`-`19` the party's names, `1A` Crono's again (from his name's own address),
  `1B`-`1D` the party in battle order, `1E` the word "Nadia", `1F` an item's name, `20`
  the time machine's. `21`-`9F`: a word of the substring dictionary (`$DE:FA00`
  [`TextSubstringPtrs`]: 127 pointers into bank `$DE`, each to a length and that many
  characters: "the", "you", "CHANCELLOR:"...). `A0`-`FF`: the dialogue font's characters
  (capitals, small letters, digits, signs; `EF` the space, `F1` "…")
  ([`engines/chrono_trigger.py`](../src/classic_retro/engines/chrono_trigger.py)).
- **The text engine** (bank `$C2`, its direct page at `$0200`). A message's start
  (`$C2:57DF` [`Text_RenderString`]) takes the string's number from `$0C` and its table
  from `$0D`-`$0F`, the string's address from the table into `$31`-`$33` and the pen
  (`$34`) to 8. Each frame (`$C2:5823` [`Text_EngineTick`]) first runs the engine's state
  (`$15`, from `$C2:584A` [`Text_DispatchState`]): a control code `00` or `04`-`0C`
  becomes that state, and a new line or box puts the pen at 8, or at 20 when indented.
  Then it runs the reading mode (`$30`, its table at `$C2:5842`): 0 reads the string
  (`$C2:58B2` [`Text_DecodeLoop`]): a character is drawn, a dictionary word or a name
  becomes mode 1 (an expansion from `$37`-`$39`, `$3A` characters, `$C2:5BF5`
  [`Text_PlaySubstring`]), a number mode 2 or 3; a control code goes through its table.
- **The dialogue driver** (bank `$C0`, `$C0:2126` [`Dialog_HandleRenderResult`]) reads
  the state after each tick: a line (`05`-`08`) scrolls, and after the fourth waits for
  the button; a box after the button (`0B`, `0C`) waits with its timer at `$FFFF`; a box
  at once (`09`, `0A`) goes on with the timer as it is; a pause (`03`) sets the timer to
  fifteen frames times its byte, and a pause of nothing closes the box as the string's
  end does.
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
- **The box's tiles.** The box's tile map (VRAM `$1C00`, `$C0:2B78`
  [`Dialog_BuildTextAreaTilemap`]) shows the text's tiles from `$2900`: a line every
  `$40`, a row of tiles every `$10`, the columns from 16 at `$20` further. Column 1 is the
  pen's 8: the English text runs from `$08` to `$F0` of the 256 pixels.
- **The choice cursor** (`$C0:F05E` [`Dialog_DrawChoiceCursor`], in the vertical blank,
  the PPU's registers on its direct page). A choice's cursor is two by two tiles
  (`$28FC`-`$28FF`) at column 2 of the choice's line of the box (`$1C02`, `$1C42`,
  `$1C82`, `$1CC2`); the other choices' cells show their text tiles again (`$2902`,
  `$2912`; `$2942`...). The English indents a choice's text by three spaces to leave the
  cursor its place.
- **The font's look.** The letters are white (value 3) with a shadow a pixel right and
  below (1), darker in the corner (2), inside the glyph's width.

## The added banks

The ROM's 4 MiB have no room for the dialogue: 67 KB of zeros in all. The overlay adds
a third and a fourth MiB, banks `$40` to `$5F`: the header's map mode goes from `$31` to
`$35` (ExHiROM) and its size code from `$0C` to `$0D`, as a 48 Mbit cartridge's (Tales
of Phantasia's, Star Ocean's). Under that mapping the console reads banks `$00` to
`$1F`'s upper halves from the added banks' upper halves, where it read the ROM's first
banks before, and the game does (the tables and stubs above): so **the upper half of
each added bank is a copy of the upper half of the ROM's bank of the same number**,
the mirror the game had, and the overlay uses only the lower halves. The copy of bank
`$C0` carries the header's copy at `$40:FFC0`, which snes9x reads for an ExHiROM
(`BIGFIRST`: the header of the part past 4 MiB scores at least the first's). The
checksum is a 48 Mbit cartridge's: the sum of the bytes, the last 2 MiB counted twice,
in the header and in its copy.

| Address | Content |
|---------|---------|
| `$40:0000` | the hooks: `setup_hook` at `+0`, `reader_hook` at `+$75`, `glyph_hook` at `+$10D`, `choice_hook` at `+$2EE` |
| `$40:0800` | the bank index: a word a bank from `$C0`, the offset in bank `$40` of its first entry in the list, 0 for none |
| `$40:0900` | the list of translated tables: 8 bytes each: the table's address (3), its strings times two (2), its entries' address (3); a zero bank ends it |
| `$40:2000` | a width a glyph, from code `21` |
| `$40:2100` | 48 bytes a glyph: 24 of its left 8 pixels, 24 of its right 4 (high nibble) |
| `$41:0000` | the tables' entries, a block a table: 3 bytes a string, its Arabic's address, or zero for the English |
| `$42:0000` to `$5F:7FFF` | the Arabic messages, none across the end of a lower half |

Everything else in the lower halves is `FF`.

## Right-to-left text

The hooks (`rom/chrono_trigger_arabic_hooks.s`, 910 bytes) live at `$40:0000`: bank
`$C2` has no room, so they are reached with long calls and jumps and leave through the
engine's own code and returns.

- **Arabic messages.** At a message's start (`$C2:57F7`), the string's pointer in its
  table (the table's address plus twice the number) is looked for in the list, by the
  table's bank through the index: a table that holds it gives the string's entry, and an
  entry that is not zero is the string's Arabic, read instead. A table named from its
  middle finds the same entries. The English strings stay where they were, as they were;
  the hooks tell an Arabic message by its bank (`$42` to `$5F`).
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
  shows the name the player gave, in Latin letters, the right way round; an item's name
  the same.
- **The choice cursor.** After an Arabic message (the last message's bank, `$0233`), the
  cursor's cells are at column 29 (`$1C1D`, `$1C5D`...), and the other choices' cells show
  the text tiles of that column (`$292D`, `$293D`...); a choice's line starts with spaces
  that take the pen on to 28, as the English's three spaces do, so its text ends at the
  mirror's 228, left of the cursor. After an English message the cursor is where it was.

## Glyphs

The reference font is Noto Kufi Arabic SemiBold. The glyphs come from a cell of 12x12
pixels, the letters on row 8 (the row under the English capitals), at 9 pixels: the
largest size at which every form of the repertoire and every digit fits the cell with its
shadow (from 13 down; at 10 seen and sheen are 13 and 14 pixels wide). Coverage from 128 of
255 is ink, and a dot between 60 and 128 keeps its strongest pixel. The merged dots of two-
and three-dot letters are drawn apart (`separated_dots`); hamza above alef is drawn by hand
over the font's alef (`alef_with_mark`), and final and isolated yeh are raised a row
(`raised_form`). `.`, `,`, `:`, `!`, `-`, `…`, `،`, `؛`, `؟`, `«`, `»`, `(`, `)` and `♪`
are drawn by hand; the quotes and the brackets as their mirror images, as a right-to-left
run shows them. Every glyph is white with the game's shadow, all of it inside its width;
a form that joins the glyph on its right runs to its edge, any other keeps a free column.
The space is 4 pixels, as the English's.

## Layout

The encoder lays each box out itself, a word at a time: a line runs from the pen at 8 (or
20, indented) to 240, as the English's widest lines do, and a box shows four lines. A
message that starts with the speaker's name and a colon (`الأم: `, `{Marle}: `) has its
other lines and boxes indented, as the English does (`06`, `0C`). A name counts 55
pixels, the widest five letters of the name screen; an item's name 80, the widest of the
game's; a number 8 a digit. A choice's line (`{choice}`) starts with the spaces that
take the pen on to 28, and a line the layout breaks starts where the engine starts it,
indented under a speaker. Which lines are choices is the event's to say: its decision
command (`C0`, `Dialog_OpenDecisionBox` at `$C0:3674`) names the first and the last line
of the message's last box, and takes the answer by its line. The script pins those
lines for the 100 decisions of the three tables (`DECISIONS`, read from the location
events), and the build refuses a translation whose `{choice}` lines are elsewhere, or a
`{choice}` in another message. `{box auto}`
starts a box at once (`09`, `0A`), `{pause xx}` passes to the game, and `{pause 00}`
starts the message over: what follows is laid out as a message of its own, as the game
shows it, so the tail messages of a chain encode to the tail of the chain's Arabic and
are stored once. The glyphs of a line are stored in reading order: the first is drawn at
the right.

| Site | Original | Arabic |
|------|----------|--------|
| `$C2:57F7`, in `Text_RenderString` | `LDA $0F`; `STA $33` | `JSL setup_hook` |
| `$C2:58B2`, `Text_DecodeLoop` | `LDA [$31]`; `REP #$20` | `JML reader_hook` |
| `$C2:5DC4`, `Text_EmitGlyph` | `REP #$20`; `LDA $35` | `JML glyph_hook` |
| `$C0:F05E`, `Dialog_DrawChoiceCursor` | `PHD`; `REP #$20`; `LDA #$2100` | `JML choice_hook`; `NOP`; `NOP` |

Anchors checked before any change: the ROM (SHA-256) and its header; the message start's
direct page and table read; where the hooks go back (a character drawn; `LDA #$10; STA
$15; RTS`; the dictionary; the control codes' table; the glyph routine after its site and
its end; the cursor routine after its site, its two ends and its first slot's cells and
tiles); the font's addresses and bank and its widths' address in the glyph routine; the
two tile layouts' steps and column tables; the vectors' stubs the mirror carries; each
translated table (its count) and message (its table's pointer and the SHA-256 of its
bytes). The build then sets the header's checksum and checks that nothing but the sites,
the header's three fields and the added banks changed, and that the added banks hold the
mirrors, the overlay's data and the fill and nothing else.

## Translations

`rom/chrono_trigger_arabic_script.py` pins the messages of three whole string tables, by
their table, their number and the SHA-256 of each with its command skeleton; each entry's
id is the table's key and the message number.

| Table | Key | Messages | What |
|-------|-----|----------|------|
| `$F7:0000` | `truce` | 0-455 (0 runs on through 5, 63 through 66, 198 and 199, 214 through 217) | Crono's house and Truce in 1000 and in 600, Truce Canyon with the Gate, the prison's cell, Lab 32 with Johnny's race, the Proto Dome with Robo's awakening, the Sun Keep and the Geno Dome |
| `$FC:BA00` | `fair` | 0-398 | Leene Square with the Millennial Fair and Lucca's Telepod, the trial, the castle's cellars with the Rainbow Shell, Melchior's hut, Norstein Bekkler's tent, the Tyrano Lair's cells, the Lavos crater, Zeal's sealed palace and Death Peak |
| `$F7:4900` | `guardia` | 0-1202 (330 runs on through 333, 355 through 375, 535 through 547) | Castle Guardia in 600 and 1000 with the King, Queen Leene, the Chancellor and Yakra, the knights and the kitchen; the domes of 2300 A.D. with Doan and the Info center; Medina; the End of Time with Gaspar and Spekkio; Ozzie, Slash, Flea and Magus; the Blackbird and Dalton; the Reptites' land |

Another table is added from the user's own ROM by four commands of the
`chrono-trigger` group (`rom/chrono_trigger_tables.py`). `tables` lists the fifteen with
their counts and which are translated. `new-table ROM ADDRESS KEY` writes two local
files: a workspace of the table's originals, and a plan that holds none of the game's
text: each message's pin (its number, SHA-256 and commands), the messages that run on
inside another (a string that starts just after another's `{pause 00}`), the decision
boxes and what is left to review. The decisions come from the location events (a table
of three-byte pointers at `$FC:F9F0`, one compressed script a location): a scan takes a
`B8` with the table's address, then a `C0`, `C3` or `C4` with a string's number and the
lines of its choices, and keeps a decision only when those lines are the original's
indented option lines; anything else is for a person to decide. On the three tables
translated so far the scan gives every pinned decision but `guardia.659` and
`guardia.1201`, which it lists for review, and every pin and chain. `check-table` checks a
translated workspace, or a batch of it, message by message as the build does, chains
included, and `adopt-table` writes the table into `TABLES`, `DECISIONS` and the pins and
its Arabic into the shipped file, whose contexts say only where each message is; the
digests, the reference patch and the overlay's pins are then regenerated as for any
change of the translation.

The Arabic is in `translations/chrono-trigger.json`, a line a box, `{line}` where a line
must end, `{choice}` at a choice's line, `{box auto}` for a box at once; its `glossary`
fixes how every place, character, item and term is written. A translation keeps its
original's commands but the layout: its skeleton must equal the original's, which the
build takes from the ROM and the script pins too; the word "Nadia" (`1E`) is text, written
in Arabic.

## Verification

With the reference font the build matches the reference patch (its SHA-256 is pinned with
the target, and the build report's `matches_reference` says so). In snes9x
(`snes9x_libretro`) through `classic-retro research run`, from power-on with the patched
ROM, the 6 MiB ExHiROM boots as the ROM did: the Battle Mode and name screens, the
opening's "Crono…" boxes at the top of the black screen, then Crono's room. The mother's
messages are in Arabic from the right, a line typed glyph by glyph, the second line
indented on the right; a message of two boxes waits for the button between them. The
script, inputs only:

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
run 360
shot mother.png
```

The RetroPad's A is the Super NES's A.

Any message can be shown the same way after an edit: the entry of the mother's first
message (the `truce` table, number 6) pointed at another message's Arabic makes that
message the first shown, three bytes in the patched ROM:

```python
import struct
from pathlib import Path
from classic_retro.rom import chrono_trigger_arabic as overlay
from classic_retro.rom.chrono_trigger_arabic_script import TABLES

rom = bytearray(Path("Chrono Trigger (USA) (Arabic).sfc").read_bytes())
redirects = overlay.read_redirects(bytes(rom))  # (table, number) -> Arabic address
low, bank, doubled, entries_low, entries_bank = struct.unpack_from(
    "<HBHHB",
    rom,
    overlay.rom_offset(overlay.TABLE_LIST),  # the first table: truce
)
entry = overlay.rom_offset((entries_bank << 16 | entries_low) + 3 * 6)
rom[entry : entry + 3] = redirects[TABLES["fair"].address, 41].to_bytes(3, "little")
overlay.set_checksum(rom)
Path("variant.sfc").write_bytes(rom)
```

The choice's cursor needs the event's choice mode, so a choice pointed at this way shows
its lines without it; `poke system_ram:0x163 00` in the script draws the cursor on the
first line while the box is open. The original of any message, in the notation, is
`engines.chrono_trigger.string_notation(engines.chrono_trigger.string_bytes(rom, at),
engines.chrono_trigger.dictionary(rom))` with `at` from `table_string(rom, table, number)`
on the unpatched ROM; `targets extract` writes them all into a workspace.

## Limits

- Three of the fifteen dialogue tables are in Arabic; every other message, the menus, the
  battles and the rest of the game stay English.
- 223 glyph codes for all the Arabic; a message holds no Latin letters, and a name is the
  player's, in Latin letters, as an item's name is the game's.
- A box shows four lines of 232 pixels (220 indented); the encoder refuses more.
- The font is 9 pixels; no vowel marks, lam and alef stay two glyphs.
- The hooks tell an Arabic message by its bank: no dialogue table of the game lies in
  banks `$42` to `$5F`, which the overlay adds.
- The ROM grows to 6 MiB; an emulator or a flash cartridge must take an ExHiROM of that
  size, the mapping of Tales of Phantasia and Star Ocean. snes9x runs it, from power-on
  through the opening; the others were not tried.
